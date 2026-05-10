"""Lightweight recovery wakes for board agents with assigned board work."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.services.activity_log import record_activity
from app.services.openclaw.constants import OFFLINE_AFTER
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.provisioning import (
    OpenClawGatewayProvisioner,
    _agent_session_model,
    _board_code_repo_url,
    _board_code_workspace_root,
    _board_code_worktree_path,
)

logger = get_logger(__name__)


def _truncate_snippet(value: str | None, *, limit: int = 500) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def build_task_wake_message(
    *,
    board: Board,
    task: Task,
    agent: Agent,
    gateway_workspace_root: str,
    reason: str,
) -> str:
    description = _truncate_snippet(task.description)
    details = [
        f"Board: {board.name}",
        f"Board ID: {board.id}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
        f"Wake reason: {reason}",
    ]
    if description:
        details.append(f"Description: {description}")
    repo_url = _board_code_repo_url(board)
    if repo_url:
        details.append(f"Repo URL: {repo_url}")
    if gateway_workspace_root:
        details.extend(
            [
                f"CODE_WORKSPACE_ROOT: {_board_code_workspace_root(board, gateway_workspace_root)}",
                f"CODE_WORKTREE_PATH: {_board_code_worktree_path(agent, board, gateway_workspace_root)}",
            ]
        )
    return (
        "TASK WAKE\n"
        + "\n".join(details)
        + "\n\nTake action now: read TOOLS.md and HEARTBEAT.md, verify the code workspace, "
        "then continue this task. If the worktree is missing, clone/create it from the repo URL "
        "above. If code access is still missing, add a task comment with the exact missing path "
        "or credential instead of going silent."
    )


async def wake_agent_for_task(
    *,
    session: AsyncSession,
    board: Board,
    task: Task,
    agent: Agent,
    reason: str,
) -> bool:
    """Wake one assigned agent for one task without reprovisioning its workspace."""
    if not agent.openclaw_session_id:
        return False
    dispatch = GatewayDispatchService(session)
    try:
        gateway, config = await dispatch.require_gateway_config_for_board(board)
        await OpenClawGatewayProvisioner().sync_gateway_agent_heartbeats(gateway, [agent])
        message = build_task_wake_message(
            board=board,
            task=task,
            agent=agent,
            gateway_workspace_root=gateway.workspace_root,
            reason=reason,
        )
        error = await dispatch.try_wake_agent_session(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=message,
            model=_agent_session_model(agent),
            reset_stuck_session=True,
        )
        if error is not None:
            raise error
        agent.last_wake_sent_at = utcnow()
        agent.checkin_deadline_at = agent.last_wake_sent_at + timedelta(
            seconds=settings.agent_checkin_deadline_seconds,
        )
        agent.wake_attempts += 1
        agent.updated_at = utcnow()
        record_activity(
            session,
            event_type="task.assignee_woken",
            message=(f"Assignee session wake sent ({reason}): {agent.name}."),
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
        return True
    except Exception as exc:  # pragma: no cover - best effort recovery path
        record_activity(
            session,
            event_type="task.assignee_wake_failed",
            message=(f"Assignee wake failed ({reason}): {agent.name}. Error: {exc!s}"),
            agent_id=agent.id,
            task_id=task.id,
            board_id=board.id,
        )
        await session.commit()
        return False


def _agent_needs_work_wake(agent: Agent) -> bool:
    now = utcnow()
    if agent.checkin_deadline_at is not None and agent.checkin_deadline_at > now:
        return False
    if agent.status != "online":
        return True
    if agent.last_seen_at is None:
        return True
    return agent.last_seen_at < now - OFFLINE_AFTER


async def wake_stale_board_agents_with_active_work(session: AsyncSession) -> int:
    """Wake stale board agents that already own executable board tasks.

    This is intentionally not lifecycle reconciliation. Active task recovery
    should preserve the existing OpenClaw session and workspace, only making
    sure the runtime knows the agent heartbeat entry and receives a work wake.
    """
    rows = (
        await session.exec(
            select(Agent, Task, Board, Gateway)
            .join(Task, col(Task.assigned_agent_id) == col(Agent.id))
            .join(Board, col(Board.id) == col(Task.board_id))
            .join(Gateway, col(Gateway.id) == col(Agent.gateway_id))
            .where(col(Task.status).in_(["in_progress", "inbox"]))
            .where(col(Agent.board_id) == col(Board.id))
            .where(col(Agent.openclaw_session_id).is_not(None))
            .where(col(Gateway.url).is_not(None))
            .order_by(
                col(Agent.id).asc(),
                col(Task.in_progress_at).is_(None).asc(),
                col(Task.in_progress_at).asc(),
                col(Task.updated_at).asc(),
            )
        )
    ).all()
    if not rows:
        return 0

    seen_agent_ids: set[object] = set()
    woken = 0
    for agent, task, board, gateway in rows:
        _ = gateway
        if agent.id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent.id)
        if not _agent_needs_work_wake(agent):
            continue
        reason = (
            "active_work_recovery"
            if task.status == "in_progress"
            else "assigned_inbox_work_recovery"
        )
        if await wake_agent_for_task(
            session=session,
            board=board,
            task=task,
            agent=agent,
            reason=reason,
        ):
            woken += 1
            logger.info(
                "board_agent_work_recovery.woke agent_id=%s task_id=%s board_id=%s",
                agent.id,
                task.id,
                board.id,
            )
    return woken
