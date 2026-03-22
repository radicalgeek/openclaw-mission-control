"""Thread message endpoints — single source of truth for thread conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import asc, col, select

from app.api.deps import require_org_member, require_user_or_agent
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db import crud
from app.db.session import get_session
from app.models.channel import Channel
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.schemas.thread_messages import (
    ThreadMessageCreate,
    ThreadMessageRead,
    ThreadMessageUpdate,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["channels"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
ACTOR_DEP = Depends(require_user_or_agent)
BEFORE_QUERY = Query(default=None)
LIMIT_QUERY = Query(default=50, ge=1, le=200)


def _channels_enabled_check() -> None:
    if not settings.channels_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _to_message_read(msg: ThreadMessage) -> ThreadMessageRead:
    return ThreadMessageRead(
        id=msg.id,
        thread_id=msg.thread_id,
        sender_type=msg.sender_type,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        content=msg.content,
        content_type=msg.content_type,
        event_metadata=msg.event_metadata,
        is_edited=msg.is_edited,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
    )


# ---------------------------------------------------------------------------
# Message list & create (thread-scoped)
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}/messages", response_model=list[ThreadMessageRead], tags=["channels"])
async def list_thread_messages(
    thread_id: UUID,
    before: UUID | None = BEFORE_QUERY,
    limit: int = LIMIT_QUERY,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> list[ThreadMessageRead]:
    """List messages in a thread in chronological order."""
    _channels_enabled_check()
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    stmt = select(ThreadMessage).where(col(ThreadMessage.thread_id) == thread_id)

    if before is not None:
        cursor_msg = await session.get(ThreadMessage, before)
        if cursor_msg is not None:
            stmt = stmt.where(col(ThreadMessage.created_at) < cursor_msg.created_at)

    stmt = stmt.order_by(asc(col(ThreadMessage.created_at))).limit(limit)
    messages = (await session.exec(stmt)).all()
    return [_to_message_read(m) for m in messages]


@router.post(
    "/threads/{thread_id}/messages",
    response_model=ThreadMessageRead,
    status_code=status.HTTP_201_CREATED,
    tags=["channels"],
)
async def create_thread_message(
    thread_id: UUID,
    payload: ThreadMessageCreate,
    session: AsyncSession = SESSION_DEP,
    actor: object = ACTOR_DEP,
) -> ThreadMessageRead:
    """Send a message to a thread."""
    _channels_enabled_check()
    from app.api.deps import ActorContext

    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    channel = await session.get(Channel, thread.channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if channel.is_archived:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Channel is archived.")

    sender_name = "User"
    sender_id = None
    sender_type = "user"
    if isinstance(actor, ActorContext):
        if actor.actor_type == "agent" and actor.agent:
            sender_name = actor.agent.name
            sender_id = actor.agent.id
            sender_type = "agent"
        elif actor.actor_type == "user" and actor.user:
            sender_id = actor.user.id
            u = actor.user
            sender_name = (
                getattr(u, "preferred_name", None)
                or getattr(u, "name", None)
                or getattr(u, "email", None)
                or "User"
            )

    msg = ThreadMessage(
        thread_id=thread_id,
        sender_type=sender_type,
        sender_id=sender_id,
        sender_name=sender_name,
        content=payload.content,
        content_type=payload.content_type,
    )
    session.add(msg)

    # Update thread denormalized counters
    thread.message_count = (thread.message_count or 0) + 1
    thread.last_message_at = msg.created_at
    thread.updated_at = utcnow()

    await session.commit()
    await session.refresh(msg)

    # Dispatch to agents (non-blocking, fail-safe)
    try:
        if settings.channels_enabled:
            from app.services.channel_agent_routing import dispatch_channel_message_to_agents
            await dispatch_channel_message_to_agents(
                session=session,
                thread=thread,
                message=msg,
                channel=channel,
            )
    except Exception:
        logger.exception(
            "channel_messages.agent_dispatch_failed thread_id=%s msg_id=%s",
            thread_id,
            msg.id,
        )

    return _to_message_read(msg)


# ---------------------------------------------------------------------------
# Message edit and delete
# ---------------------------------------------------------------------------


@router.patch("/messages/{message_id}", response_model=ThreadMessageRead, tags=["channels"])
async def edit_message(
    message_id: UUID,
    payload: ThreadMessageUpdate,
    session: AsyncSession = SESSION_DEP,
    actor: object = ACTOR_DEP,
) -> ThreadMessageRead:
    """Edit a message (own messages only)."""
    _channels_enabled_check()
    from app.api.deps import ActorContext

    msg = await session.get(ThreadMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Check ownership
    if isinstance(actor, ActorContext):
        if actor.actor_type == "agent" and actor.agent:
            if msg.sender_id != actor.agent.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        elif actor.actor_type == "user" and actor.user:
            if msg.sender_id != actor.user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    msg.content = payload.content
    msg.is_edited = True
    msg.updated_at = utcnow()
    await crud.save(session, msg)
    return _to_message_read(msg)


@router.delete("/messages/{message_id}", response_model=dict, tags=["channels"])
async def delete_message(
    message_id: UUID,
    session: AsyncSession = SESSION_DEP,
    actor: object = ACTOR_DEP,
) -> dict:
    """Delete a message (own messages only)."""
    _channels_enabled_check()
    from app.api.deps import ActorContext

    msg = await session.get(ThreadMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Check ownership
    if isinstance(actor, ActorContext):
        if actor.actor_type == "agent" and actor.agent:
            if msg.sender_id != actor.agent.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        elif actor.actor_type == "user" and actor.user:
            if msg.sender_id != actor.user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    # Update thread counter
    thread = await session.get(Thread, msg.thread_id)
    if thread is not None and thread.message_count > 0:
        thread.message_count -= 1
        thread.updated_at = utcnow()

    await session.delete(msg)
    await session.commit()
    return {"ok": True}
