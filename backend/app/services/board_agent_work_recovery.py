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
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.provisioning import (
    GatewayAgentRegistration,
    OpenClawGatewayControlPlane,
    _agent_key,
    _agent_model_config,
    _agent_session_model,
    _board_code_repo_url,
    _board_code_workspace_root,
    _board_code_worktree_path,
    _heartbeat_config,
    _workspace_path,
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


def _wake_comment_message(
    *,
    board: Board,
    task: Task,
    agent: Agent,
    gateway_workspace_root: str,
    reason: str,
) -> str:
    lines = [
        f"System wake sent to {agent.name} ({reason}).",
        f"Task status: {task.status}.",
    ]
    if gateway_workspace_root:
        lines.append(
            f"Expected code worktree: {_board_code_worktree_path(agent, board, gateway_workspace_root)}."
        )
    lines.append(
        "The agent must verify code access and post a progress or completion comment."
    )
    return " ".join(lines)


def _is_merge_agent(agent: Agent) -> bool:
    profile = agent.identity_profile or {}
    return isinstance(profile, dict) and profile.get("role_template") == "merger"


def _merge_wake_message(
    *,
    board: Board,
    agent: Agent,
    gateway_workspace_root: str,
    active_count: int,
    review_count: int,
) -> str:
    details = [
        "MERGE WATCH WAKE",
        f"Board: {board.name}",
        f"Board ID: {board.id}",
        f"Active assigned tasks: {active_count}",
        f"Tasks in review: {review_count}",
    ]
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
        "\n".join(details)
        + "\n\nTake action now: inspect the board shared source worktrees, identify completed "
        "or review-ready developer work, merge clean changes into the merge worktree, and post "
        "task comments describing merged files, conflicts, tests, or blockers. If no worktree "
        "is ready, post a board/task comment explaining what is missing."
    )


def _is_missing_runtime_agent_error(error: OpenClawGatewayError) -> bool:
    message = str(error).lower()
    return (
        "no longer exists in configuration" in message
        or "agent " in message
        and " not found" in message
    )


async def _register_runtime_agent(*, gateway: Gateway, config: object, agent: Agent) -> None:
    if not gateway.workspace_root:
        msg = "gateway workspace_root is required"
        raise OpenClawGatewayError(msg)
    await OpenClawGatewayControlPlane(config).upsert_agent(
        GatewayAgentRegistration(
            agent_id=_agent_key(agent),
            name=agent.name,
            workspace_path=_workspace_path(agent, gateway.workspace_root),
            heartbeat=_heartbeat_config(agent),
            model=_agent_model_config(agent),
        )
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
        if error is not None and _is_missing_runtime_agent_error(error):
            await _register_runtime_agent(gateway=gateway, config=config, agent=agent)
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
        record_activity(
            session,
            event_type="task.comment",
            message=_wake_comment_message(
                board=board,
                task=task,
                agent=agent,
                gateway_workspace_root=gateway.workspace_root,
                reason=reason,
            ),
            agent_id=None,
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
        record_activity(
            session,
            event_type="task.comment",
            message=(
                f"System wake failed for {agent.name} ({reason}). "
                f"Error: {exc!s}"
            ),
            agent_id=None,
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


async def wake_merge_agents_for_active_board_work(session: AsyncSession) -> int:
    """Wake stale merge agents when their board has active work to watch."""
    active_counts = (
        await session.exec(
            select(
                col(Board.id),
                col(Board.name),
                col(Gateway.workspace_root),
                col(Task.status),
            )
            .join(Task, col(Task.board_id) == col(Board.id))
            .join(Gateway, col(Gateway.id) == col(Board.gateway_id))
            .where(col(Task.status).in_(["in_progress", "review"]))
            .where(col(Gateway.url).is_not(None))
        )
    ).all()
    if not active_counts:
        return 0

    boards: dict[object, dict[str, object]] = {}
    for board_id, board_name, workspace_root, task_status in active_counts:
        item = boards.setdefault(
            board_id,
            {
                "name": board_name,
                "workspace_root": workspace_root,
                "active_count": 0,
                "review_count": 0,
            },
        )
        item["active_count"] = int(item["active_count"]) + 1
        if task_status == "review":
            item["review_count"] = int(item["review_count"]) + 1

    rows = (
        await session.exec(
            select(Agent, Board)
            .join(Board, col(Board.id) == col(Agent.board_id))
            .where(col(Agent.board_id).in_(list(boards)))
            .where(col(Agent.openclaw_session_id).is_not(None))
            .where(col(Agent.is_board_lead).is_(False))
        )
    ).all()

    woken = 0
    for agent, board in rows:
        if not _is_merge_agent(agent) or not _agent_needs_work_wake(agent):
            continue
        board_stats = boards[board.id]
        gateway, config = await GatewayDispatchService(
            session,
        ).require_gateway_config_for_board(board)
        message = _merge_wake_message(
            board=board,
            agent=agent,
            gateway_workspace_root=gateway.workspace_root,
            active_count=int(board_stats["active_count"]),
            review_count=int(board_stats["review_count"]),
        )
        error = await GatewayDispatchService(session).try_wake_agent_session(
            session_key=agent.openclaw_session_id,
            config=config,
            agent_name=agent.name,
            message=message,
            model=_agent_session_model(agent),
            reset_stuck_session=True,
        )
        if error is not None and _is_missing_runtime_agent_error(error):
            await _register_runtime_agent(gateway=gateway, config=config, agent=agent)
            error = await GatewayDispatchService(session).try_wake_agent_session(
                session_key=agent.openclaw_session_id,
                config=config,
                agent_name=agent.name,
                message=message,
                model=_agent_session_model(agent),
                reset_stuck_session=True,
            )
        if error is not None:
            record_activity(
                session,
                event_type="board.merge_agent_wake_failed",
                message=f"Merge agent wake failed: {agent.name}. Error: {error!s}",
                agent_id=agent.id,
                board_id=board.id,
            )
            await session.commit()
            continue

        agent.last_wake_sent_at = utcnow()
        agent.checkin_deadline_at = agent.last_wake_sent_at + timedelta(
            seconds=settings.agent_checkin_deadline_seconds,
        )
        agent.wake_attempts += 1
        agent.updated_at = utcnow()
        record_activity(
            session,
            event_type="board.merge_agent_woken",
            message=(
                f"Merge agent wake sent: {agent.name}. "
                f"Active tasks: {board_stats['active_count']}; "
                f"review tasks: {board_stats['review_count']}."
            ),
            agent_id=agent.id,
            board_id=board.id,
        )
        await session.commit()
        woken += 1
        logger.info(
            "board_agent_work_recovery.merge_woke agent_id=%s board_id=%s active_count=%s review_count=%s",
            agent.id,
            board.id,
            board_stats["active_count"],
            board_stats["review_count"],
        )
    return woken


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
    woken = 0
    if not rows:
        return await wake_merge_agents_for_active_board_work(session)

    seen_agent_ids: set[object] = set()
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
    return woken + await wake_merge_agents_for_active_board_work(session)
