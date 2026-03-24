"""Channel CRUD, subscription, and webhook endpoints."""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlmodel import col, select

from app.api.deps import (
    get_board_for_user_read,
    get_board_for_user_write,
    require_org_member,
    require_user_auth,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.models.user_channel_state import UserChannelState
from app.schemas.channels import (
    ChannelCreate,
    ChannelRead,
    ChannelUpdate,
    ChannelWebhookInfo,
    SubscriptionRead,
    SubscriptionUpsert,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.channel_thread_hook import handle_direct_channel_webhook

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board
    from app.schemas.auth import AuthContext

router = APIRouter(tags=["channels"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
USER_AUTH_DEP = Depends(require_user_auth)
BOARD_USER_READ_DEP = Depends(get_board_for_user_read)
BOARD_USER_WRITE_DEP = Depends(get_board_for_user_write)


def _channels_enabled_check() -> None:
    if not settings.channels_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _require_channel(session: AsyncSession, channel_id: UUID) -> Channel:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return channel


async def _require_channel_for_board(
    session: AsyncSession,
    channel_id: UUID,
    board_id: UUID,
) -> Channel:
    channel = await _require_channel(session, channel_id)
    if channel.board_id != board_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return channel


def _to_channel_read(channel: Channel, *, unread_count: int = 0, last_message_preview: str | None = None) -> ChannelRead:
    return ChannelRead(
        id=channel.id,
        board_id=channel.board_id,
        name=channel.name,
        slug=channel.slug,
        channel_type=channel.channel_type,
        description=channel.description,
        is_archived=channel.is_archived,
        is_readonly=channel.is_readonly,
        webhook_source_filter=channel.webhook_source_filter,
        position=channel.position,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
        unread_count=unread_count,
        last_message_preview=last_message_preview,
    )


def _slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "channel"


# ---------------------------------------------------------------------------
# Channel list & create (board-scoped)
# ---------------------------------------------------------------------------


@router.get("/boards/{board_id}/channels", response_model=list[ChannelRead], tags=["channels"])
async def list_board_channels(
    board: Board = BOARD_USER_READ_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[ChannelRead]:
    """List all non-archived channels for a board."""
    _channels_enabled_check()
    channels = (
        await session.exec(
            select(Channel)
            .where(col(Channel.board_id) == board.id)
            .where(col(Channel.is_archived).is_(False))
            .order_by(col(Channel.position).asc(), col(Channel.created_at).asc())
        )
    ).all()
    return [_to_channel_read(c) for c in channels]


@router.post("/boards/{board_id}/channels", response_model=ChannelRead, tags=["channels"])
async def create_board_channel(
    payload: ChannelCreate,
    board: Board = BOARD_USER_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ChannelRead:
    """Create a custom channel on a board."""
    _channels_enabled_check()
    channel = Channel(
        board_id=board.id,
        name=payload.name,
        slug=_slugify(payload.name),
        channel_type=payload.channel_type,
        description=payload.description,
        is_readonly=payload.is_readonly,
        webhook_source_filter=payload.webhook_source_filter,
        position=payload.position,
    )
    await crud.save(session, channel)
    # Auto-subscribe all existing board agents to the new channel
    try:
        from app.services.channel_lifecycle import on_channel_created as _on_channel_created
        await _on_channel_created(session, channel)
    except Exception:
        logger.exception("channel_lifecycle.channel_created_failed channel_id=%s", channel.id)
    return _to_channel_read(channel)


# ---------------------------------------------------------------------------
# Channel CRUD (channel-scoped)
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}", response_model=ChannelRead, tags=["channels"])
async def get_channel(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ChannelRead:
    """Get a channel by id."""
    _channels_enabled_check()
    channel = await _require_channel(session, channel_id)
    return _to_channel_read(channel)


@router.patch("/channels/{channel_id}", response_model=ChannelRead, tags=["channels"])
async def update_channel(
    channel_id: UUID,
    payload: ChannelUpdate,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ChannelRead:
    """Update channel properties."""
    _channels_enabled_check()
    channel = await _require_channel(session, channel_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        crud.apply_updates(channel, updates)
        channel.updated_at = utcnow()
        await crud.save(session, channel)
    return _to_channel_read(channel)


@router.delete("/channels/{channel_id}", response_model=OkResponse, tags=["channels"])
async def archive_channel(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> OkResponse:
    """Archive a channel (soft delete)."""
    _channels_enabled_check()
    channel = await _require_channel(session, channel_id)
    channel.is_archived = True
    channel.updated_at = utcnow()
    await crud.save(session, channel)
    return OkResponse()


# ---------------------------------------------------------------------------
# Channel webhook info & regeneration
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}/webhook-info", response_model=ChannelWebhookInfo, tags=["channels"])
async def get_channel_webhook_info(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ChannelWebhookInfo:
    """Get the webhook URL and secret for a channel."""
    _channels_enabled_check()
    channel = await _require_channel(session, channel_id)
    base_url = settings.base_url.rstrip("/") if settings.base_url else None
    webhook_url = f"{base_url}/api/v1/channels/{channel_id}/webhook" if base_url else None
    return ChannelWebhookInfo(
        channel_id=channel.id,
        webhook_url=webhook_url,
        webhook_secret=channel.webhook_secret,
    )


@router.post("/channels/{channel_id}/regenerate-webhook-secret", response_model=ChannelWebhookInfo, tags=["channels"])
async def regenerate_channel_webhook_secret(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> ChannelWebhookInfo:
    """Regenerate the webhook secret for a channel."""
    _channels_enabled_check()
    import secrets
    channel = await _require_channel(session, channel_id)
    channel.webhook_secret = secrets.token_hex(32)
    channel.updated_at = utcnow()
    await crud.save(session, channel)
    base_url = settings.base_url.rstrip("/") if settings.base_url else None
    webhook_url = f"{base_url}/api/v1/channels/{channel_id}/webhook" if base_url else None
    return ChannelWebhookInfo(
        channel_id=channel.id,
        webhook_url=webhook_url,
        webhook_secret=channel.webhook_secret,
    )


# ---------------------------------------------------------------------------
# Direct channel webhook endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/channels/{channel_id}/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["channels"],
)
async def ingest_channel_webhook(
    request: Request,
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
) -> dict[str, object]:
    """Direct channel webhook: creates a thread but NOT a board task."""
    _channels_enabled_check()
    channel = await _require_channel(session, channel_id)
    if channel.is_archived:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Channel is archived.")

    # Verify secret if configured
    raw_body = await request.body()
    sig_header = request.headers.get("x-webhook-secret") or request.headers.get(
        "x-hub-signature-256"
    )
    if sig_header:
        sig_value = sig_header
        if sig_value.lower().startswith("sha256="):
            sig_value = sig_value[7:]
        expected = hmac.new(
            channel.webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_value.strip().lower(), expected.strip().lower()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret.")

    try:
        import json

        payload = json.loads(raw_body) if raw_body else {}
    except Exception:
        payload = {}

    headers_dict = dict(request.headers)
    result = await handle_direct_channel_webhook(
        session=session,
        channel=channel,
        payload=payload,
        headers=headers_dict,
    )
    return {"channel_id": str(channel_id), "thread_id": str(result) if result else None}


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@router.get("/channels/{channel_id}/subscriptions", response_model=list[SubscriptionRead], tags=["channels"])
async def list_channel_subscriptions(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> list[SubscriptionRead]:
    """List agent subscriptions for a channel."""
    _channels_enabled_check()
    await _require_channel(session, channel_id)
    subs = (
        await session.exec(
            select(ChannelSubscription).where(
                col(ChannelSubscription.channel_id) == channel_id
            )
        )
    ).all()
    return [
        SubscriptionRead(
            id=s.id,
            channel_id=s.channel_id,
            agent_id=s.agent_id,
            notify_on=s.notify_on,
            created_at=s.created_at,
        )
        for s in subs
    ]


@router.put(
    "/channels/{channel_id}/subscriptions/{agent_id}",
    response_model=SubscriptionRead,
    tags=["channels"],
)
async def upsert_channel_subscription(
    channel_id: UUID,
    agent_id: UUID,
    payload: SubscriptionUpsert,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> SubscriptionRead:
    """Create or update an agent's subscription to a channel."""
    _channels_enabled_check()
    await _require_channel(session, channel_id)
    sub = (
        await session.exec(
            select(ChannelSubscription).where(
                col(ChannelSubscription.channel_id) == channel_id,
                col(ChannelSubscription.agent_id) == agent_id,
            )
        )
    ).first()
    if sub is None:
        sub = ChannelSubscription(
            channel_id=channel_id,
            agent_id=agent_id,
            notify_on=payload.notify_on,
        )
        session.add(sub)
    else:
        sub.notify_on = payload.notify_on
        sub.updated_at = utcnow()
    await session.commit()
    await session.refresh(sub)
    return SubscriptionRead(
        id=sub.id,
        channel_id=sub.channel_id,
        agent_id=sub.agent_id,
        notify_on=sub.notify_on,
        created_at=sub.created_at,
    )


@router.delete(
    "/channels/{channel_id}/subscriptions/{agent_id}",
    response_model=OkResponse,
    tags=["channels"],
)
async def delete_channel_subscription(
    channel_id: UUID,
    agent_id: UUID,
    session: AsyncSession = SESSION_DEP,
    _auth: object = ORG_MEMBER_DEP,
) -> OkResponse:
    """Remove an agent's subscription from a channel."""
    _channels_enabled_check()
    sub = (
        await session.exec(
            select(ChannelSubscription).where(
                col(ChannelSubscription.channel_id) == channel_id,
                col(ChannelSubscription.agent_id) == agent_id,
            )
        )
    ).first()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await session.delete(sub)
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Read/mute state
# ---------------------------------------------------------------------------


@router.post("/channels/{channel_id}/mark-read", response_model=OkResponse, tags=["channels"])
async def mark_channel_read(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    auth: object = USER_AUTH_DEP,
) -> OkResponse:
    """Mark all messages in a channel as read for the authenticated user."""
    _channels_enabled_check()
    from app.core.auth import AuthContext

    if not isinstance(auth, AuthContext) or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    await _require_channel(session, channel_id)

    # Find the latest message in this channel
    latest_msg = (
        await session.exec(
            select(ThreadMessage)
            .join(Thread, Thread.id == ThreadMessage.thread_id)
            .where(col(Thread.channel_id) == channel_id)
            .order_by(col(ThreadMessage.created_at).desc())
            .limit(1)
        )
    ).first()

    if latest_msg is None:
        return OkResponse()

    state = (
        await session.exec(
            select(UserChannelState).where(
                col(UserChannelState.user_id) == auth.user.id,
                col(UserChannelState.channel_id) == channel_id,
            )
        )
    ).first()

    if state is None:
        state = UserChannelState(
            user_id=auth.user.id,
            channel_id=channel_id,
            last_read_message_id=latest_msg.id,
        )
        session.add(state)
    else:
        state.last_read_message_id = latest_msg.id
        state.updated_at = utcnow()

    await session.commit()
    return OkResponse()


@router.post("/channels/{channel_id}/mute", response_model=OkResponse, tags=["channels"])
async def toggle_channel_mute(
    channel_id: UUID,
    session: AsyncSession = SESSION_DEP,
    auth: object = USER_AUTH_DEP,
) -> OkResponse:
    """Toggle mute for the authenticated user on this channel."""
    _channels_enabled_check()
    from app.core.auth import AuthContext

    if not isinstance(auth, AuthContext) or auth.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    await _require_channel(session, channel_id)

    state = (
        await session.exec(
            select(UserChannelState).where(
                col(UserChannelState.user_id) == auth.user.id,
                col(UserChannelState.channel_id) == channel_id,
            )
        )
    ).first()

    if state is None:
        state = UserChannelState(
            user_id=auth.user.id,
            channel_id=channel_id,
            is_muted=True,
        )
        session.add(state)
    else:
        state.is_muted = not state.is_muted
        state.updated_at = utcnow()

    await session.commit()
    return OkResponse()
