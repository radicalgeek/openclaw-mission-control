"""Pydantic/SQLModel schemas for agent API payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlmodel import SQLModel
from sqlmodel._compat import SQLModelConfig

from app.models.agents import (
    AGENT_TYPE_BOARD_LEAD,
    AGENT_TYPE_BOARD_WORKER,
    AGENT_TYPE_GATEWAY_MAIN,
    AGENT_TYPE_STANDALONE,
)
from app.schemas.common import NonEmptyStr

VALID_AGENT_TYPES = frozenset(
    {AGENT_TYPE_BOARD_WORKER, AGENT_TYPE_BOARD_LEAD, AGENT_TYPE_GATEWAY_MAIN, AGENT_TYPE_STANDALONE}
)

VALID_ROLE_TEMPLATES = frozenset(
    {
        # Delivery specialists (board_worker or standalone)
        "triager",
        "planner",
        "estimator",
        "priority",
        # Board specialists (board_worker only, Kanban task execution)
        "test_agent",
        "merger",
        "ui_test",
        "visual_regression",
        # Cross-board reviewers (standalone only, webhook-driven)
        "quality_reviewer",
        "security_reviewer",
        "architecture_reviewer",
    }
)

# Templates that may only be assigned to standalone agents.
STANDALONE_ONLY_ROLE_TEMPLATES = frozenset(
    {
        "quality_reviewer",
        "security_reviewer",
        "architecture_reviewer",
    }
)

# Templates that may only be assigned to board_worker agents.
BOARD_WORKER_ONLY_ROLE_TEMPLATES = frozenset(
    {
        "test_agent",
        "merger",
        "ui_test",
        "visual_regression",
    }
)

# Delivery-tier templates valid for BOTH standalone and board_worker.
ORG_STANDALONE_ROLE_TEMPLATES = frozenset(
    {
        "triager",
        "planner",
        "estimator",
        "priority",
    }
)

# All templates valid for standalone agents (used by reconciler).
STANDALONE_ROLE_TEMPLATES = STANDALONE_ONLY_ROLE_TEMPLATES | ORG_STANDALONE_ROLE_TEMPLATES

# All templates valid for board_worker agents.
BOARD_WORKER_ROLE_TEMPLATES = BOARD_WORKER_ONLY_ROLE_TEMPLATES | ORG_STANDALONE_ROLE_TEMPLATES

_RUNTIME_TYPE_REFERENCES = (datetime, UUID, NonEmptyStr)


def _normalize_identity_profile(
    profile: object,
) -> dict[str, str] | None:
    if not isinstance(profile, Mapping):
        return None
    normalized: dict[str, str] = {}
    for raw_key, raw in profile.items():
        if raw is None:
            continue
        key = str(raw_key).strip()
        if not key:
            continue
        if isinstance(raw, list):
            parts = [str(item).strip() for item in raw if str(item).strip()]
            if not parts:
                continue
            normalized[key] = ", ".join(parts)
            continue
        value = str(raw).strip()
        if value:
            normalized[key] = value
    return normalized or None


class AgentBase(SQLModel):
    """Common fields shared by agent create/read/update payloads."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_profile",
            "x-when-to-use": [
                "Create or update canonical agent metadata",
                "Inspect agent attributes for governance or delegation",
            ],
            "x-when-not-to-use": [
                "Task lifecycle operations (use task endpoints)",
                "User-facing conversation content (not modeled here)",
            ],
            "x-required-actor": "lead_or_worker_agent",
            "x-prerequisites": [
                "board_id if required by your board policy",
                "identity templates should be valid JSON or text with expected markers",
            ],
            "x-response-shape": "AgentRead",
            "x-side-effects": [
                "Reads or writes core agent profile fields",
                "May impact routing or assignment decisions when persisted",
            ],
        },
    )

    board_id: UUID | None = Field(
        default=None,
        description="Board id that scopes this agent. Omit only when policy allows global agents.",
        examples=["11111111-1111-1111-1111-111111111111"],
    )
    agent_type: str = Field(
        default=AGENT_TYPE_BOARD_WORKER,
        description="Agent type: board_worker, board_lead, gateway_main, or standalone.",
        examples=[AGENT_TYPE_BOARD_WORKER, AGENT_TYPE_STANDALONE],
    )
    name: NonEmptyStr = Field(
        description="Human-readable agent display name.",
        examples=["Ops triage lead"],
    )
    status: str = Field(
        default="provisioning",
        description="Current lifecycle state used by coordinator logic.",
        examples=["provisioning", "active", "paused", "retired"],
    )
    heartbeat_config: dict[str, Any] | None = Field(
        default=None,
        description="Runtime heartbeat behavior overrides for this agent.",
        examples=[{"interval_seconds": 30, "missing_tolerance": 120}],
    )
    identity_profile: dict[str, Any] | None = Field(
        default=None,
        description="Optional profile hints used by routing and policy checks.",
        examples=[{"role": "incident_lead", "skill": "triage"}],
    )
    identity_template: str | None = Field(
        default=None,
        description="Template that helps define initial intent and behavior.",
        examples=["You are a senior incident response lead."],
    )
    soul_template: str | None = Field(
        default=None,
        description="Template representing deeper agent instructions.",
        examples=["When critical blockers appear, escalate in plain language."],
    )

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, value: str) -> str:
        """Reject unknown agent_type values."""
        if value not in VALID_AGENT_TYPES:
            raise ValueError(
                f"Invalid agent_type '{value}'. Must be one of: {sorted(VALID_AGENT_TYPES)}"
            )
        return value

    @field_validator("identity_template", "soul_template", mode="before")
    @classmethod
    def normalize_templates(cls, value: object) -> object | None:
        """Normalize blank template text to null."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("identity_profile", mode="before")
    @classmethod
    def normalize_identity_profile(
        cls,
        value: object,
    ) -> dict[str, str] | None:
        """Normalize identity-profile values into trimmed string mappings."""
        return _normalize_identity_profile(value)


class AgentCreate(AgentBase):
    """Payload for creating a new agent."""

    @model_validator(mode="after")
    def sync_is_board_lead_from_agent_type(self) -> "AgentCreate":
        """Ensure is_board_lead=True whenever agent_type is 'board_lead'.

        Clients may set either field; this validator enforces consistency so
        provisioning always has a coherent state for session-key/template resolution.
        """
        if self.agent_type == AGENT_TYPE_BOARD_LEAD:
            self.is_board_lead = True
        return self

    @model_validator(mode="after")
    def validate_standalone_board_id(self) -> "AgentCreate":
        """Enforce board_id presence/absence based on agent_type."""
        boardless_types = {AGENT_TYPE_STANDALONE, AGENT_TYPE_GATEWAY_MAIN}
        if self.agent_type in boardless_types and self.board_id is not None:
            raise ValueError(f"{self.agent_type} agents must not have a board_id")
        if self.agent_type not in boardless_types and self.board_id is None:
            raise ValueError(f"{self.agent_type} agents must have a board_id")
        return self

    @model_validator(mode="after")
    def validate_role_template(self) -> "AgentCreate":
        """Validate role_template in identity_profile against the closed allowed set."""
        profile = self.identity_profile or {}
        role_template = profile.get("role_template")
        if role_template is None:
            return self
        if role_template not in VALID_ROLE_TEMPLATES:
            raise ValueError(
                f"Invalid role_template '{role_template}'. "
                f"Must be one of: {sorted(VALID_ROLE_TEMPLATES)}"
            )
        if (
            role_template in STANDALONE_ONLY_ROLE_TEMPLATES
            and self.agent_type != AGENT_TYPE_STANDALONE
        ):
            raise ValueError(f"role_template '{role_template}' requires agent_type 'standalone'")
        if (
            role_template in BOARD_WORKER_ONLY_ROLE_TEMPLATES
            and self.agent_type != AGENT_TYPE_BOARD_WORKER
        ):
            raise ValueError(f"role_template '{role_template}' requires agent_type 'board_worker'")
        return self

    gateway_id: UUID | None = Field(
        default=None,
        description=(
            "Gateway UUID for standalone agents. Required when agent_type is 'standalone'. "
            "Ignored for board-scoped agents (gateway is derived from the board)."
        ),
        examples=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
    )
    auth_profile: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Full auth-profiles.json content written to the agent workspace at provision time. "
            "Supports multiple providers (Anthropic, GitHub Copilot, etc.). "
            "Written as auth-profiles.json — not stored on the agent record. "
            'Example: {"version": 1, "profiles": {"anthropic:main": {"type": "token", '
            '"provider": "anthropic", "token": "sk-ant-..."}}, '
            '"order": {"anthropic": ["anthropic:main"]}, "lastGood": {}, "usageStats": {}}.'
        ),
        examples=[
            {
                "version": 1,
                "profiles": {
                    "anthropic:main": {
                        "type": "token",
                        "provider": "anthropic",
                        "token": "sk-ant-oat01-...",
                        "expires": 1803423216508,
                    },
                    "github-copilot:github": {
                        "type": "token",
                        "provider": "github-copilot",
                        "token": "ghu_...",
                    },
                },
                "order": {
                    "anthropic": ["anthropic:main"],
                    "github-copilot": ["github-copilot:github"],
                },
                "lastGood": {},
                "usageStats": {},
            }
        ],
    )
    skill_env: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Per-skill credential overrides written to skills/<slug>/config.env at provision time. "
            'Example: {"plane-workflow": {"PLANE_API_KEY": "plane_api_xxx"}}. '
            "Values are write-only and not stored on the agent record."
        ),
        examples=[{"hoofer-k8s": {"GITLAB_TOKEN": "glpat-xxx"}}],
    )
    tool_instructions: str | None = Field(
        default=None,
        description=(
            "Optional additional tool documentation appended to TOOLS.md at provision time. "
            "Use for custom API instructions, endpoints, or usage notes specific to this agent. "
            "Write-only — not stored on the agent record."
        ),
        examples=[
            "## Plane\nPLANE_API_URL=https://plane.example.com\nUse the plane-workflow skill for ticket management."
        ],
    )
    is_board_lead: bool = Field(
        default=False,
        description=(
            "Whether this agent should be created as the board lead. "
            "When true, the agent will be assigned the board lead session key and role. "
            "Only one board lead is allowed per board."
        ),
    )
    installed_skills: list[str] | None = Field(
        default=None,
        description=(
            "Per-agent skill allowlist pushed to gateway agents.list[].skills. "
            'None = inherit gateway defaults. [] = no skills. ["a","b"] = explicit list.'
        ),
        examples=[["github", "weather"]],
    )


class AgentUpdate(SQLModel):
    """Payload for patching an existing agent."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_profile_update",
            "x-when-to-use": [
                "Patch mutable agent metadata without replacing the full payload",
                "Update status, templates, or heartbeat policy",
            ],
            "x-when-not-to-use": [
                "Creating an agent (use AgentCreate)",
                "Hard deletes or archive actions (use lifecycle endpoints)",
            ],
            "x-required-actor": "board_lead",
            "x-prerequisites": [
                "Target agent id must exist and be visible to actor context",
            ],
            "x-side-effects": [
                "Mutates agent profile state",
            ],
        },
    )

    board_id: UUID | None = Field(
        default=None,
        description="Optional new board assignment.",
        examples=["22222222-2222-2222-2222-222222222222"],
    )
    is_gateway_main: bool | None = Field(
        default=None,
        description="Whether this agent is treated as the board gateway main.",
    )
    name: NonEmptyStr | None = Field(
        default=None,
        description="Optional replacement display name.",
        examples=["Ops triage lead"],
    )
    status: str | None = Field(
        default=None,
        description="Optional replacement lifecycle status.",
        examples=["active", "paused"],
    )
    heartbeat_config: dict[str, Any] | None = Field(
        default=None,
        description="Optional heartbeat policy override.",
        examples=[{"interval_seconds": 45}],
    )
    identity_profile: dict[str, Any] | None = Field(
        default=None,
        description="Optional identity profile update values.",
        examples=[{"role": "coordinator"}],
    )
    identity_template: str | None = Field(
        default=None,
        description="Optional replacement identity template.",
        examples=["Focus on root cause analysis first."],
    )
    soul_template: str | None = Field(
        default=None,
        description="Optional replacement soul template.",
        examples=["Escalate only after checking all known mitigations."],
    )
    installed_skills: list[str] | None = Field(
        default=None,
        description="Optional replacement for agent skill allowlist.",
        examples=[["github", "weather"]],
    )

    @field_validator("identity_template", "soul_template", mode="before")
    @classmethod
    def normalize_templates(cls, value: object) -> object | None:
        """Normalize blank template text to null."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("identity_profile", mode="before")
    @classmethod
    def normalize_identity_profile(
        cls,
        value: object,
    ) -> dict[str, str] | None:
        """Normalize identity-profile values into trimmed string mappings."""
        return _normalize_identity_profile(value)

    @model_validator(mode="after")
    def validate_role_template(self) -> "AgentUpdate":
        """Reject unknown role_template values at update time.

        Cross-type validation (e.g. reviewer on board_worker) requires the
        persisted agent_type and is enforced in the service layer.
        """
        profile = self.identity_profile
        if profile is None:
            return self
        role_template = profile.get("role_template")
        if role_template is None:
            return self
        if role_template not in VALID_ROLE_TEMPLATES:
            raise ValueError(
                f"Invalid role_template '{role_template}'. "
                f"Must be one of: {sorted(VALID_ROLE_TEMPLATES)}"
            )
        return self


class AgentRead(AgentBase):
    """Public agent representation returned by the API."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_profile_lookup",
            "x-when-to-use": [
                "Inspect live agent state for routing and ownership decisions",
            ],
            "x-required-actor": "board_lead_or_worker",
            "x-interpretation": "This is a read model; changes here should use update/lifecycle endpoints.",
        },
    )

    id: UUID = Field(description="Agent UUID.")
    gateway_id: UUID = Field(description="Gateway UUID that manages this agent.")
    is_board_lead: bool = Field(
        default=False,
        description="Whether this agent is the board lead.",
    )
    is_gateway_main: bool = Field(
        default=False,
        description="Whether this agent is the primary gateway agent.",
    )
    installed_skills: list[str] | None = Field(
        default=None,
        description="Per-agent skill allowlist (gateway agents.list[].skills). None = gateway defaults.",
    )
    openclaw_session_id: str | None = Field(
        default=None,
        description="Optional openclaw session token.",
        examples=["sess_01J..."],
    )
    last_seen_at: datetime | None = Field(
        default=None,
        description="Last heartbeat timestamp.",
    )
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class AgentHeartbeat(SQLModel):
    """Heartbeat status payload sent by agents."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_health_signal",
            "x-when-to-use": [
                "Send periodic heartbeat to indicate liveness",
            ],
            "x-required-actor": "any_agent",
            "x-response-shape": "AgentRead",
        },
    )

    status: str | None = Field(
        default=None,
        description="Agent health status string.",
        examples=["healthy", "offline", "degraded"],
    )


class AgentHeartbeatCreate(AgentHeartbeat):
    """Heartbeat payload used to create an agent lazily."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_bootstrap",
            "x-when-to-use": [
                "First heartbeat from a non-provisioned worker should bootstrap identity.",
            ],
            "x-required-actor": "agent",
            "x-prerequisites": ["Agent auth token already validated"],
            "x-response-shape": "AgentRead",
        },
    )

    name: NonEmptyStr = Field(
        description="Display name assigned during first heartbeat bootstrap.",
        examples=["Ops triage lead"],
    )
    board_id: UUID | None = Field(
        default=None,
        description="Optional board context for bootstrap.",
        examples=["33333333-3333-3333-3333-333333333333"],
    )


class AgentNudge(SQLModel):
    """Nudge message payload for pinging an agent."""

    model_config = SQLModelConfig(
        json_schema_extra={
            "x-llm-intent": "agent_nudge",
            "x-when-to-use": [
                "Prompt a specific agent to revisit or reprioritize work.",
            ],
            "x-required-actor": "board_lead",
            "x-response-shape": "AgentRead",
        },
    )

    message: NonEmptyStr = Field(
        description="Short message to direct an agent toward immediate attention.",
        examples=["Please update the incident triage status for task T-001."],
    )
