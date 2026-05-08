"""Shared constants for lifecycle orchestration services."""

from __future__ import annotations

import random
import re
from datetime import timedelta
from typing import Any

_GATEWAY_OPENCLAW_AGENT_PREFIX = "mc-gateway-"
_GATEWAY_AGENT_PREFIX = f"agent:{_GATEWAY_OPENCLAW_AGENT_PREFIX}"
_GATEWAY_AGENT_SUFFIX = ":main"

DEFAULT_HEARTBEAT_CONFIG: dict[str, Any] = {
    # 5-minute interval (was 1m). With 17+ standalone+board agents, a 1m
    # heartbeat creates concurrent LLM call bursts that saturate Azure
    # Foundry per-minute TPM quotas. 5m gives the model providers room to
    # serve all agents without throttling.
    "every": "5m",
    "target": "last",
    "includeReasoning": False,
}

OFFLINE_AFTER = timedelta(minutes=10)
# Provisioning convergence policy — runtime values come from
# app.core.config.settings (agent_checkin_deadline_seconds /
# agent_max_wake_attempts) so operators can tune via env vars.
# These module-level names are kept for test/legacy import compatibility.
CHECKIN_DEADLINE_AFTER_WAKE = timedelta(seconds=120)
MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN = 5
AGENT_SESSION_PREFIX = "agent"

DEFAULT_CHANNEL_HEARTBEAT_VISIBILITY: dict[str, bool] = {
    # Suppress routine HEARTBEAT_OK delivery by default.
    "showOk": False,
    "showAlerts": True,
    "useIndicator": True,
}

DEFAULT_IDENTITY_PROFILE = {
    "role": "Generalist",
    "communication_style": "direct, concise, practical",
    "emoji": ":gear:",
}

IDENTITY_PROFILE_FIELDS = {
    "role": "identity_role",
    "communication_style": "identity_communication_style",
    "emoji": "identity_emoji",
}

EXTRA_IDENTITY_PROFILE_FIELDS = {
    "autonomy_level": "identity_autonomy_level",
    "verbosity": "identity_verbosity",
    "output_format": "identity_output_format",
    "update_cadence": "identity_update_cadence",
    # Per-agent charter (optional).
    # Used to give agents a "purpose in life" and a distinct vibe.
    "purpose": "identity_purpose",
    "personality": "identity_personality",
    "custom_instructions": "identity_custom_instructions",
    # Specialist role template — selects Jinja2 heartbeat/agents partials.
    "role_template": "identity_role_template",
}

# Default values for EXTRA_IDENTITY_PROFILE_FIELDS when not set in identity_profile.
# role_template must never be empty — the gateway worker maps it to a Jinja2 partial
# and silently hangs if given an empty string.
DEFAULT_EXTRA_IDENTITY_PROFILE: dict[str, str] = {
    "role_template": "developer",
}

DEFAULT_GATEWAY_FILES = frozenset(
    {
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "HEARTBEAT.md",
        "MEMORY.md",
        # BOOTSTRAP.md is part of every agent's first provision. Agents read it
        # once on startup, perform initial setup (verify tools, daily memory
        # file, first heartbeat curl), then DELETE the file. The
        # `_should_include_bootstrap` helper guards against re-issuing it on
        # update reconciles once the agent has consumed it (it checks for the
        # `missing` marker openclaw sets when the agent deletes the file). So
        # leaving this in the default set is safe and gives every newly-
        # provisioned agent — board lead, board worker, standalone, gateway
        # main — the bootstrap doc they need to actually send their first
        # heartbeat. Without it, board workers and standalones tried to read a
        # non-existent BOOTSTRAP.md and got ENOENT instead of bootstrap steps.
        "BOOTSTRAP.md",
    },
)

# Lead-only workspace contract. Used for board leads to allow an iterative rollout
# without changing worker templates.
LEAD_GATEWAY_FILES = frozenset(
    {
        "AGENTS.md",
        "BOOTSTRAP.md",
        "IDENTITY.md",
        "SOUL.md",
        "USER.md",
        "MEMORY.md",
        "TOOLS.md",
        "HEARTBEAT.md",
    },
)

# These files are intended to evolve within the agent workspace.
# Provision them if missing, but avoid overwriting existing content during updates.
#
# Examples:
# - USER.md: human-provided context + lead intake notes
# - MEMORY.md: curated long-term memory (consolidated)
PRESERVE_AGENT_EDITABLE_FILES = frozenset({"USER.md", "MEMORY.md"})

HEARTBEAT_LEAD_TEMPLATE = "BOARD_HEARTBEAT.md.j2"
HEARTBEAT_AGENT_TEMPLATE = "BOARD_HEARTBEAT.md.j2"
SESSION_KEY_PARTS_MIN = 2
_SESSION_KEY_PARTS_MIN = SESSION_KEY_PARTS_MIN

MAIN_TEMPLATE_MAP = {
    "AGENTS.md": "BOARD_AGENTS.md.j2",
    "BOOTSTRAP.md": "BOARD_BOOTSTRAP.md.j2",
    "IDENTITY.md": "BOARD_IDENTITY.md.j2",
    "SOUL.md": "BOARD_SOUL.md.j2",
    "MEMORY.md": "BOARD_MEMORY.md.j2",
    "HEARTBEAT.md": "BOARD_HEARTBEAT.md.j2",
    "USER.md": "BOARD_USER.md.j2",
    "TOOLS.md": "BOARD_TOOLS.md.j2",
}

BOARD_SHARED_TEMPLATE_MAP = {
    "AGENTS.md": "BOARD_AGENTS.md.j2",
    "BOOTSTRAP.md": "BOARD_BOOTSTRAP.md.j2",
    "IDENTITY.md": "BOARD_IDENTITY.md.j2",
    "SOUL.md": "BOARD_SOUL.md.j2",
    "MEMORY.md": "BOARD_MEMORY.md.j2",
    "HEARTBEAT.md": "BOARD_HEARTBEAT.md.j2",
    "USER.md": "BOARD_USER.md.j2",
    "TOOLS.md": "BOARD_TOOLS.md.j2",
}

LEAD_TEMPLATE_MAP: dict[str, str] = {}

# Template map for standalone agents (not attached to any board).
# Reuses BOARD_* templates which already branch on is_main / agent_type.
STANDALONE_TEMPLATE_MAP = {
    "AGENTS.md": "BOARD_AGENTS.md.j2",
    "BOOTSTRAP.md": "BOARD_BOOTSTRAP.md.j2",
    "IDENTITY.md": "BOARD_IDENTITY.md.j2",
    "SOUL.md": "BOARD_SOUL.md.j2",
    "MEMORY.md": "BOARD_MEMORY.md.j2",
    "HEARTBEAT.md": "BOARD_HEARTBEAT.md.j2",
    "USER.md": "BOARD_USER.md.j2",
    "TOOLS.md": "BOARD_TOOLS.md.j2",
}

_TOOLS_KV_RE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")
_NON_TRANSIENT_GATEWAY_ERROR_MARKERS = ("unsupported file",)
_TRANSIENT_GATEWAY_ERROR_MARKERS = (
    "connect call failed",
    "connection refused",
    "errno 111",
    "econnrefused",
    "did not receive a valid http response",
    "no route to host",
    "network is unreachable",
    "host is down",
    "name or service not known",
    "received 1012",
    "service restart",
    "http 503",
    "http 502",
    "http 504",
    "temporar",
    "timeout",
    "timed out",
    "connection closed",
    "connection reset",
)

_COORDINATION_GATEWAY_TIMEOUT_S = 45.0
_COORDINATION_GATEWAY_BASE_DELAY_S = 0.5
_COORDINATION_GATEWAY_MAX_DELAY_S = 5.0
_SECURE_RANDOM = random.SystemRandom()
