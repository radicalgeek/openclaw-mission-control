"""Schemas for plan CRUD, chat, and promotion API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)


class DecomposedTicket(SQLModel):
    """A single ticket produced by plan decomposition."""

    title: str
    description: str = ""
    priority: str = "medium"  # low | medium | high | critical (display label)
    priority_score: int = 35  # 1–100 numeric score (auto-set from priority)
    estimate_minutes: int | None = None  # Agent-suggested time estimate


VALID_PLAN_STATUSES = frozenset({"draft", "active", "completed", "archived"})
VALID_DECOMPOSITION_TARGETS = frozenset({"board_lead", "org_planner", "org_triager"})


class PlanCreate(SQLModel):
    """Payload for creating a new plan."""

    title: NonEmptyStr
    initial_prompt: str | None = None  # Optional kickoff message to the agent
    # Plan authoring is handled by the planner; task generation defaults to the triager.
    decomposition_target: str = "org_triager"


class PlanUpdate(SQLModel):
    """Payload for partial plan updates (title, content, or status)."""

    title: str | None = None
    content: str | None = None  # Direct manual content edits from the editor
    status: str | None = None  # "draft" | "active" | "archived"


class PlanRead(SQLModel):
    """Plan payload returned from read endpoints."""

    id: UUID
    board_id: UUID
    title: str
    slug: str
    content: str
    status: str
    decomposition_target: str = "org_triager"
    created_by_user_id: UUID | None
    task_id: UUID | None
    task_status: str | None  # Denormalized from linked task for display
    messages: list[dict[str, object]] | None
    decomposed_tickets: list[DecomposedTicket] | None = None
    created_at: datetime
    updated_at: datetime


class PlanChatRequest(SQLModel):
    """User message sent to the lead agent during a planning session."""

    message: NonEmptyStr


class PlanChatResponse(SQLModel):
    """Response from the agent after processing a planning chat message."""

    messages: list[dict[str, object]]  # Updated full transcript
    content: str  # Updated plan markdown (may be unchanged if agent only asked a question)
    agent_reply: str  # The agent's latest reply text


class PlanPromoteRequest(SQLModel):
    """Payload for promoting a plan to a board task."""

    task_title: str | None = None  # Defaults to plan title if not provided
    task_priority: str = Field(default="medium")
    task_priority_score: int = Field(default=50)  # 1–100 numeric score
    estimate_minutes: int | None = None  # Optional time estimate for the promoted task
    target_status: str = Field(default="inbox")  # "inbox" (on-board) or "backlog" (off-board)
    assigned_agent_id: UUID | None = None


class PlanAgentUpdateRequest(SQLModel):
    """Payload pushed by the gateway lead agent to update a plan."""

    reply: str = ""  # Agent reply text (appended to transcript as assistant message)
    content: str | None = None  # If provided, replaces plan.content
    tickets: list[DecomposedTicket] | None = None  # If provided, stores decomposed tickets
    content_type: str = "text"  # "text" | "mcp_app_result"
    app_metadata: dict[str, object] | None = None  # Required when content_type == "mcp_app_result"


class PlanCommitTicketsResponse(SQLModel):
    """Response from the bulk-commit endpoint listing the created backlog tasks."""

    plan_id: UUID
    task_ids: list[UUID]
    count: int
