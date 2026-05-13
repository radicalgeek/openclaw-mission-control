"""Sprint lifecycle service: state transitions and side-effects."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from sqlmodel import col, select

from app.core.logging import get_logger
from app.core.time import utcnow

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board
    from app.models.sprints import Sprint

logger = get_logger(__name__)

_SPRINT_ALLOWED_START_STATUSES = frozenset({"draft", "queued"})
_AGENT_MISSING_HINT = "no longer exists in configuration"
_SPRINT_WAKE_IDEMPOTENCY_NAMESPACE = UUID("a3bca6bd-4d2c-4da2-881a-8717d8313466")


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


def _build_sprint_started_lead_message(
    *,
    sprint: Sprint,
    board: Board,
    ticket_count: int,
) -> str:
    task_list_path = f"/api/v1/agent/boards/{board.id}/tasks?status=inbox&is_backlog=false"
    roster_path = f"/api/v1/agent/agents?board_id={board.id}"
    task_update_path = f"/api/v1/agent/boards/{board.id}/tasks/<task_id>"
    return (
        f"Sprint started on board {board.name}: {sprint.name}.\n\n"
        f"There are {ticket_count} committed sprint tickets now in inbox.\n\n"
        f"Board ID: {board.id}\n"
        f"Sprint ID: {sprint.id}\n\n"
        "Execute this assignment cycle now. Do not reply with a plan, recap, or "
        "standby message. Use your AxiaCraft API tools from TOOLS.md/OpenAPI in "
        "this turn to:\n"
        "1. Read HEARTBEAT.md and refresh the lead operation list if needed.\n"
        f"2. Inspect the active sprint tickets with GET {task_list_path}.\n"
        f"3. Discover assignable board agents with GET {roster_path}; do not use "
        "/api/v1/agent/boards/<board_id>/agents because that route does not exist.\n"
        "4. Assign all unassigned sprint inbox tickets to the available "
        f"non-lead developer agents with PATCH {task_update_path} using "
        '{"assigned_agent_id":"<developer_agent_id>"}.\n'
        f"5. Verify assignment by re-reading GET {task_list_path}.\n\n"
        "Use the Board ID and Sprint ID exactly as written above. Do not rewrite, "
        "shorten, or substitute any UUID.\n\n"
        "Do not create new tickets for this sprint-start event. Wake developers "
        "only when they have assigned work. Only finish with HEARTBEAT_OK after "
        "the assignments are visible in AxiaCraft. If you cannot make tool/API "
        "calls, reply exactly: BLOCKED: no tool access."
    )


async def _wake_board_lead_for_started_sprint(
    session: AsyncSession,
    *,
    sprint: Sprint,
    board: Board,
    ticket_count: int,
) -> None:
    """Ensure board agents are in the runtime config, then wake the lead.

    This is intentionally lighter than lifecycle/provisioning. Sprint start only
    needs the already-provisioned agents to be visible to OpenClaw after a worker
    restart; it should not rewrite templates, rotate tokens, reset sessions, or
    mark agents as updating.
    """
    if board.gateway_id is None:
        return

    from app.models.agents import Agent  # noqa: PLC0415
    from app.models.gateways import Gateway  # noqa: PLC0415
    from app.services.openclaw.gateway_resolver import gateway_client_config  # noqa: PLC0415
    from app.services.openclaw.gateway_rpc import OpenClawGatewayError  # noqa: PLC0415
    from app.services.openclaw.gateway_rpc import ensure_session  # noqa: PLC0415
    from app.services.openclaw.gateway_rpc import openclaw_call  # noqa: PLC0415
    from app.services.openclaw.gateway_rpc import send_session_message_nonblocking  # noqa: PLC0415
    from app.services.openclaw.provisioning import OpenClawGatewayProvisioner  # noqa: PLC0415
    from app.services.openclaw.provisioning import _agent_session_model  # noqa: PLC0415
    from app.services.openclaw.provisioning import (  # noqa: PLC0415
        _agent_session_should_clear_model,
    )

    gateway = await session.get(Gateway, board.gateway_id)
    if gateway is None or gateway.organization_id != board.organization_id:
        logger.warning(
            "sprint.start.lead_wake.skipped_invalid_gateway board_id=%s gateway_id=%s",
            board.id,
            board.gateway_id,
        )
        return
    if not (gateway.url or "").strip() or not (gateway.workspace_root or "").strip():
        logger.warning(
            "sprint.start.lead_wake.skipped_incomplete_gateway board_id=%s gateway_id=%s",
            board.id,
            gateway.id,
        )
        return

    agents = (
        await session.exec(
            select(Agent)
            .where(col(Agent.board_id) == board.id)
            .where(col(Agent.gateway_id) == gateway.id)
            .order_by(col(Agent.created_at).asc())
        )
    ).all()
    if not agents:
        logger.warning("sprint.start.lead_wake.skipped_no_agents board_id=%s", board.id)
        return

    lead = next((agent for agent in agents if agent.is_board_lead), None)
    if lead is None or not lead.openclaw_session_id:
        logger.warning("sprint.start.lead_wake.skipped_no_lead board_id=%s", board.id)
        return
    lead_session_key = lead.openclaw_session_id

    try:
        await OpenClawGatewayProvisioner().sync_gateway_agent_heartbeats(gateway, list(agents))
    except Exception:
        logger.exception(
            "sprint.start.lead_wake.runtime_register_failed board_id=%s gateway_id=%s",
            board.id,
            gateway.id,
        )
        return

    config = gateway_client_config(gateway)
    message = _build_sprint_started_lead_message(
        sprint=sprint,
        board=board,
        ticket_count=ticket_count,
    )

    async def _send_lead_wake() -> None:
        await _reset_failed_lead_session_if_needed(
            openclaw_call=openclaw_call,
            session_key=lead_session_key,
            config=config,
        )
        await ensure_session(
            lead_session_key,
            config=config,
            label=lead.name,
            model=_agent_session_model(lead),
            clear_model_override=_agent_session_should_clear_model(lead),
        )
        await send_session_message_nonblocking(
            message,
            session_key=lead_session_key,
            config=config,
            idempotency_key=str(
                uuid5(
                    _SPRINT_WAKE_IDEMPOTENCY_NAMESPACE,
                    f"sprint-start:{sprint.id}:{lead.id}",
                ),
            ),
        )

    try:
        await _send_lead_wake()
    except OpenClawGatewayError as exc:
        if _AGENT_MISSING_HINT in str(exc).lower():
            try:
                await OpenClawGatewayProvisioner().sync_gateway_agent_heartbeats(
                    gateway,
                    list(agents),
                )
                await _send_lead_wake()
                return
            except Exception:
                logger.exception(
                    "sprint.start.lead_wake.retry_failed board_id=%s lead_agent_id=%s",
                    board.id,
                    lead.id,
                )
                return
        logger.exception(
            "sprint.start.lead_wake.failed board_id=%s lead_agent_id=%s",
            board.id,
            lead.id,
        )
    except Exception:
        logger.exception(
            "sprint.start.lead_wake.failed board_id=%s lead_agent_id=%s",
            board.id,
            lead.id,
        )


async def _reset_failed_lead_session_if_needed(
    *,
    openclaw_call: Any,
    session_key: str,
    config: object,
) -> None:
    """Reset a canonical lead session that is already known failed.

    A failed OpenClaw session can persist across later runtime fixes. If sprint
    start only sends another message to that poisoned session, the lead may not
    resume heartbeat/check-in even though the agent is registered correctly.
    """
    if not session_key:
        return
    try:
        sessions = await openclaw_call("sessions.list", {}, config=config)
    except Exception:
        return
    raw_items = []
    if isinstance(sessions, dict):
        maybe_items = sessions.get("sessions") or sessions.get("items") or []
        if isinstance(maybe_items, list):
            raw_items = maybe_items
    elif isinstance(sessions, list):
        raw_items = sessions

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if item.get("key") != session_key:
            continue
        if item.get("status") != "failed":
            return
        try:
            await openclaw_call("sessions.reset", {"key": session_key}, config=config)
        except Exception:
            return
        return


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
        from app.models.sprints import Sprint as _Sprint  # noqa: PLC0415
        from app.models.sprints import SprintTicket
        from app.models.tasks import Task  # noqa: PLC0415
        from app.services.activity_log import record_activity  # noqa: PLC0415

        if sprint.status not in _SPRINT_ALLOWED_START_STATUSES:
            from fastapi import HTTPException
            from fastapi import status as http_status  # noqa: PLC0415

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
            from fastapi import HTTPException
            from fastapi import status as http_status  # noqa: PLC0415

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
            await session.exec(select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id))
        ).all()

        committed = 0
        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None:
                task.is_backlog = False
                task.status = "inbox"
                task.updated_at = utcnow()
                session.add(task)
                committed += task.estimate_minutes or 0

        # Snapshot committed_minutes = sum of estimate_minutes for all sprint tickets
        sprint.committed_minutes = committed if committed > 0 else None
        session.add(sprint)

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
        await _wake_board_lead_for_started_sprint(
            session,
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
        """Check if the active sprint is ready for review; if so, start review."""
        from app.models.boards import Board as _Board  # noqa: PLC0415
        from app.models.sprints import Sprint as _Sprint  # noqa: PLC0415
        from app.models.sprints import SprintTicket
        from app.models.tasks import Task  # noqa: PLC0415

        sprint = (
            await session.exec(
                select(_Sprint)
                .where(col(_Sprint.board_id) == board_id)
                .where(col(_Sprint.status).in_(["active", "reviewing"]))
                .order_by(col(_Sprint.updated_at).desc())
            )
        ).first()

        if sprint is None:
            return

        tickets = (
            await session.exec(select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id))
        ).all()

        if not tickets:
            return

        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is None or task.status != "done":
                return  # Still work to do

        # All tickets are done — enter or re-enter the review gate.
        board = await session.get(_Board, board_id)
        if board is None:
            return

        from app.services.sprint_reviews import begin_sprint_review  # noqa: PLC0415

        if sprint.status == "reviewing":
            from app.models.sprints import SprintReview  # noqa: PLC0415

            reviews = (
                await session.exec(
                    select(SprintReview).where(col(SprintReview.sprint_id) == sprint.id)
                )
            ).all()
            if reviews and not any(
                review.status in {"changes_requested", "skipped"} for review in reviews
            ):
                return

        await begin_sprint_review(session, sprint=sprint, board=board)

    @staticmethod
    async def complete_sprint(
        session: AsyncSession,
        *,
        sprint: Sprint,
        board: Board,
        allow_reviewing: bool = False,
    ) -> None:
        """Complete a sprint: archive done tickets, optionally auto-advance."""
        from app.models.sprints import Sprint as _Sprint  # noqa: PLC0415
        from app.models.sprints import SprintTicket
        from app.models.tasks import Task  # noqa: PLC0415
        from app.services.activity_log import record_activity  # noqa: PLC0415

        allowed_statuses = {"active"}
        if allow_reviewing:
            allowed_statuses.add("reviewing")
        if sprint.status not in allowed_statuses:
            from fastapi import HTTPException
            from fastapi import status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Sprint cannot be completed from status '{sprint.status}'.",
            )

        sprint.status = "completed"
        sprint.completed_at = utcnow()
        sprint.updated_at = utcnow()
        session.add(sprint)

        tickets = (
            await session.exec(select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id))
        ).all()

        tickets_done = 0
        completed_estimate = 0
        completed_actual = 0
        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None and task.status == "done":
                task.is_backlog = True  # Legacy flag
                task.status = "archived"  # Move off the board
                task.updated_at = utcnow()
                session.add(task)
                tickets_done += 1
                completed_estimate += task.estimate_minutes or 0
                completed_actual += task.actual_minutes or 0

        # Snapshot velocity fields
        sprint.completed_minutes = completed_estimate if completed_estimate > 0 else None
        sprint.actual_minutes = completed_actual if completed_actual > 0 else None
        session.add(sprint)

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

        # Auto-advance to the next loaded sprint if flow mode is enabled.
        if board.auto_advance_sprint:
            next_sprints = (
                await session.exec(
                    select(_Sprint)
                    .where(col(_Sprint.board_id) == board.id)
                    .where(col(_Sprint.status).in_(["queued", "draft"]))
                    .order_by(col(_Sprint.position).asc())
                )
            ).all()
            for next_sprint in next_sprints:
                next_tickets = (
                    await session.exec(
                        select(SprintTicket).where(col(SprintTicket.sprint_id) == next_sprint.id)
                    )
                ).all()
                has_open_work = False
                for next_ticket in next_tickets:
                    next_task = await session.get(Task, next_ticket.task_id)
                    if next_task is not None and next_task.status not in {"done", "archived"}:
                        has_open_work = True
                        break
                if not has_open_work:
                    continue
                try:
                    await SprintService.start_sprint(session, sprint=next_sprint, board=board)
                except Exception:
                    logger.exception(
                        "sprint.auto_advance_failed board_id=%s next_sprint_id=%s",
                        board.id,
                        next_sprint.id,
                    )
                break

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
            from fastapi import HTTPException
            from fastapi import status as http_status  # noqa: PLC0415

            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a sprint with status '{sprint.status}'.",
            )

        sprint.status = "cancelled"
        sprint.updated_at = utcnow()
        session.add(sprint)

        tickets = (
            await session.exec(select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint.id))
        ).all()

        for ticket in tickets:
            task = await session.get(Task, ticket.task_id)
            if task is not None:
                if task.status != "done":
                    task.is_backlog = True
                    task.status = "backlog"  # Return to off-board backlog for re-planning
                else:
                    task.is_backlog = True
                    task.status = "archived"  # Archive completed work
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
