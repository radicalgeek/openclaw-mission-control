"""Sprint webhook CRUD endpoints."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import col, select

from app.api.deps import get_board_for_user_read, get_board_for_user_write, require_user_auth
from app.core.time import utcnow
from app.db.session import get_session
from app.models.sprint_webhooks import SprintWebhook
from app.schemas.common import OkResponse
from app.schemas.sprints import SprintWebhookCreate, SprintWebhookRead, SprintWebhookUpdate

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext
    from app.models.boards import Board

router = APIRouter(prefix="/boards/{board_id}/sprint-webhooks", tags=["sprint-webhooks"])
SESSION_DEP = Depends(get_session)
BOARD_READ_DEP = Depends(get_board_for_user_read)
BOARD_WRITE_DEP = Depends(get_board_for_user_write)
USER_AUTH_DEP = Depends(require_user_auth)


def _to_read(webhook: SprintWebhook) -> SprintWebhookRead:
    return SprintWebhookRead(
        id=webhook.id,
        board_id=webhook.board_id,
        url=webhook.url,
        events=list(webhook.events or []),
        enabled=webhook.enabled,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
    )


async def _require_sprint_webhook(
    session: "AsyncSession",
    webhook_id: UUID,
    board: "Board",
) -> SprintWebhook:
    webhook = (
        await session.exec(
            select(SprintWebhook)
            .where(col(SprintWebhook.id) == webhook_id)
            .where(col(SprintWebhook.board_id) == board.id)
        )
    ).first()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return webhook


@router.get("", response_model=list[SprintWebhookRead])
async def list_sprint_webhooks(
    board: "Board" = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> list[SprintWebhookRead]:
    """List all sprint webhooks for a board."""
    webhooks = (
        await session.exec(
            select(SprintWebhook)
            .where(col(SprintWebhook.board_id) == board.id)
            .order_by(col(SprintWebhook.created_at).asc())
        )
    ).all()
    return [_to_read(w) for w in webhooks]


@router.post("", response_model=SprintWebhookRead, status_code=status.HTTP_201_CREATED)
async def create_sprint_webhook(
    payload: SprintWebhookCreate,
    board: "Board" = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintWebhookRead:
    """Create a sprint webhook with auto-generated signing secret."""
    secret = secrets.token_hex(32)
    webhook = SprintWebhook(
        organization_id=board.organization_id,
        board_id=board.id,
        url=str(payload.url),
        secret=secret,
        events=list(payload.events),
        enabled=payload.enabled,
    )
    session.add(webhook)
    await session.commit()
    await session.refresh(webhook)
    return _to_read(webhook)


@router.patch("/{webhook_id}", response_model=SprintWebhookRead)
async def update_sprint_webhook(
    webhook_id: UUID,
    payload: SprintWebhookUpdate,
    board: "Board" = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintWebhookRead:
    """Update sprint webhook URL, events list, or enabled state."""
    webhook = await _require_sprint_webhook(session, webhook_id, board)
    if payload.url is not None:
        webhook.url = str(payload.url)
    if payload.events is not None:
        webhook.events = list(payload.events)
    if payload.enabled is not None:
        webhook.enabled = payload.enabled
    webhook.updated_at = utcnow()
    session.add(webhook)
    await session.commit()
    await session.refresh(webhook)
    return _to_read(webhook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint_webhook(
    webhook_id: UUID,
    board: "Board" = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> None:
    """Delete a sprint webhook."""
    webhook = await _require_sprint_webhook(session, webhook_id, board)
    await session.delete(webhook)
    await session.commit()
