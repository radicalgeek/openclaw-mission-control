"""Sprint lifecycle service: state transitions and side-effects."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col, select

from app.core.logging import get_logger
from app.core.time import utcnow

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board
    from app.models.sprints import Sprint

logger = get_logger(__name__)

_SPRINT_ALLOWED_START_STATUSES = frozenset({"draft", "queued"})


def _utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_sprint_webhook_payload(
    *,
    event: str,
    sprint: Sprint,
    board: Board,
    ticket_count: int = 0,
    tickets_completed: int = 0,
    tickets_cancelled: int = 0,
) -> dict[str, object]:
    return {
        "event": event,
        "sprint": {
            "id": str(sprint.id),
            "name": sprint.name,
            "goal": sprint.goal,
            "status": sprint.status,
            "started_at": _utc_iso(sprint.started_at),
            "completed_at": _utc_iso(sprint.completed_at),
            "board_id": str(sprint.board_id),
            "ticket_count": ticket_count,
            "tickets_completed": tickets_completed,
            "tickets_cancelled": tickets_cancelled,
        },
        "board": {
            "id": str(board.id),
            "name": board.name,
            "slug": board.slug,
        },
        "timestamp": _utc_iso(utcnow()),
    }


def _sign_payload(secret: str, body_bytes: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


async def _dispatch_sprint_webhooks(
    session: AsyncSession,
    *,
    event: str,
    sprint: Sprint,
    board: Board,
    ticket_count: int = 0,
    tickets_completed: int = 0,
    tickets_cancelled: int = 0,
) -> None:
    """Fire outbound HTTP POST to all configured sprint webhooks for this event."""
    from app.models.sprint_webhooks import SprintWebhook  # noqa: PLC0415

    query = (
        select(SprintWebhook)
        .where(col(SprintWebhook.board_id) == board.id)
        .where(col(SprintWebhook.enabled).is_(True))
    )
    result = await session.exec(query)
    webhooks = result.all()

    if not webhooks:
        return

    payload_data = _build_sprint_webhook_payload(
        event=event,
        sprint=sprint,
        board=board,
        ticket_count=ticket_count,
        tickets_completed=tickets_completed,
        tickets_cancelled=tickets_cancelled,
    )
    body_bytes = json.dumps(payload_data, default=str).encode("utf-8")

    for webhook in webhooks:
        hook_events: list[str] = list(webhook.events or [])
        if hook_events and event not in hook_events:
            continue
        try:
            import httpx  # noqa: PLC0415

            signature = _sign_payload(webhook.secret, body_bytes)
            headers = {
                "Content-Type": "application/json",
                "X-Openclaw-Event": event,
                "X-Openclaw-Signature": signature,
                "X-Openclaw-Board-Id": str(board.id),
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook.url, content=body_bytes, headers=headers)
            logger.info(
                "sprint.webhook.dispatched event=%s webhook_id=%s status=%s",
                event,
                webhook.id,
                resp.status_code,
            )
        except Exception:
            logger.exception(
                "sprint.webhook.dispatch_failed event=%s webhook_id=%s url=%s",
                event,
                webhook.id,
                webhook.url,
            )


class SprintService:
    """Encapsulates sprint state transitions and side-effects."""

    @staticmethod
    async def start_sprint(
        session: AsyncSession,
        *,
        sprint: Sprint,
        board: Board,
    ) -> None:
        """Start a sprint: validate, set active, push tickets to inbox."""
        from app.models.sprints import Sprint as _Sprint, SprintTicket  # noqa: PLC0415
        from app.models.tasks import Task  # noqa: PLC0415
        from app.services.activity_log import record_activity  # noqa: PLC0415

        if sprint.status not in _SPRINT_ALLOWED_START_STATUSES:
            from fastapi import HTTPException, status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Sprint must be in draft or queued status to start (current: {sprint.status}).",
            )

        # Validate no other active sprint on this board
        existing_active = (
            await session.exec(
                select(_Sprint)
                .where(col(_Sprint.board_id) == board.id)
                .where(col(_Sprint.status) == "active")
                .where(col(_Sprint.id) != sprint.id)
            )
        ).first()
        if existing_active is not None:
            from fastapi import HTTPException, status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Another sprint is already active on this board.",
            )

        sprint.status = "active"
        sprint.started_at = utcnow()
        sprint.updated_at = utcnow()
        session.add(sprint)

        # Push sprint tickets to inbox on the board
        tickets = (
            await session.exec(
                select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id)
            )
        ).all()

        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None:
                task.is_backlog = False
                task.status = "inbox"
                task.updated_at = utcnow()
                session.add(task)

        record_activity(
            session,
            event_type="sprint_started",
            message=f"Sprint started: {sprint.name}",
            board_id=board.id,
        )
        await session.commit()
        await session.refresh(sprint)

        await _dispatch_sprint_webhooks(
            session,
            event="sprint_started",
            sprint=sprint,
            board=board,
            ticket_count=len(tickets),
        )

    @staticmethod
    async def check_sprint_completion(
        session: AsyncSession,
        *,
        board_id: UUID,
    ) -> None:
        """Check if the active sprint is complete; if so, complete it."""
        from app.models.sprints import Sprint as _Sprint, SprintTicket  # noqa: PLC0415
        from app.models.tasks import Task  # noqa: PLC0415
        from app.models.boards import Board as _Board  # noqa: PLC0415

        sprint = (
            await session.exec(
                select(_Sprint)
                .where(col(_Sprint.board_id) == board_id)
                .where(col(_Sprint.status) == "active")
            )
        ).first()

        if sprint is None:
            return

        tickets = (
            await session.exec(
                select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id)
            )
        ).all()

        if not tickets:
            return

        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is None or task.status != "done":
                return  # Still work to do

        # All tickets are done — auto-complete
        board = await session.get(_Board, board_id)
        if board is None:
            return

        await SprintService.complete_sprint(session, sprint=sprint, board=board)

    @staticmethod
    async def complete_sprint(
        session: AsyncSession,
        *,
        sprint: Sprint,
        board: Board,
    ) -> None:
        """Complete a sprint: archive done tickets, optionally auto-advance."""
        from app.models.sprints import Sprint as _Sprint, SprintTicket  # noqa: PLC0415
        from app.models.tasks import Task  # noqa: PLC0415
        from app.services.activity_log import record_activity  # noqa: PLC0415

        if sprint.status != "active":
            from fastapi import HTTPException, status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Sprint must be active to complete (current: {sprint.status}).",
            )

        sprint.status = "completed"
        sprint.completed_at = utcnow()
        sprint.updated_at = utcnow()
        session.add(sprint)

        tickets = (
            await session.exec(
                select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id)
            )
        ).all()

        tickets_done = 0
        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None and task.status == "done":
                task.is_backlog = True  # Archive off the board
                task.updated_at = utcnow()
                session.add(task)
                tickets_done += 1

        record_activity(
            session,
            event_type="sprint_completed",
            message=f"Sprint completed: {sprint.name}",
            board_id=board.id,
        )
        await session.commit()
        await session.refresh(sprint)

        await _dispatch_sprint_webhooks(
            session,
            event="sprint_completed",
            sprint=sprint,
            board=board,
            ticket_count=len(tickets),
            tickets_completed=tickets_done,
        )

        # Auto-advance to next queued sprint if flow mode enabled
        if board.auto_advance_sprint:
            next_sprint = (
                await session.exec(
                    select(_Sprint)
                    .where(col(_Sprint.board_id) == board.id)
                    .where(col(_Sprint.status) == "queued")
                    .order_by(col(_Sprint.position).asc())
                )
            ).first()
            if next_sprint is not None:
                try:
                    await SprintService.start_sprint(session, sprint=next_sprint, board=board)
                except Exception:
                    logger.exception(
                        "sprint.auto_advance_failed board_id=%s next_sprint_id=%s",
                        board.id,
                        next_sprint.id,
                    )

    @staticmethod
    async def cancel_sprint(
        session: AsyncSession,
        *,
        sprint: Sprint,
        board: Board,
    ) -> None:
        """Cancel a sprint: return unfinished tickets to backlog."""
        from app.models.sprints import SprintTicket  # noqa: PLC0415
        from app.models.tasks import Task  # noqa: PLC0415
        from app.services.activity_log import record_activity  # noqa: PLC0415

        allowed_statuses = frozenset({"draft", "queued", "active"})
        if sprint.status not in allowed_statuses:
            from fastapi import HTTPException, status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a sprint with status '{sprint.status}'.",
            )

        sprint.status = "cancelled"
        sprint.updated_at = utcnow()
        session.add(sprint)

        tickets = (
            await session.exec(
                select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id)
            )
        ).all()

        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None:
                if task.status != "done":
                    task.is_backlog = True
                    task.status = "inbox"
                else:
                    task.is_backlog = True  # Archive completed work
                task.updated_at = utcnow()
                session.add(task)

        record_activity(
            session,
            event_type="sprint_cancelled",
            message=f"Sprint cancelled: {sprint.name}",
            board_id=board.id,
        )
        await session.commit()
        await session.refresh(sprint)

        await _dispatch_sprint_webhooks(
            session,
            event="sprint_cancelled",
            sprint=sprint,
            board=board,
            ticket_count=len(tickets),
        )
