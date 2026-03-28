"""Thread CRUD endpoints for channel conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import asc, col, desc, select

from app.api.deps import (
    ActorContext,
    require_org_member,
    require_user_auth,
    require_user_or_agent,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db import crud
from app.db.session import get_session
from app.models.boards import Board
from app.models.channel import Channel
from app.models.tasks import Task
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.schemas.threads import ThreadCreate, ThreadLinkTask, ThreadRead, ThreadUpdate

if TYPE_CHECKING:
    from app.schemas.auth import AuthContext

if TYPE_CHECKING:
    from app.core.auth import AuthContext
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["channels"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
USER_AUTH_DEP = Depends(require_user_auth)
ACTOR_DEP = Depends(require_user_or_agent)


def _channels_enabled_check() -> None:
    if not settings.channels_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _require_thread(session: AsyncSession, thread_id: UUID) -> Thread:
    thread = await session.get(Thread, thread_id)
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return thread


def _to_thread_read(thread: Thread, *, last_message_preview: str | None = None) -> ThreadRead:
    return ThreadRead(
        id=thread.id,
        channel_id=thread.channel_id,
        topic=thread.topic,
        task_id=thread.task_id,
        source_type=thread.source_type,
        source_ref=thread.source_ref,
        is_resolved=thread.is_resolved,
        is_pinned=thread.is_pinned,
        message_count=thread.message_count,
        last_message_at=thread.last_message_at,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        last_message_preview=last_message_preview,
    )


# ---------------------------------------------------------------------------
# Thread list & create (channel-scoped)
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}/threads", response_model=list[ThreadRead], tags=["channels"])
async def list_channel_threads(
    channel_id: UUID,
    resolved: bool = False,
    pinned_first: bool = True,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> list[ThreadRead]:
    """List threads in a channel, sorted by last activity."""
    _channels_enabled_check()
    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    stmt = (
        select(Thread)
        .where(col(Thread.channel_id) == channel_id)
        .where(col(Thread.is_resolved).is_(resolved))
    )
    if pinned_first:
        stmt = stmt.order_by(
            desc(col(Thread.is_pinned)),
            desc(col(Thread.last_message_at)),
            desc(col(Thread.created_at)),
        )
    else:
        stmt = stmt.order_by(
            desc(col(Thread.last_message_at)),
            desc(col(Thread.created_at)),
        )

    threads = (await session.exec(stmt)).all()
    return [_to_thread_read(t) for t in threads]


@router.post(
    "/channels/{channel_id}/threads",
    response_model=ThreadRead,
    status_code=status.HTTP_201_CREATED,
    tags=["channels"],
)
async def create_channel_thread(
    channel_id: UUID,
    payload: ThreadCreate,
    session: AsyncSession = SESSION_DEP,
    actor: object = ACTOR_DEP,
) -> ThreadRead:
    """Create a new thread in a channel."""
    _channels_enabled_check()
    from app.api.deps import ActorContext

    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if channel.is_archived:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Channel is archived.")
    if channel.is_readonly:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Channel is read-only."
        )

    thread = Thread(
        channel_id=channel_id,
        topic=payload.topic,
        source_type="user",
        message_count=0,
    )
    session.add(thread)
    await session.flush()

    # Identify the actor's board so we can track thread ownership for the
    # platform Support channel (cross-board thread isolation).
    actor_board_id = None
    if isinstance(actor, ActorContext) and actor.actor_type == "agent" and actor.agent:
        actor_board_id = actor.agent.board_id

    # For the platform Support channel: record which board started this thread
    # so routing can isolate replies to only the originating board lead.
    if actor_board_id is not None and channel.slug == "support":
        from app.models.boards import Board as BoardModel
        channel_board = await session.get(BoardModel, channel.board_id)
        if channel_board is not None and channel_board.is_platform:
            # Only set if this actor is from a *different* board (cross-board thread)
            if actor_board_id != channel.board_id:
                thread.owner_board_id = actor_board_id

    # Create the first message
    sender_name = "User"
    sender_id = None
    sender_type = "user"
    if isinstance(actor, ActorContext):
        if actor.actor_type == "agent" and actor.agent:
            sender_name = actor.agent.name
            sender_id = actor.agent.id
            sender_type = "agent"
        elif actor.actor_type == "user" and actor.user:
            u = actor.user
            sender_name = (
                getattr(u, "preferred_name", None)
                or getattr(u, "name", None)
                or getattr(u, "email", None)
                or "User"
            )

    msg = ThreadMessage(
        thread_id=thread.id,
        sender_type=sender_type,
        sender_id=sender_id,
        sender_name=sender_name,
        content=payload.content,
        content_type="text",
    )
    session.add(msg)
    thread.message_count = 1
    thread.last_message_at = msg.created_at

    await session.commit()
    await session.refresh(thread)

    # Dispatch first message to subscribed agents (board lead etc.)
    try:
        channel_obj = await session.get(Channel, channel_id)
        if channel_obj:
            from app.services.channel_agent_routing import dispatch_channel_message_to_agents
            await dispatch_channel_message_to_agents(session, thread, msg, channel_obj)
    except Exception:  # noqa: BLE001
        logger.exception("channel_routing.dispatch_error thread_id=%s", thread.id)

    return _to_thread_read(thread)


# ---------------------------------------------------------------------------
# Thread detail & mutation
# ---------------------------------------------------------------------------


@router.get("/threads/{thread_id}", response_model=ThreadRead, tags=["channels"])
async def get_thread(
    thread_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ThreadRead:
    """Get a thread by id."""
    _channels_enabled_check()
    thread = await _require_thread(session, thread_id)
    return _to_thread_read(thread)


@router.patch("/threads/{thread_id}", response_model=ThreadRead, tags=["channels"])
async def update_thread(
    thread_id: UUID,
    payload: ThreadUpdate,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ThreadRead:
    """Update thread (resolve, pin, rename topic)."""
    _channels_enabled_check()
    thread = await _require_thread(session, thread_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        crud.apply_updates(thread, updates)
        thread.updated_at = utcnow()
        await crud.save(session, thread)
    return _to_thread_read(thread)


@router.post("/threads/{thread_id}/link-task", response_model=ThreadRead, tags=["channels"])
async def link_thread_to_task(
    thread_id: UUID,
    payload: ThreadLinkTask,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ThreadRead:
    """Manually link a thread to an existing board task."""
    _channels_enabled_check()
    thread = await _require_thread(session, thread_id)

    # Validate task exists and is on the same board as the thread's channel
    task = await session.get(Task, payload.task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="task_id is invalid",
        )
    channel = await session.get(Channel, thread.channel_id)
    if channel is None or task.board_id != channel.board_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Task must be on the same board as the thread's channel.",
        )

    thread.task_id = task.id
    thread.updated_at = utcnow()
    # Also set the task's thread_id for bidirectional link
    task.thread_id = thread.id
    task.updated_at = utcnow()
    await session.commit()
    await session.refresh(thread)
    return _to_thread_read(thread)


@router.post("/threads/{thread_id}/unlink-task", response_model=ThreadRead, tags=["channels"])
async def unlink_thread_from_task(
    thread_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ThreadRead:
    """Remove the task link from a thread."""
    _channels_enabled_check()
    thread = await _require_thread(session, thread_id)
    if thread.task_id is not None:
        task = await session.get(Task, thread.task_id)
        if task is not None:
            task.thread_id = None
            task.updated_at = utcnow()
    thread.task_id = None
    thread.updated_at = utcnow()
    await session.commit()
    await session.refresh(thread)
    return _to_thread_read(thread)


@router.post("/threads/{thread_id}/create-task", response_model=ThreadRead, tags=["channels"])
async def create_task_from_thread(
    thread_id: UUID,
    session: AsyncSession = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> ThreadRead:
    """Create a new board task from this thread and link them bidirectionally.

    The thread topic becomes the task title. The thread is marked active (not resolved)
    and will show a LinkedTaskBadge linking to the created task.

    Accessible by both users and agents.
    """
    _channels_enabled_check()
    thread = await _require_thread(session, thread_id)

    if thread.task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Thread already has a linked task.",
        )

    channel = await session.get(Channel, thread.channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    board = await session.get(Board, channel.board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Set created_by_user_id only when a user creates the task
    created_by_user_id = None
    if actor.actor_type == "user" and actor.user is not None:
        created_by_user_id = actor.user.id

    task = Task(
        board_id=board.id,
        title=thread.topic,
        status="inbox",
        priority="medium",
        thread_id=thread.id,
        created_by_user_id=created_by_user_id,
    )
    session.add(task)
    await session.flush()  # obtain task.id

    # Link bidirectionally
    thread.task_id = task.id
    thread.is_resolved = False
    thread.updated_at = utcnow()

    # Add a system message noting the task was created
    system_msg = ThreadMessage(
        thread_id=thread.id,
        sender_type="system",
        sender_name="System",
        content=f"Task created from this conversation: #{task.id}",
        content_type="system_notification",
    )
    session.add(system_msg)
    thread.message_count = (thread.message_count or 0) + 1
    thread.last_message_at = system_msg.created_at

    await session.commit()
    await session.refresh(thread)
    return _to_thread_read(thread)
