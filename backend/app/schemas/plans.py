"""Schemas for plan CRUD, chat, and promotion API payloads."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)

VALID_PLAN_STATUSES = frozenset({"draft", "active", "completed", "archived"})


class PlanCreate(SQLModel):
    """Payload for creating a new plan."""

    title: NonEmptyStr
    initial_prompt: str | None = None  # Optional kickoff message to the agent


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
    created_by_user_id: UUID | None
    task_id: UUID | None
    task_status: str | None  # Denormalized from linked task for display
    messages: list[dict[str, object]] | None
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
    assigned_agent_id: UUID | None = None


class PlanAgentUpdateRequest(SQLModel):
    """Payload pushed by the gateway lead agent to update a plan."""

    reply: str = ""  # Agent reply text (appended to transcript as assistant message)
    content: str | None = None  # If provided, replaces plan.content
