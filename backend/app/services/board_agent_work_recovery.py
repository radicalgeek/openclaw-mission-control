"""Lightweight recovery wakes for board agents with assigned board work."""

from __future__ import annotations

from datetime import timedelta
from typing import TypedDict

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
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.provisioning import (
    GatewayAgentRegistration,
    OpenClawGatewayControlPlane,
    _agent_model_config,
    _agent_session_model,
    _agent_session_should_clear_model,
    _board_code_repo_url,
    _board_code_workspace_root,
    _board_code_worktree_path,
    _heartbeat_config,
    _workspace_path,
)

logger = get_logger(__name__)


class _MergeBoardStats(TypedDict):
    name: object
    workspace_root: object
    active_count: int
    review_count: int


class _LeadBoardStats(_MergeBoardStats):
    inbox_count: int


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
        "or credential instead of going silent.\n\n"
        f"When implementation is complete, move the task to review with PATCH "
        f"/api/v1/agent/boards/{board.id}/tasks/{task.id} and JSON "
        '{"status":"review","comment":"<summary, commits, tests, and evidence>"}. '
        "Do not invent a separate task status endpoint. Read and write comments only through "
        f"/api/v1/agent/boards/{board.id}/tasks/{task.id}/comments."
    )


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
        + "\n\nTake action now: inspect all tasks currently in `review`, including task "
        "comments and developer worktrees when branch custom fields are missing. Merge clean "
        "committed changes into the merge worktree/mainline, run the relevant checks, then "
        "move successfully merged tasks to `done` with PATCH "
        f"/api/v1/agent/boards/{board.id}/tasks/{{task_id}} and JSON "
        '{"status":"done","comment":"<merge SHA, branch/worktree, checks, and evidence>"}. '
        "If work is uncommitted, missing, conflicted, or not mergeable, notify the lead and "
        "original developer in the review task comment, and also post one concise board chat "
        "message via POST "
        f"/api/v1/agent/boards/{board.id}/memory with tags [\"chat\",\"merge_blocker\"]. "
        "Do not use OpenClaw message/channel-send tools for board chat. Leave the task in "
        "`review` for follow-up."
    )


def _lead_wake_message(
    *,
    board: Board,
    agent: Agent,
    gateway_workspace_root: str,
    inbox_count: int,
    active_count: int,
    review_count: int,
) -> str:
    details = [
        "BOARD LEAD WATCH WAKE",
        f"Board: {board.name}",
        f"Board ID: {board.id}",
        f"Inbox tasks: {inbox_count}",
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
        + "\n\nTake action now: inspect the board, assign ready inbox work, check in-progress "
        "developer tasks for progress comments or blockers, and review tasks in `review` for "
        "quality, acceptance criteria, test evidence, and merge readiness. Do not mark review "
        "tasks `done` before the code is merged to mainline. If the work is ready, wake or "
        "mention the merge agent with the task id, branch/commit/worktree evidence, and expected "
        "checks. If the merge agent reports that mainline contains the work but the task is "
        "still in `review`, move it to `done` with a comment containing the merge SHA. If work "
        "is blocked, read recent board chat for merge_blocker messages, post a task comment "
        "naming the blocker, and send it back to the developer when rework is needed."
    )


def _is_missing_runtime_agent_error(error: OpenClawGatewayError) -> bool:
    message = str(error).lower()
    return (
        "no longer exists in configuration" in message
        or "agent " in message
        and " not found" in message
    )


async def _refresh_runtime_agent_registration(
    *, gateway: Gateway, config: GatewayConfig, agent: Agent
) -> None:
    """Refresh lightweight gateway runtime state without touching agent files."""

    if not gateway.workspace_root:
        msg = "gateway workspace_root is required"
        raise OpenClawGatewayError(msg)
    control_plane = OpenClawGatewayControlPlane(config)
    agent_id = _agent_key(agent)
    workspace_path = _workspace_path(agent, gateway.workspace_root)
    heartbeat = _heartbeat_config(agent)
    model = _agent_model_config(agent)
    await control_plane.upsert_agent(
        GatewayAgentRegistration(
            agent_id=agent_id,
            name=agent.name,
            workspace_path=workspace_path,
            heartbeat=heartbeat,
            model=model,
        )
    )
    await control_plane.patch_agent_heartbeats(
        [(agent_id, workspace_path, heartbeat, model)],
    )


async def _wake_session_with_lazy_registration(
    *,
    dispatch: GatewayDispatchService,
    gateway: Gateway,
    config: GatewayConfig,
    agent: Agent,
    message: str,
) -> OpenClawGatewayError | None:
    """Wake an existing session, refreshing runtime registration only if missing."""

    error = await dispatch.try_wake_agent_session(
        session_key=agent.openclaw_session_id or "",
        config=config,
        agent_name=agent.name,
        message=message,
        model=_agent_session_model(agent),
        clear_model_override=_agent_session_should_clear_model(agent),
        reset_stuck_session=True,
    )
    if error is not None and _is_missing_runtime_agent_error(error):
        await _refresh_runtime_agent_registration(gateway=gateway, config=config, agent=agent)
        error = await dispatch.try_wake_agent_session(
            session_key=agent.openclaw_session_id or "",
            config=config,
            agent_name=agent.name,
            message=message,
            model=_agent_session_model(agent),
            clear_model_override=_agent_session_should_clear_model(agent),
            reset_stuck_session=True,
        )
    return error


def _mark_work_wake_sent(agent: Agent) -> None:
    now = utcnow()
    agent.last_wake_sent_at = now
    agent.checkin_deadline_at = now + timedelta(
        seconds=settings.agent_checkin_deadline_seconds,
    )
    if agent.status != "deleting":
        agent.status = "online"
    agent.wake_attempts += 1
    agent.updated_at = now


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
        error = await _wake_session_with_lazy_registration(
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            agent=agent,
            message=message,
        )
        if error is not None:
            raise error
        _mark_work_wake_sent(agent)
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
            .where(col(Task.status) == "review")
            .where(col(Gateway.url).is_not(None))
        )
    ).all()
    if not active_counts:
        return 0

    boards: dict[object, _MergeBoardStats] = {}
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
        dispatch = GatewayDispatchService(session)
        gateway, config = await dispatch.require_gateway_config_for_board(board)
        message = _merge_wake_message(
            board=board,
            agent=agent,
            gateway_workspace_root=gateway.workspace_root,
            active_count=int(board_stats["active_count"]),
            review_count=int(board_stats["review_count"]),
        )
        error = await _wake_session_with_lazy_registration(
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            agent=agent,
            message=message,
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

        _mark_work_wake_sent(agent)
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


async def wake_board_leads_for_active_board_work(session: AsyncSession) -> int:
    """Wake stale board leads when their board has work that needs orchestration."""
    task_rows = (
        await session.exec(
            select(
                col(Board.id),
                col(Board.name),
                col(Gateway.workspace_root),
                col(Task.status),
            )
            .join(Task, col(Task.board_id) == col(Board.id))
            .join(Gateway, col(Gateway.id) == col(Board.gateway_id))
            .where(col(Task.status).in_(["inbox", "in_progress", "review"]))
            .where(col(Gateway.url).is_not(None))
        )
    ).all()
    if not task_rows:
        return 0

    boards: dict[object, _LeadBoardStats] = {}
    for board_id, board_name, workspace_root, task_status in task_rows:
        item = boards.setdefault(
            board_id,
            {
                "name": board_name,
                "workspace_root": workspace_root,
                "inbox_count": 0,
                "active_count": 0,
                "review_count": 0,
            },
        )
        if task_status == "inbox":
            item["inbox_count"] = int(item["inbox_count"]) + 1
        elif task_status == "review":
            item["review_count"] = int(item["review_count"]) + 1
        else:
            item["active_count"] = int(item["active_count"]) + 1

    rows = (
        await session.exec(
            select(Agent, Board)
            .join(Board, col(Board.id) == col(Agent.board_id))
            .where(col(Agent.board_id).in_(list(boards)))
            .where(col(Agent.openclaw_session_id).is_not(None))
            .where(col(Agent.is_board_lead).is_(True))
        )
    ).all()

    woken = 0
    for agent, board in rows:
        if not _agent_needs_work_wake(agent):
            continue
        board_stats = boards[board.id]
        dispatch = GatewayDispatchService(session)
        gateway, config = await dispatch.require_gateway_config_for_board(board)
        message = _lead_wake_message(
            board=board,
            agent=agent,
            gateway_workspace_root=gateway.workspace_root,
            inbox_count=int(board_stats["inbox_count"]),
            active_count=int(board_stats["active_count"]),
            review_count=int(board_stats["review_count"]),
        )
        error = await _wake_session_with_lazy_registration(
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            agent=agent,
            message=message,
        )
        if error is not None:
            record_activity(
                session,
                event_type="board.lead_wake_failed",
                message=f"Board lead wake failed: {agent.name}. Error: {error!s}",
                agent_id=agent.id,
                board_id=board.id,
            )
            await session.commit()
            continue

        _mark_work_wake_sent(agent)
        record_activity(
            session,
            event_type="board.lead_woken",
            message=(
                f"Board lead wake sent: {agent.name}. "
                f"Inbox tasks: {board_stats['inbox_count']}; "
                f"active tasks: {board_stats['active_count']}; "
                f"review tasks: {board_stats['review_count']}."
            ),
            agent_id=agent.id,
            board_id=board.id,
        )
        await session.commit()
        woken += 1
        logger.info(
            "board_agent_work_recovery.lead_woke agent_id=%s board_id=%s inbox_count=%s active_count=%s review_count=%s",
            agent.id,
            board.id,
            board_stats["inbox_count"],
            board_stats["active_count"],
            board_stats["review_count"],
        )
    return woken


async def wake_stale_board_agents_with_active_work(session: AsyncSession) -> int:
    """Wake stale board agents that already own executable board tasks.

    This is intentionally not lifecycle reconciliation. Active task recovery
    should preserve the existing OpenClaw session and workspace. It wakes only
    concrete work. Gateway runtime registration is refreshed only if OpenClaw
    reports the existing agent is missing.
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
        return await wake_board_leads_for_active_board_work(
            session
        ) + await wake_merge_agents_for_active_board_work(session)

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
    return (
        woken
        + await wake_board_leads_for_active_board_work(session)
        + await wake_merge_agents_for_active_board_work(session)
    )
