"""Gateway-only provisioning and lifecycle orchestration.

This module is the low-level layer that talks to the OpenClaw gateway RPC surface.
DB-backed workflows (template sync, lead-agent record creation) live in
`app.services.openclaw.provisioning_db`.
"""

from __future__ import annotations

import asyncio
import json
import posixpath
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.branding import get_branding
from app.core.config import settings
from app.core.logging import get_logger
from app.models.agents import AGENT_TYPE_BOARD_WORKER, AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services import souls_directory
from app.services.openclaw.constants import (
    BOARD_SHARED_TEMPLATE_MAP,
    DEFAULT_BOARD_AGENT_MODEL_PRIMARY,
    DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY,
    DEFAULT_EXTRA_IDENTITY_PROFILE,
    DEFAULT_GATEWAY_FILES,
    DEFAULT_HEARTBEAT_CONFIG,
    DEFAULT_IDENTITY_PROFILE,
    EXTRA_IDENTITY_PROFILE_FIELDS,
    HEARTBEAT_AGENT_TEMPLATE,
    HEARTBEAT_LEAD_TEMPLATE,
    IDENTITY_PROFILE_FIELDS,
    LEAD_GATEWAY_FILES,
    LEAD_TEMPLATE_MAP,
    MAIN_TEMPLATE_MAP,
    PRESERVE_AGENT_EDITABLE_FILES,
    ROLE_TEMPLATE_HEARTBEAT_PROMPT,
    ROLE_TEMPLATE_MODEL_PRIMARY,
    STANDALONE_TEMPLATE_MAP,
)
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import (
    OpenClawGatewayError,
    ensure_session,
    openclaw_call,
    send_message,
)
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.internal.agent_key import slugify
from app.services.openclaw.internal.session_keys import (
    board_agent_session_key,
    board_lead_session_key,
)
from app.services.openclaw.shared import GatewayAgentIdentity

if TYPE_CHECKING:
    from app.models.users import User

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProvisionOptions:
    """Toggles controlling provisioning write/reset behavior."""

    action: str = "provision"
    force_bootstrap: bool = False
    overwrite: bool = False


_ROLE_SOUL_MAX_CHARS = 24_000
_ROLE_SOUL_WORD_RE = re.compile(r"[a-z0-9]+")


def _is_missing_session_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    return any(
        marker in message
        for marker in (
            "not found",
            "unknown session",
            "no such session",
            "session does not exist",
        )
    )


def _is_missing_agent_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    if any(
        marker in message for marker in ("unknown agent", "no such agent", "agent does not exist")
    ):
        return True
    return "agent" in message and "not found" in message


# Error-message substrings that indicate a gateway rejected a file path as unsupported
# (e.g. paths with directory separators on older gateway firmware).
_UNSUPPORTED_FILE_PATTERNS = frozenset(
    {
        "unsupported file",
        "invalid path",
        "path separator",
        "path contains",
        "not a valid file",
        "illegal file",
    }
)


def _is_unsupported_file_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _UNSUPPORTED_FILE_PATTERNS)


# ---------------------------------------------------------------------------
# Per-gateway rejected-file capability cache
# ---------------------------------------------------------------------------
# Tracks file names that a specific gateway has permanently rejected with an
# "unsupported" error.  Keyed by gateway ID (str).  Avoids re-sending files
# that are known to be incompatible with the connected gateway firmware, which
# saves ~2 failed RPC calls per provisioning cycle (skills/…, tools/…).
# In-process only — clears on restart, which is the safe default.
_GATEWAY_REJECTED_FILES: dict[str, set[str]] = {}


def _mark_file_rejected(gateway_id: str, file_name: str) -> None:
    _GATEWAY_REJECTED_FILES.setdefault(gateway_id, set()).add(file_name)


def _is_file_rejected(gateway_id: str, file_name: str) -> bool:
    return file_name in _GATEWAY_REJECTED_FILES.get(gateway_id, set())


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _templates_root() -> Path:
    return _repo_root() / "templates"


def _heartbeat_config(agent: Agent) -> dict[str, Any]:
    merged = DEFAULT_HEARTBEAT_CONFIG.copy()
    if isinstance(agent.heartbeat_config, dict):
        merged.update(agent.heartbeat_config)
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    role_template = profile.get("role_template")
    if (
        isinstance(role_template, str)
        and role_template in ROLE_TEMPLATE_HEARTBEAT_PROMPT
        and not (
            isinstance(agent.heartbeat_config, dict)
            and isinstance(agent.heartbeat_config.get("prompt"), str)
            and agent.heartbeat_config["prompt"].strip()
        )
    ):
        merged["prompt"] = ROLE_TEMPLATE_HEARTBEAT_PROMPT[role_template]
    return merged


def _model_override_from_config(value: object) -> dict[str, object] | str | None:
    """Normalize a configured model override into OpenClaw's accepted shape."""

    if value is None:
        return None
    if isinstance(value, str):
        primary = value.strip()
        return {"primary": primary} if primary else None
    if not isinstance(value, dict):
        return None

    primary_value = value.get("primary") or value.get("model") or value.get("model_primary")
    if not isinstance(primary_value, str) or not primary_value.strip():
        return None

    result: dict[str, object] = {"primary": primary_value.strip()}
    raw_fallbacks = value.get("fallbacks") or value.get("model_fallbacks")
    if isinstance(raw_fallbacks, list):
        fallbacks = [str(item).strip() for item in raw_fallbacks if str(item).strip()]
        if fallbacks:
            result["fallbacks"] = fallbacks
    return result


def _builtin_agent_model_routing() -> tuple[
    dict[str, dict[str, object] | str],
    dict[str, object] | str | None,
]:
    return (
        {role: {"primary": primary} for role, primary in ROLE_TEMPLATE_MODEL_PRIMARY.items()},
        {"primary": DEFAULT_BOARD_AGENT_MODEL_PRIMARY},
    )


def _configured_agent_model_routing() -> tuple[
    dict[str, dict[str, object] | str],
    dict[str, object] | str | None,
]:
    """Return model routing from runtime config, with source defaults as fallback."""

    role_models, default_board_model = _builtin_agent_model_routing()
    raw_config = (settings.agent_model_routing or "").strip()
    if not raw_config:
        return role_models, default_board_model

    try:
        config = json.loads(raw_config)
    except json.JSONDecodeError:
        logger.warning("agent_model_routing.invalid_json")
        return role_models, default_board_model

    if not isinstance(config, dict):
        logger.warning("agent_model_routing.invalid_shape")
        return role_models, default_board_model

    configured_default = _model_override_from_config(
        config.get("default_board_agent")
        or config.get("default_board_agent_model")
        or config.get("default_board_agent_model_primary")
    )
    if configured_default is not None:
        default_board_model = configured_default

    configured_roles = config.get("roles") or config.get("role_template_models")
    if isinstance(configured_roles, dict):
        role_models = {
            role: model
            for role, raw_model in configured_roles.items()
            if isinstance(role, str)
            for model in [_model_override_from_config(raw_model)]
            if model is not None
        }

    return role_models, default_board_model


def _agent_model_config(agent: Agent) -> dict[str, object] | str | None:
    """Return an OpenClaw agents.list[].model override for an agent."""

    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    explicit_primary = profile.get("model_primary")
    if isinstance(explicit_primary, str) and explicit_primary.strip():
        primary = explicit_primary.strip()
        raw_fallbacks = profile.get("model_fallbacks")
        if isinstance(raw_fallbacks, list):
            fallbacks = [str(item).strip() for item in raw_fallbacks if str(item).strip()]
            return {"primary": primary, "fallbacks": fallbacks}
        return {"primary": primary}

    role_template = profile.get("role_template")
    role_models, default_board_model = _configured_agent_model_routing()
    if not isinstance(role_template, str):
        if (
            getattr(agent, "board_id", None) is not None
            and getattr(agent, "agent_type", None) == AGENT_TYPE_BOARD_WORKER
            and not getattr(agent, "is_board_lead", False)
        ):
            return role_models.get("developer", default_board_model)
        if getattr(agent, "board_id", None) is not None:
            return default_board_model
        return None
    model = role_models.get(role_template)
    if not model:
        if getattr(agent, "board_id", None) is not None:
            return default_board_model
        return None
    return model


def _agent_session_model(agent: Agent) -> str | None:
    """Return an OpenClaw sessions.patch model ref for legacy string-only overrides.

    OpenClaw sessions.patch only accepts a single model string. AxiaCraft's
    configured role routing can include fallbacks, so object-shaped model
    policies must stay on agents.list where OpenClaw can resolve both the
    primary and fallback chain for the agent session.
    """
    model_config = _agent_model_config(agent)
    if isinstance(model_config, str):
        return model_config
    return None


def _agent_session_should_clear_model(agent: Agent) -> bool:
    """Return whether sessions.patch should clear a stale session model override."""
    return isinstance(_agent_model_config(agent), dict)


def _tools_exec_host_patch(config_data: dict[str, Any]) -> dict[str, Any] | None:
    """Ensure ``tools.exec.host`` is set to ``"gateway"`` so agents can run commands.

    Without this, heartbeat-driven agents cannot execute ``curl``, ``bash``, or
    any other shell command — making HEARTBEAT.md instructions unexecutable.
    Returns a partial ``tools`` dict to merge into ``config.patch``, or ``None``
    if the setting is already present.
    """
    tools = config_data.get("tools")
    if not isinstance(tools, dict):
        return {"exec": {"host": "gateway"}}
    exec_cfg = tools.get("exec")
    if not isinstance(exec_cfg, dict):
        return {"exec": {"host": "gateway"}}
    if exec_cfg.get("host") == "gateway":
        return None  # Already configured correctly for container-hosted agents.
    return {"exec": {"host": "gateway"}}


def _channel_heartbeat_visibility_patch(config_data: dict[str, Any]) -> dict[str, Any] | None:
    """Build a minimal patch ensuring channel default heartbeat visibility is configured.

    Gateways may have existing channel config; we only want to fill missing keys rather than
    overwrite operator intent. Returns `None` if no change is needed, otherwise returns a shallow
    patch dict suitable for a config merge."""
    channels = config_data.get("channels")
    if not isinstance(channels, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}

    defaults = channels.get("defaults")
    if not isinstance(defaults, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}

    heartbeat = defaults.get("heartbeat")
    if not isinstance(heartbeat, dict):
        return {"defaults": {"heartbeat": DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.copy()}}

    merged = dict(heartbeat)
    changed = False
    for key, value in DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY.items():
        if key not in merged:
            merged[key] = value
            changed = True

    if not changed:
        return None

    return {"defaults": {"heartbeat": merged}}


def _template_env() -> Environment:
    """Create the Jinja environment used for gateway template rendering.

    Note: we intentionally disable auto-escaping so markdown/plaintext templates render verbatim.
    """

    return Environment(
        loader=FileSystemLoader(_templates_root()),
        # Render markdown verbatim (HTML escaping makes it harder for agents to read).
        autoescape=select_autoescape(default=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def _heartbeat_template_name(agent: Agent) -> str:
    return HEARTBEAT_LEAD_TEMPLATE if agent.is_board_lead else HEARTBEAT_AGENT_TEMPLATE


def _workspace_path(agent: Agent, workspace_root: str) -> str:
    """Return the absolute on-disk workspace directory for an agent.

    Why this exists:
    - We derive the folder name from a stable *agent key* (ultimately rooted in ids/session keys)
      rather than display names to avoid collisions.
    - We preserve a historical gateway-main naming quirk to avoid moving existing directories.

    This path is later interpolated into template files (TOOLS.md, etc.) that agents treat as the
    source of truth for where to read/write.
    """

    if not workspace_root:
        msg = "gateway_workspace_root is required"
        raise ValueError(msg)

    root = workspace_root.rstrip("/")

    # Use agent key derived from session key when possible. This prevents collisions for
    # lead agents (session key includes board id) even if multiple boards share the same
    # display name (e.g. "Lead Agent").
    key = _agent_key(agent)

    # Backwards-compat: gateway-main agents historically used session keys that encoded
    # "gateway-<id>" while the gateway agent id is "mc-gateway-<id>".
    # Keep the on-disk workspace path stable so existing provisioned files aren't moved.
    if key.startswith("mc-gateway-"):
        key = key.removeprefix("mc-")

    return f"{root}/workspace-{slugify(key)}"


def _shared_source_root(workspace_root: str) -> str:
    """Return the shared source-code root adjacent to the gateway agent workspaces."""
    root = workspace_root.rstrip("/")
    parent, leaf = posixpath.split(root)
    if leaf == "agents" and parent:
        return posixpath.join(parent, "shared-src")
    return posixpath.join(root, "shared-src")


def _board_code_workspace_root(board: Board, workspace_root: str) -> str:
    board_slug = slugify(board.slug or board.name or str(board.id))
    return posixpath.join(_shared_source_root(workspace_root), "boards", board_slug)


def _board_code_worktree_path(agent: Agent, board: Board, workspace_root: str) -> str:
    root = _board_code_workspace_root(board, workspace_root)
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    role_template = str(profile.get("role_template") or "").strip()
    if agent.is_board_lead:
        return posixpath.join(root, "main")
    if role_template == "merger":
        return posixpath.join(root, "worktrees", "merge")
    worktree_slug = slugify(f"{agent.name}-{str(agent.id)[:8]}")
    return posixpath.join(root, "worktrees", worktree_slug)


def _board_code_repo_url(board: Board) -> str:
    context = board.context if isinstance(board.context, dict) else {}
    for key in (
        "production_repo_url",
        "repo_url",
        "repository_url",
        "source_repo_url",
        "prototype_repo_url",
    ):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _email_local_part(email: str) -> str:
    normalized = email.strip()
    if not normalized:
        return ""
    local, _sep, _domain = normalized.partition("@")
    return local.strip() or normalized


def _display_name(user: User | None) -> str:
    if user is None:
        return ""
    name = (user.name or "").strip()
    if name:
        return name
    return (user.email or "").strip()


def _preferred_name(user: User | None) -> str:
    preferred_name = (user.preferred_name or "") if user else ""
    if preferred_name:
        preferred_name = preferred_name.strip().split()[0]
    if preferred_name:
        return preferred_name
    display_name = _display_name(user)
    if display_name:
        if "@" in display_name:
            return _email_local_part(display_name)
        return display_name.split()[0]
    email = (user.email or "") if user else ""
    return _email_local_part(email)


def _user_context(user: User | None) -> dict[str, str]:
    return {
        "user_name": _display_name(user),
        "user_preferred_name": _preferred_name(user),
        "user_pronouns": (user.pronouns or "") if user else "",
        "user_timezone": (user.timezone or "") if user else "",
        "user_notes": (user.notes or "") if user else "",
        "user_context": (user.context or "") if user else "",
    }


def _normalized_identity_profile(agent: Agent) -> dict[str, str]:
    identity_profile: dict[str, Any] = {}
    if isinstance(agent.identity_profile, dict):
        identity_profile = agent.identity_profile
    normalized_identity: dict[str, str] = {}
    for key, value in identity_profile.items():
        if value is None:
            continue
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            if not parts:
                continue
            normalized_identity[key] = ", ".join(parts)
            continue
        text = str(value).strip()
        if text:
            normalized_identity[key] = text
    return normalized_identity


def _identity_context(agent: Agent) -> dict[str, str]:
    normalized_identity = _normalized_identity_profile(agent)
    identity_context = {
        context_key: normalized_identity.get(field, DEFAULT_IDENTITY_PROFILE[field])
        for field, context_key in IDENTITY_PROFILE_FIELDS.items()
    }
    extra_identity_context = {
        context_key: normalized_identity.get(field, DEFAULT_EXTRA_IDENTITY_PROFILE.get(field, ""))
        for field, context_key in EXTRA_IDENTITY_PROFILE_FIELDS.items()
    }
    return {**identity_context, **extra_identity_context}


def _role_slug(role: str) -> str:
    tokens = _ROLE_SOUL_WORD_RE.findall(role.strip().lower())
    return "-".join(tokens)


def _select_role_soul_ref(
    refs: list[souls_directory.SoulRef],
    *,
    role: str,
) -> souls_directory.SoulRef | None:
    role_slug = _role_slug(role)
    if not role_slug:
        return None

    exact_slug = next((ref for ref in refs if ref.slug.lower() == role_slug), None)
    if exact_slug is not None:
        return exact_slug

    prefix_matches = [ref for ref in refs if ref.slug.lower().startswith(f"{role_slug}-")]
    if prefix_matches:
        return sorted(prefix_matches, key=lambda ref: len(ref.slug))[0]

    contains_matches = [ref for ref in refs if role_slug in ref.slug.lower()]
    if contains_matches:
        return sorted(contains_matches, key=lambda ref: len(ref.slug))[0]

    role_tokens = [token for token in role_slug.split("-") if token]
    if len(role_tokens) < 2:
        return None

    scored: list[tuple[int, souls_directory.SoulRef]] = []
    for ref in refs:
        haystack = f"{ref.handle}-{ref.slug}".lower()
        token_hits = sum(1 for token in role_tokens if token in haystack)
        if token_hits >= 2:
            scored.append((token_hits, ref))
    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], len(item[1].slug)))
    return scored[0][1]


async def _resolve_role_soul_markdown(role: str) -> tuple[str, str]:
    if not role.strip():
        return "", ""
    try:
        refs = await souls_directory.list_souls_directory_refs()
        matched_ref = _select_role_soul_ref(refs, role=role)
        if matched_ref is None:
            return "", ""
        content = await souls_directory.fetch_soul_markdown(
            handle=matched_ref.handle,
            slug=matched_ref.slug,
        )
        normalized = content.strip()
        if not normalized:
            return "", ""
        if len(normalized) > _ROLE_SOUL_MAX_CHARS:
            normalized = normalized[:_ROLE_SOUL_MAX_CHARS]
        return normalized, matched_ref.page_url
    except Exception:
        # Best effort only. Provisioning must remain robust even if directory is unavailable.
        return "", ""


def _build_context(
    agent: Agent,
    board: Board,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    if not gateway.workspace_root:
        msg = "gateway_workspace_root is required"
        raise ValueError(msg)
    agent_id = str(agent.id)
    workspace_root = gateway.workspace_root
    workspace_path = _workspace_path(agent, workspace_root)
    code_workspace_root = _board_code_workspace_root(board, workspace_root)
    code_worktree_path = _board_code_worktree_path(agent, board, workspace_root)
    session_key = agent.openclaw_session_id or ""
    base_url = settings.base_url
    main_session_key = GatewayAgentIdentity.session_key(gateway)
    identity_context = _identity_context(agent)
    user_context = _user_context(user)
    return {
        "agent_name": agent.name,
        "agent_id": agent_id,
        "board_id": str(board.id),
        "board_name": board.name,
        "board_type": board.board_type,
        "board_objective": board.objective or "",
        "board_success_metrics": json.dumps(board.success_metrics or {}),
        "board_target_date": board.target_date.isoformat() if board.target_date else "",
        "board_goal_confirmed": str(board.goal_confirmed).lower(),
        "board_rule_require_approval_for_done": str(board.require_approval_for_done).lower(),
        "board_rule_require_review_before_done": str(board.require_review_before_done).lower(),
        "board_rule_comment_required_for_review": str(board.comment_required_for_review).lower(),
        "board_rule_block_status_changes_with_pending_approval": str(
            board.block_status_changes_with_pending_approval
        ).lower(),
        "board_rule_only_lead_can_change_status": str(board.only_lead_can_change_status).lower(),
        "board_rule_max_agents": str(board.max_agents),
        "is_board_lead": str(agent.is_board_lead).lower(),
        "is_platform_board": str(board.is_platform).lower(),
        "is_main_agent": "false",
        "session_key": session_key,
        "workspace_path": workspace_path,
        "code_repo_url": _board_code_repo_url(board),
        "code_workspace_root": code_workspace_root,
        "code_worktree_path": code_worktree_path,
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": main_session_key,
        "workspace_root": workspace_root,
        "product_name": get_branding().product_name,
        "company_name": get_branding().company_name,
        **user_context,
        **identity_context,
    }


def _build_main_context(
    agent: Agent,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    base_url = settings.base_url
    identity_context = _identity_context(agent)
    user_context = _user_context(user)
    return {
        "agent_name": agent.name,
        "agent_id": str(agent.id),
        "is_main_agent": "true",
        "is_standalone": "false",
        "session_key": agent.openclaw_session_id or "",
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": GatewayAgentIdentity.session_key(gateway),
        "workspace_root": gateway.workspace_root or "",
        "product_name": get_branding().product_name,
        "company_name": get_branding().company_name,
        **user_context,
        **identity_context,
    }


def _build_standalone_context(
    agent: Agent,
    gateway: Gateway,
    auth_token: str,
    user: User | None,
) -> dict[str, str]:
    """Build template context for a standalone (boardless, non-main) agent."""
    base_url = settings.base_url
    identity_context = _identity_context(agent)
    user_context = _user_context(user)
    return {
        "agent_name": agent.name,
        "agent_id": str(agent.id),
        "is_main_agent": "false",
        "is_standalone": "true",
        "is_board_lead": "false",
        "board_id": "",
        "board_name": "",
        "session_key": agent.openclaw_session_id or "",
        "base_url": base_url,
        "auth_token": auth_token,
        "main_session_key": GatewayAgentIdentity.session_key(gateway),
        "workspace_root": gateway.workspace_root or "",
        "product_name": get_branding().product_name,
        "company_name": get_branding().company_name,
        **user_context,
        **identity_context,
    }


def _session_key(agent: Agent) -> str:
    """Return the deterministic session key for a board-scoped agent.

    Note: Never derive session keys from a human-provided name; use stable ids instead.
    """

    if agent.is_board_lead and agent.board_id is not None:
        return board_lead_session_key(agent.board_id)
    return board_agent_session_key(agent.id)


def _render_agent_files(
    context: dict[str, str],
    agent: Agent,
    file_names: set[str],
    *,
    include_bootstrap: bool,
    template_overrides: dict[str, str] | None = None,
    db_templates: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render agent workspace files from templates.

    Template resolution cascade (highest priority first):
    1. Per-agent override (agent.identity_template / agent.soul_template)
    2. DB-stored override (board or org level, passed via ``db_templates``)
    3. Built-in .j2 file on disk (backend/templates/)
    """
    env = _template_env()
    overrides: dict[str, str] = {}
    if agent.identity_template:
        overrides["IDENTITY.md"] = agent.identity_template
    if agent.soul_template:
        overrides["SOUL.md"] = agent.soul_template

    rendered: dict[str, str] = {}
    for name in sorted(file_names):
        if name == "BOOTSTRAP.md" and not include_bootstrap:
            continue
        if name == "HEARTBEAT.md":
            heartbeat_template = (
                template_overrides[name]
                if template_overrides and name in template_overrides
                else _heartbeat_template_name(agent)
            )
            heartbeat_path = _templates_root() / heartbeat_template
            if not heartbeat_path.exists():
                msg = f"Missing template file: {heartbeat_template}"
                raise FileNotFoundError(msg)
            rendered[name] = env.get_template(heartbeat_template).render(**context).strip()
            continue
        # 1. Per-agent override (identity_template / soul_template)
        override = overrides.get(name)
        if override:
            rendered[name] = env.from_string(override).render(**context).strip()
            continue
        # 2. DB-stored template override (board-level or org-level)
        if db_templates and name in db_templates:
            rendered[name] = env.from_string(db_templates[name]).render(**context).strip()
            continue
        # 3. Built-in .j2 template from disk
        template_name = (
            template_overrides[name] if template_overrides and name in template_overrides else name
        )
        if template_name == "SOUL.md":
            # Use shared Jinja soul template as the default implementation.
            template_name = "BOARD_SOUL.md.j2"
        path = _templates_root() / template_name
        if not path.exists():
            msg = f"Missing template file: {template_name}"
            raise FileNotFoundError(msg)
        rendered[name] = env.get_template(template_name).render(**context).strip()
    return rendered


@dataclass(frozen=True, slots=True)
class GatewayAgentRegistration:
    """Desired gateway runtime state for one agent."""

    agent_id: str
    name: str
    workspace_path: str
    heartbeat: dict[str, Any]
    model: dict[str, object] | str | None = None


class GatewayControlPlane(ABC):
    """Abstract gateway runtime interface used by agent lifecycle managers."""

    @abstractmethod
    async def health(self) -> object:
        raise NotImplementedError

    @abstractmethod
    async def ensure_agent_session(self, session_key: str, *, label: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def reset_agent_session(self, session_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent_session(self, session_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upsert_agent(self, registration: GatewayAgentRegistration) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_agent_files(self, agent_id: str) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_agent_file_payload(self, *, agent_id: str, name: str) -> object:
        raise NotImplementedError

    @abstractmethod
    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_agent_file(self, *, agent_id: str, name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def patch_agent_heartbeats(
        self,
        entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]],
    ) -> None:
        raise NotImplementedError


class OpenClawGatewayControlPlane(GatewayControlPlane):
    """OpenClaw gateway RPC implementation of the lifecycle control-plane contract."""

    def __init__(self, config: GatewayClientConfig) -> None:
        self._config = config

    async def health(self) -> object:
        return await openclaw_call("health", config=self._config)

    async def ensure_agent_session(self, session_key: str, *, label: str | None = None) -> None:
        if not session_key:
            return
        await ensure_session(session_key, config=self._config, label=label)

    async def reset_agent_session(self, session_key: str) -> None:
        if not session_key:
            return
        await openclaw_call("sessions.reset", {"key": session_key}, config=self._config)

    async def delete_agent_session(self, session_key: str) -> None:
        if not session_key:
            return
        await openclaw_call("sessions.delete", {"key": session_key}, config=self._config)

    async def upsert_agent(self, registration: GatewayAgentRegistration) -> None:
        # Update-first, create-on-missing flow.
        #
        # Prior implementation always tried `agents.create` first and treated
        # "already exists" as a soft failure. That approach was correct logically
        # but expensive on the contended Premium NFS mount: openclaw serializes
        # all `agents.*` RPCs on its config file, and a failing `agents.create`
        # has been observed at 5–25 s under concurrent reconcile load (it has
        # to acquire the config lock and read the entire `openclaw.json` to
        # decide the agent already exists). With ~12 agents reconciling every
        # 10 minutes, those 5–25 s "failures" stacked into the 60 s reconcile
        # timeout and starved out the wake / heartbeat-patch steps further down
        # the pipeline, leaving agents perpetually `last_seen_at=NULL`.
        #
        # By trying `agents.update` first we hit the hot path (sub-second) for
        # every reconcile of an existing agent. The `agent not found` fallback
        # to `agents.create` covers fresh provisions and the rare case where
        # openclaw lost its config (gateway worker rebuild without state).
        try:
            await openclaw_call(
                "agents.update",
                {
                    "agentId": registration.agent_id,
                    "name": registration.name,
                    "workspace": registration.workspace_path,
                },
                config=self._config,
            )
            return
        except OpenClawGatewayError as exc:
            if not _is_missing_agent_error(exc):
                raise

        # Agent missing on the gateway side — fall back to create.
        await openclaw_call(
            "agents.create",
            {
                "name": registration.agent_id,
                "workspace": registration.workspace_path,
            },
            config=self._config,
        )

        # Gateway hot-reload has a ~500ms debounce after agents.create writes to
        # disk. A follow-up call arriving before the reload completes can return
        # "agent not found". Wait for the reload window, then issue agents.update
        # so the agent's heartbeat / workspace metadata are captured.
        await asyncio.sleep(0.75)
        _update_retries = 5
        _update_delay = 0.5
        for _attempt in range(_update_retries):
            try:
                await openclaw_call(
                    "agents.update",
                    {
                        "agentId": registration.agent_id,
                        "name": registration.name,
                        "workspace": registration.workspace_path,
                    },
                    config=self._config,
                )
                break
            except OpenClawGatewayError as exc:
                if _is_missing_agent_error(exc) and _attempt < _update_retries - 1:
                    await asyncio.sleep(_update_delay)
                    _update_delay = min(_update_delay * 2, 4.0)
                    continue
                raise

    async def delete_agent(self, agent_id: str, *, delete_files: bool = True) -> None:
        await openclaw_call(
            "agents.delete",
            {"agentId": agent_id, "deleteFiles": delete_files},
            config=self._config,
        )

    async def list_agent_files(self, agent_id: str) -> dict[str, dict[str, Any]]:
        payload = await openclaw_call(
            "agents.files.list",
            {"agentId": agent_id},
            config=self._config,
        )
        if not isinstance(payload, dict):
            return {}
        files = payload.get("files") or []
        if not isinstance(files, list):
            return {}
        index: dict[str, dict[str, Any]] = {}
        for item in files:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name:
                name = item.get("path")
            if isinstance(name, str) and name:
                index[name] = dict(item)
        return index

    async def get_agent_file_payload(self, *, agent_id: str, name: str) -> object:
        return await openclaw_call(
            "agents.files.get",
            {"agentId": agent_id, "name": name},
            config=self._config,
        )

    async def set_agent_file(self, *, agent_id: str, name: str, content: str) -> None:
        _set_retries = 5
        _set_delay = 0.5
        for _attempt in range(_set_retries):
            try:
                await openclaw_call(
                    "agents.files.set",
                    {"agentId": agent_id, "name": name, "content": content},
                    config=self._config,
                )
                return
            except OpenClawGatewayError as exc:
                if _is_missing_agent_error(exc) and _attempt < _set_retries - 1:
                    await asyncio.sleep(_set_delay)
                    _set_delay = min(_set_delay * 2, 4.0)
                    continue
                raise

    async def delete_agent_file(self, *, agent_id: str, name: str) -> None:
        await openclaw_call(
            "agents.files.delete",
            {"agentId": agent_id, "name": name},
            config=self._config,
        )

    async def patch_agent_heartbeats(
        self,
        entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]],
    ) -> None:
        base_hash, raw_list, config_data = await _gateway_config_agent_list(self._config)
        entry_by_id = _heartbeat_entry_map(entries)
        new_list = _updated_agent_list(raw_list, entry_by_id)

        tools_patch = _tools_exec_host_patch(config_data)

        # NOTE: we deliberately do NOT emit a `channels` patch here, even though
        # `_channel_heartbeat_visibility_patch` exists. openclaw treats
        # `channels` as a non-hot-reloadable path and schedules a full gateway
        # restart whenever it changes (close code 1012 on every WS connection).
        # When this ran on every per-agent reconcile, the openclaw config file
        # was rewritten on each restart — losing the heartbeat-visibility
        # defaults — so the next reconcile detected them missing again and
        # emitted another channels patch, restarting the gateway again.
        # Result: divergent retry loop, agents never finished provisioning.
        # Channel heartbeat defaults are an ergonomic concern that belongs in
        # gateway templates/sync (a one-shot bootstrap), not the per-agent
        # path. See `_channel_heartbeat_visibility_patch`; templates/sync can
        # call it at gateway-create time without restart-cascade risk.

        # Skip config.patch entirely when nothing changed — avoids an unnecessary
        # gateway SIGUSR1 restart that rotates agent tokens and breaks active sessions.
        if new_list == raw_list and tools_patch is None:
            logger.debug("patch_agent_heartbeats: no changes detected, skipping config.patch")
            return

        patch: dict[str, Any] = {"agents": {"list": new_list}}
        if tools_patch is not None:
            patch["tools"] = tools_patch
        params = {"raw": json.dumps(patch)}
        if base_hash:
            params["baseHash"] = base_hash
        await openclaw_call("config.patch", params, config=self._config)


async def _gateway_config_agent_list(
    config: GatewayClientConfig,
) -> tuple[str | None, list[object], dict[str, Any]]:
    cfg = await openclaw_call("config.get", config=config)
    if not isinstance(cfg, dict):
        msg = "config.get returned invalid payload"
        raise OpenClawGatewayError(msg)

    data = cfg.get("config") or cfg.get("parsed") or {}
    if not isinstance(data, dict):
        msg = "config.get returned invalid config"
        raise OpenClawGatewayError(msg)

    agents_section = data.get("agents") or {}
    agents_list = agents_section.get("list") or []
    if not isinstance(agents_list, list):
        msg = "config agents.list is not a list"
        raise OpenClawGatewayError(msg)
    return cfg.get("hash"), agents_list, data


def _heartbeat_entry_map(
    entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]],
) -> dict[str, tuple[str, dict[str, Any], dict[str, object] | str | None]]:
    return {
        agent_id: (workspace_path, heartbeat, model)
        for agent_id, workspace_path, heartbeat, model in entries
    }


def _updated_agent_list(
    raw_list: list[object],
    entry_by_id: dict[str, tuple[str, dict[str, Any], dict[str, object] | str | None]],
) -> list[object]:
    updated_ids: set[str] = set()
    new_list: list[object] = []

    for raw_entry in raw_list:
        if not isinstance(raw_entry, dict):
            new_list.append(raw_entry)
            continue
        agent_id = raw_entry.get("id")
        if not isinstance(agent_id, str) or agent_id not in entry_by_id:
            new_list.append(raw_entry)
            continue

        workspace_path, heartbeat, model = entry_by_id[agent_id]
        new_entry = dict(raw_entry)
        new_entry["workspace"] = workspace_path
        new_entry["heartbeat"] = heartbeat
        if model is not None:
            new_entry["model"] = model
        elif "model" in new_entry:
            del new_entry["model"]
        new_list.append(new_entry)
        updated_ids.add(agent_id)

    for agent_id, (workspace_path, heartbeat, model) in entry_by_id.items():
        if agent_id in updated_ids:
            continue
        entry: dict[str, object] = {
            "id": agent_id,
            "workspace": workspace_path,
            "heartbeat": heartbeat,
        }
        if model is not None:
            entry["model"] = model
        new_list.append(entry)

    return new_list


class BaseAgentLifecycleManager(ABC):
    """Base class for scalable board/main agent lifecycle managers."""

    def __init__(self, gateway: Gateway, control_plane: GatewayControlPlane) -> None:
        self._gateway = gateway
        self._control_plane = control_plane

    async def _resolve_org_branding(self) -> dict[str, str]:
        """Fetch org branding overrides and merge with deployment defaults.

        Returns a dict with ``product_name`` and ``company_name`` keys, preferring
        the organization-level override when set.
        """
        branding = get_branding()
        product_name = branding.product_name
        company_name = branding.company_name
        try:
            from app.db.session import async_session_maker

            async with async_session_maker() as session:
                from sqlmodel import select

                org = (
                    await session.exec(
                        select(Organization).where(Organization.id == self._gateway.organization_id)
                    )
                ).first()
                if org and org.branding_overrides:
                    product_name = org.branding_overrides.get("product_name", product_name)
                    company_name = org.branding_overrides.get("company_name", company_name)
        except Exception:
            logger.debug("Failed to resolve org branding overrides, using defaults")
        return {"product_name": product_name, "company_name": company_name}

    @abstractmethod
    def _agent_id(self, agent: Agent) -> str:
        raise NotImplementedError

    @abstractmethod
    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        raise NotImplementedError

    async def _augment_context(
        self,
        *,
        agent: Agent,
        context: dict[str, str],
    ) -> dict[str, str]:
        _ = agent
        return context

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        return None

    def _file_names(self, agent: Agent) -> set[str]:
        _ = agent
        return set(DEFAULT_GATEWAY_FILES)

    def _preserve_files(self, agent: Agent) -> set[str]:
        _ = agent
        """Files that are expected to evolve inside the agent workspace."""
        return set(PRESERVE_AGENT_EDITABLE_FILES)

    def _allow_stale_file_deletion(self, agent: Agent) -> bool:
        _ = agent
        return False

    def _stale_file_candidates(self, agent: Agent) -> set[str]:
        _ = agent
        return set()

    async def _set_agent_files(
        self,
        *,
        agent: Agent | None = None,
        agent_id: str,
        rendered: dict[str, str],
        desired_file_names: set[str] | None = None,
        existing_files: dict[str, dict[str, Any]],
        action: str,
        overwrite: bool = False,
    ) -> None:
        preserve_files = (
            self._preserve_files(agent) if agent is not None else set(PRESERVE_AGENT_EDITABLE_FILES)
        )
        target_file_names = desired_file_names or set(rendered.keys())
        unsupported_names: list[str] = []
        gateway_id_str = str(self._gateway.id)

        for name, content in rendered.items():
            if content == "":
                continue
            # Skip files this gateway has previously rejected as unsupported.
            if _is_file_rejected(gateway_id_str, name):
                continue
            # Preserve "editable" files only during updates. During first-time provisioning,
            # the gateway may pre-create defaults for USER/MEMORY/etc, and we still want to
            # apply Product Foundry's templates.
            if action == "update" and not overwrite and name in preserve_files:
                entry = existing_files.get(name)
                if entry and not bool(entry.get("missing")):
                    continue
            try:
                await self._control_plane.set_agent_file(
                    agent_id=agent_id,
                    name=name,
                    content=content,
                )
            except OpenClawGatewayError as exc:
                if _is_unsupported_file_error(exc):
                    unsupported_names.append(name)
                    _mark_file_rejected(gateway_id_str, name)
                    continue
                raise

        if agent is not None and agent.is_board_lead and unsupported_names:
            unsupported_sorted = ", ".join(sorted(set(unsupported_names)))
            logger.warning(
                "gateway.files.unsupported_skipped agent_is_board_lead=True files=%s",
                unsupported_sorted,
            )

        if agent is None or not self._allow_stale_file_deletion(agent):
            return

        stale_names = (
            set(existing_files.keys()) & self._stale_file_candidates(agent)
        ) - target_file_names
        for name in sorted(stale_names):
            try:
                await self._control_plane.delete_agent_file(agent_id=agent_id, name=name)
            except OpenClawGatewayError as exc:
                message = str(exc).lower()
                if any(
                    marker in message
                    for marker in (
                        "unsupported",
                        "unknown method",
                        "not found",
                        "no such file",
                    )
                ):
                    continue
                raise

    async def provision(
        self,
        *,
        agent: Agent,
        session_key: str,
        auth_token: str | None,
        user: User | None,
        options: ProvisionOptions,
        board: Board | None = None,
        session_label: str | None = None,
        extra_files: dict[str, str] | None = None,
        db_templates: dict[str, str] | None = None,
    ) -> None:
        """Provision an agent on the gateway.

        ``auth_token=None`` means "this is an update for an agent that
        already has working workspace files (templates contain a token)".
        We still call ``upsert_agent`` to ensure the agent is registered in
        the gateway's ``agents.list`` (otherwise ``chat.send`` would fail
        with "Agent ... no longer exists in configuration" after a gateway
        restart). We skip the template/file rendering in that case to avoid
        clobbering the agent's existing AUTH_TOKEN with an empty value.
        """

        if not self._gateway.workspace_root:
            msg = "gateway_workspace_root is required"
            raise ValueError(msg)
        # Ensure templates render with the active deterministic session key.
        agent.openclaw_session_id = session_key

        agent_id = self._agent_id(agent)
        workspace_path = _workspace_path(agent, self._gateway.workspace_root)
        heartbeat = _heartbeat_config(agent)
        # Always register the agent — even on a token-preserving update —
        # so chat.send / heartbeat ticks can find it after a gateway restart.
        await self._control_plane.upsert_agent(
            GatewayAgentRegistration(
                agent_id=agent_id,
                name=agent.name,
                workspace_path=workspace_path,
                heartbeat=heartbeat,
                model=_agent_model_config(agent),
            ),
        )

        # Token-preserving update path: agent is registered, files left as-is.
        # Caller (lifecycle reconcile) will proceed to the wake step.
        if auth_token is None:
            return

        context = self._build_context(
            agent=agent,
            auth_token=auth_token,
            user=user,
            board=board,
        )
        context = await self._augment_context(agent=agent, context=context)
        # Merge org-level branding overrides on top of deployment defaults.
        org_branding = await self._resolve_org_branding()
        context.update(org_branding)
        # Always attempt to sync Product Foundry's full template set.
        # Do not introspect gateway defaults (avoids touching gateway "main" agent state).
        file_names = self._file_names(agent)
        existing_files = await self._control_plane.list_agent_files(agent_id)
        include_bootstrap = _should_include_bootstrap(
            action=options.action,
            force_bootstrap=options.force_bootstrap,
            existing_files=existing_files,
        )
        rendered = _render_agent_files(
            context,
            agent,
            file_names,
            include_bootstrap=include_bootstrap,
            template_overrides=self._template_overrides(agent),
            db_templates=db_templates,
        )

        await self._set_agent_files(
            agent=agent,
            agent_id=agent_id,
            rendered=rendered,
            desired_file_names=set(rendered.keys()),
            existing_files=existing_files,
            action=options.action,
            overwrite=options.overwrite,
        )

        # Write caller-supplied extra files (e.g. auth-profiles.json, skill config.env).
        # These are written after templates so they are never overwritten by template rendering.
        gateway_id_str = str(self._gateway.id)
        if extra_files:
            for name, content in extra_files.items():
                if _is_file_rejected(gateway_id_str, name):
                    continue
                try:
                    await self._control_plane.set_agent_file(
                        agent_id=agent_id,
                        name=name,
                        content=content,
                    )
                except OpenClawGatewayError as exc:
                    if _is_unsupported_file_error(exc):
                        _mark_file_rejected(gateway_id_str, name)
                        logger.warning(
                            "gateway.extra_file.unsupported_skipped name=%s",
                            name,
                        )
                        continue
                    raise


class BoardAgentLifecycleManager(BaseAgentLifecycleManager):
    """Provisioning manager for board-scoped agents."""

    def _agent_id(self, agent: Agent) -> str:
        return _agent_key(agent)

    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        if board is None:
            msg = "board is required for board-scoped agent provisioning"
            raise ValueError(msg)
        return _build_context(agent, board, self._gateway, auth_token, user)

    async def _augment_context(
        self,
        *,
        agent: Agent,
        context: dict[str, str],
    ) -> dict[str, str]:
        context = dict(context)
        if agent.is_board_lead:
            context["directory_role_soul_markdown"] = ""
            context["directory_role_soul_source_url"] = ""
            # Query for platform board in the gateway
            from app.db.session import async_session_maker

            gateway_id = self._gateway.id
            try:
                async with async_session_maker() as session:
                    from sqlmodel import col, select

                    platform_board = await session.exec(
                        select(Board)
                        .where(col(Board.gateway_id) == gateway_id)
                        .where(col(Board.is_platform).is_(True))
                    )
                    platform_board_obj = platform_board.first()

                    if platform_board_obj:
                        context["has_platform_board"] = "true"
                        context["platform_board_name"] = platform_board_obj.name
                    else:
                        context["has_platform_board"] = "false"
                        context["platform_board_name"] = ""
            except Exception:
                # Best effort only. Provisioning must remain robust.
                context["has_platform_board"] = "false"
                context["platform_board_name"] = ""
            return context

        role = (context.get("identity_role") or "").strip()
        markdown, source_url = await _resolve_role_soul_markdown(role)
        context["directory_role_soul_markdown"] = markdown
        context["directory_role_soul_source_url"] = source_url
        return context

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        overrides = dict(BOARD_SHARED_TEMPLATE_MAP)
        if agent.is_board_lead:
            overrides.update(LEAD_TEMPLATE_MAP)
        return overrides

    def _file_names(self, agent: Agent) -> set[str]:
        if agent.is_board_lead:
            return set(LEAD_GATEWAY_FILES)
        return super()._file_names(agent)

    def _allow_stale_file_deletion(self, agent: Agent) -> bool:
        return bool(agent.is_board_lead)

    def _stale_file_candidates(self, agent: Agent) -> set[str]:
        if not agent.is_board_lead:
            return set()
        return (
            set(DEFAULT_GATEWAY_FILES)
            | set(LEAD_GATEWAY_FILES)
            | {
                "USER.md",
                "ROUTING.md",
                "LEARNINGS.md",
                "ROLE.md",
                "WORKFLOW.md",
                "STATUS.md",
                "APIS.md",
            }
        )


class GatewayMainAgentLifecycleManager(BaseAgentLifecycleManager):
    """Provisioning manager for organization gateway-main agents."""

    def _agent_id(self, agent: Agent) -> str:
        return GatewayAgentIdentity.openclaw_agent_id(self._gateway)

    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        _ = board
        return _build_main_context(agent, self._gateway, auth_token, user)

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        _ = agent
        return MAIN_TEMPLATE_MAP

    def _preserve_files(self, agent: Agent) -> set[str]:
        _ = agent
        # For gateway-main agents, USER.md is system-managed (derived from org/user context),
        # so keep it in sync even during updates.
        preserved = super()._preserve_files(agent)
        preserved.discard("USER.md")
        return preserved


class StandaloneAgentLifecycleManager(BaseAgentLifecycleManager):
    """Provisioning manager for standalone (boardless) agents."""

    def _agent_id(self, agent: Agent) -> str:
        return _agent_key(agent)

    def _build_context(
        self,
        *,
        agent: Agent,
        auth_token: str,
        user: User | None,
        board: Board | None,
    ) -> dict[str, str]:
        _ = board
        return _build_standalone_context(agent, self._gateway, auth_token, user)

    def _template_overrides(self, agent: Agent) -> dict[str, str] | None:
        _ = agent
        return STANDALONE_TEMPLATE_MAP


def _control_plane_for_gateway(gateway: Gateway) -> OpenClawGatewayControlPlane:
    if not gateway.url:
        msg = "Gateway url is required"
        raise OpenClawGatewayError(msg)
    return OpenClawGatewayControlPlane(
        GatewayClientConfig(
            url=gateway.url,
            token=gateway.token,
            allow_insecure_tls=gateway.allow_insecure_tls,
            disable_device_pairing=gateway.disable_device_pairing,
        ),
    )


async def _patch_gateway_agent_heartbeats(
    gateway: Gateway,
    *,
    entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]],
) -> None:
    """Patch multiple agent heartbeat configs in a single gateway config.patch call.

    Each entry is (agent_id, workspace_path, heartbeat_dict, model_override).
    """
    control_plane = _control_plane_for_gateway(gateway)
    await control_plane.patch_agent_heartbeats(entries)


def _should_include_bootstrap(
    *,
    action: str,
    force_bootstrap: bool,
    existing_files: dict[str, dict[str, Any]],
) -> bool:
    if action != "update" or force_bootstrap:
        return True
    if not existing_files:
        return False
    entry = existing_files.get("BOOTSTRAP.md")
    return not bool(entry and entry.get("missing"))


def _wakeup_text(agent: Agent, *, verb: str) -> str:
    text = (
        f"Hello {agent.name}. Your workspace has been {verb}.\n\n"
        "Start the agent now. If BOOTSTRAP.md exists, read it first, then read "
        "AGENTS.md and HEARTBEAT.md.\n\n"
        "Execute HEARTBEAT.md in this same turn. If the heartbeat finds work, "
        "keep using tools until it produces the required concrete outcome. "
        "Return HEARTBEAT_OK only after the heartbeat cycle is complete or "
        "there is genuinely no work."
    )
    profile = agent.identity_profile if isinstance(agent.identity_profile, dict) else {}
    role_template = profile.get("role_template")
    if isinstance(role_template, str) and role_template in ROLE_TEMPLATE_HEARTBEAT_PROMPT:
        text += "\n\nRole-specific heartbeat requirement:\n"
        text += ROLE_TEMPLATE_HEARTBEAT_PROMPT[role_template]
    return text


class OpenClawGatewayProvisioner:
    """Gateway-only agent lifecycle interface (create -> files -> wake)."""

    async def sync_gateway_agent_heartbeats(self, gateway: Gateway, agents: list[Agent]) -> None:
        """Sync current Agent.heartbeat_config values to the gateway config."""
        if not gateway.workspace_root:
            msg = "gateway workspace_root is required"
            raise OpenClawGatewayError(msg)
        entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]] = []
        for agent in agents:
            agent_id = _agent_key(agent)
            workspace_path = _workspace_path(agent, gateway.workspace_root)
            heartbeat = _heartbeat_config(agent)
            entries.append((agent_id, workspace_path, heartbeat, _agent_model_config(agent)))
        if not entries:
            return
        await _patch_gateway_agent_heartbeats(gateway, entries=entries)

    async def apply_agent_lifecycle(
        self,
        *,
        agent: Agent,
        gateway: Gateway,
        board: Board | None,
        auth_token: str | None,
        user: User | None,
        action: str = "provision",
        force_bootstrap: bool = False,
        overwrite: bool = False,
        reset_session: bool = False,
        wake: bool = True,
        deliver_wakeup: bool = True,
        wakeup_verb: str | None = None,
        extra_files: dict[str, str] | None = None,
        db_templates: dict[str, str] | None = None,
        patch_heartbeat: bool = True,
    ) -> None:
        """Create/update an agent, sync all template files, and optionally wake the agent.

        Lifecycle steps (same for all agent types):
        1) create agent (idempotent)
        2) set/update all template files (skipped when ``auth_token is None``)
        3) wake the agent session (chat.send)
        4) patch heartbeat config (unless ``patch_heartbeat=False``)

        ``auth_token=None`` means "this is an update for an agent that already
        has working workspace files (and a working token in its env)". The
        file-push step is skipped — re-rendering with an empty token would
        clobber the agent's existing AUTH_TOKEN and break all its API calls.
        """

        logger.info(
            "gateway.apply_agent_lifecycle.start agent_id=%s name=%s action=%s wake=%s "
            "reset_session=%s board_id=%s auth_token_provided=%s",
            agent.id,
            agent.name,
            action,
            wake,
            reset_session,
            board.id if board is not None else None,
            auth_token is not None,
        )

        if not gateway.url:
            msg = "Gateway url is required"
            raise ValueError(msg)

        # Guard against accidental main-agent provisioning without a board.
        if board is None and getattr(agent, "board_id", None) is not None:
            msg = "board is required for board-scoped agent lifecycle"
            raise ValueError(msg)

        # Resolve session key and agent type.
        if board is None:
            session_key = (
                agent.openclaw_session_id or GatewayAgentIdentity.session_key(gateway) or ""
            ).strip()
            if not session_key:
                msg = "gateway main agent session_key is required"
                raise ValueError(msg)
            if agent.agent_type == AGENT_TYPE_STANDALONE:
                manager_type: type[BaseAgentLifecycleManager] = StandaloneAgentLifecycleManager
            else:
                manager_type = GatewayMainAgentLifecycleManager
        else:
            session_key = _session_key(agent)
            manager_type = BoardAgentLifecycleManager

        control_plane = _control_plane_for_gateway(gateway)
        manager = manager_type(gateway, control_plane)
        await manager.provision(
            agent=agent,
            board=board,
            session_key=session_key,
            auth_token=auth_token,
            user=user,
            options=ProvisionOptions(
                action=action,
                force_bootstrap=force_bootstrap,
                overwrite=overwrite,
            ),
            session_label=agent.name or "Gateway Agent",
            extra_files=extra_files,
            db_templates=db_templates,
        )

        if reset_session:
            try:
                await control_plane.reset_agent_session(session_key)
            except OpenClawGatewayError as exc:
                if not _is_missing_session_error(exc):
                    raise

        # Patch heartbeat config before waking the session. The wake message is
        # deliberately small; the runtime needs its current heartbeat entry and
        # workspace path in config before the first post-update turn starts.
        # Bulk callers (template sync) should set ``patch_heartbeat=False`` and
        # call ``sync_gateway_agent_heartbeats`` once at the end to avoid a
        # restart storm.
        if patch_heartbeat:
            agent_id = manager._agent_id(agent)
            workspace_path = _workspace_path(agent, gateway.workspace_root)
            heartbeat = _heartbeat_config(agent)
            try:
                await control_plane.patch_agent_heartbeats(
                    [(agent_id, workspace_path, heartbeat, _agent_model_config(agent))],
                )
            except (OpenClawGatewayError, TimeoutError) as exc:
                logger.warning(
                    "gateway.apply_agent_lifecycle.heartbeat_patch_failed agent_id=%s error=%s",
                    agent_id,
                    exc,
                )

        if wake:
            client_config = GatewayClientConfig(
                url=gateway.url,
                token=gateway.token,
                allow_insecure_tls=gateway.allow_insecure_tls,
                disable_device_pairing=gateway.disable_device_pairing,
            )
            await ensure_session(
                session_key,
                config=client_config,
                label=agent.name,
                model=_agent_session_model(agent),
                clear_model_override=_agent_session_should_clear_model(agent),
            )
            verb = wakeup_verb or ("provisioned" if action == "provision" else "updated")
            await send_message(
                _wakeup_text(agent, verb=verb),
                session_key=session_key,
                config=client_config,
                deliver=deliver_wakeup,
            )

    async def delete_agent_lifecycle(
        self,
        *,
        agent: Agent,
        gateway: Gateway,
        delete_files: bool = True,
        delete_session: bool = True,
    ) -> str | None:
        """Remove agent runtime state from the gateway (agent + optional session)."""

        if not gateway.url:
            msg = "Gateway url is required"
            raise ValueError(msg)
        if not gateway.workspace_root:
            msg = "gateway_workspace_root is required"
            raise ValueError(msg)

        workspace_path = _workspace_path(agent, gateway.workspace_root)
        control_plane = _control_plane_for_gateway(gateway)

        if agent.board_id is None:
            agent_gateway_id = GatewayAgentIdentity.openclaw_agent_id(gateway)
        else:
            agent_gateway_id = _agent_key(agent)
        try:
            await control_plane.delete_agent(agent_gateway_id, delete_files=delete_files)
        except OpenClawGatewayError as exc:
            if not _is_missing_agent_error(exc):
                raise

        if delete_session:
            if agent.board_id is None:
                session_key = (
                    agent.openclaw_session_id or GatewayAgentIdentity.session_key(gateway) or ""
                ).strip()
            else:
                session_key = _session_key(agent)
            if session_key:
                try:
                    await control_plane.delete_agent_session(session_key)
                except OpenClawGatewayError as exc:
                    if not _is_missing_session_error(exc):
                        raise

        return workspace_path
