"""Lightweight recovery wakes for board agents with assigned board work."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import and_, not_, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.agent_tokens import verify_agent_token
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.tasks import Task
from app.services.activity_log import record_activity
from app.services.openclaw.constants import OFFLINE_AFTER
from app.services.openclaw.gateway_dispatch import GatewayDispatchService
from app.services.openclaw.gateway_rpc import GatewayConfig, OpenClawGatewayError
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.db_agent_state import mint_agent_token
from app.services.openclaw.lifecycle_orchestrator import _read_workspace_auth_token
from app.services.openclaw.provisioning import (
    GatewayAgentRegistration,
    OpenClawGatewayControlPlane,
    OpenClawGatewayProvisioner,
    _agent_model_config,
    _agent_session_model,
    _agent_session_should_clear_model,
    _board_code_repo_url,
    _board_code_workspace_root,
    _board_code_worktree_path,
    _heartbeat_config,
    _workspace_path,
)
from app.services.openclaw.provisioning_db import fetch_db_template_overrides

logger = get_logger(__name__)


class _MergeBoardStats(TypedDict):
    name: object
    workspace_root: object
    active_count: int
    review_count: int


class _LeadBoardStats(_MergeBoardStats):
    inbox_count: int


class _LeadReviewAction(TypedDict):
    task_id: object
    title: str
    comment: str
    created_at: datetime


def _truncate_snippet(value: str | None, *, limit: int = 500) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _agent_api_url(path: str) -> str:
    base_url = settings.base_url.rstrip("/")
    return f"{base_url}{path}" if base_url else path


def build_task_wake_message(
    *,
    board: Board,
    task: Task,
    agent: Agent,
    gateway_workspace_root: str,
    reason: str,
) -> str:
    if agent.is_board_lead and task.auto_reason == "webhook_alert_triage":
        return _lead_alert_triage_wake_message(
            board=board,
            task=task,
            agent=agent,
            gateway_workspace_root=gateway_workspace_root,
            reason=reason,
        )

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
    inbox_claim = ""
    if task.status == "inbox" and task.assigned_agent_id == agent.id:
        inbox_claim = (
            "\n\nThis task is assigned to you but is still in `inbox`. Your first "
            "AxiaCraft API write must be to claim it before implementation: PATCH "
            f"/api/v1/agent/boards/{board.id}/tasks/{task.id} with JSON "
            '{"status":"in_progress","comment":"Starting work on this assigned task."}. '
            "Do not inspect unrelated tasks first and do not wait for another assignment."
        )
    return (
        "TASK WAKE\n"
        + "\n".join(details)
        + inbox_claim
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


def _lead_alert_triage_wake_message(
    *,
    board: Board,
    task: Task,
    agent: Agent,
    gateway_workspace_root: str,
    reason: str,
) -> str:
    description = _truncate_snippet(task.description, limit=900)
    details = [
        "LEAD ALERT TRIAGE WAKE",
        f"Board: {board.name}",
        f"Board ID: {board.id}",
        f"Task: {task.title}",
        f"Task ID: {task.id}",
        f"Status: {task.status}",
        f"Wake reason: {reason}",
        f"Inspect board tasks: GET /api/v1/agent/boards/{board.id}/tasks?status=inbox",
        f"List assignable agents: GET /api/v1/agent/agents?board_id={board.id}",
        f"Inspect this task comments: GET /api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
        f"Comment on this task: POST /api/v1/agent/boards/{board.id}/tasks/{task.id}/comments",
        f"Assign this task: PATCH /api/v1/agent/boards/{board.id}/tasks/{task.id}",
    ]
    if task.thread_id:
        details.append(f"Linked alert thread ID: {task.thread_id}")
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
        "URGENT API-ONLY LEAD ACTION\n"
        "This wake overrides the normal heartbeat loop. Do not open a browser, do not edit "
        "workspace files, do not edit HEARTBEAT.md, do not update local memory, and do not "
        "search for work assigned to your own AGENT_ID. The task below is already assigned "
        "to you as the board lead. Use AxiaCraft HTTP API calls only, then stop.\n\n"
        + "\n".join(details)
        + "\n\nTake action now as the board lead. This is alert triage, not developer "
        "implementation work. Inspect the linked alert thread and board state, then decide "
        "whether this CI/CD or observability alert is a duplicate, part of an alert storm, "
        "already covered by existing remediation, or genuine new work.\n\n"
        "Do not end this wake after inspection only. Before ending, perform exactly one "
        "AxiaCraft API write: either POST the exact Comment on this task endpoint above with "
        'JSON {"message":"<duplicate/noise/already-covered triage decision and evidence>"} '
        "or PATCH the exact Assign this task endpoint above to assign the task to a developer. "
        "If it is duplicate/noise/already covered, add the comment so the operator can see why "
        "no developer was assigned. If at least one non-lead developer exists and there is no "
        "existing active remediation task for the same alert/source, treat it as genuine work: "
        "choose an available non-lead developer and assign plus start this same task with JSON "
        '{"assigned_agent_id":"<developer_agent_id>","status":"in_progress",'
        '"comment":"<triage decision and reason>"}. '
        f"The board_id is exactly `{board.id}` and the task_id is exactly `{task.id}`; never "
        "combine, concatenate, shorten, or rewrite these IDs when building URLs. "
        f"Use `GET /api/v1/agent/agents?board_id={board.id}` for the roster. Do not use "
        "`/api/v1/agent/boards/<board_id>/agents`; that route is wrong for roster listing. "
        "Do not create a duplicate task unless the alert needs to be split. Do not use "
        "OpenClaw direct-message or channel-send tools for assignment; assignment is an "
        "AxiaCraft API write and will wake the developer automatically."
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
        "comments and developer worktrees when branch custom fields are missing. Before calling "
        "AxiaCraft APIs, read the current TOOLS.md and use its current X-Agent-Token; do not "
        "reuse tokens copied from earlier session history. Merge committed changes into the "
        "merge worktree/mainline. If Git reports conflicts, resolve "
        "them in the integration worktree when the intended combined result is clear; this is "
        "your core responsibility, including Terraform, pipeline, requirements, migration, "
        "config, documentation, formatting, and additive module conflicts. After resolving, run "
        "the relevant checks, then push the updated mainline branch to origin. Include the pushed "
        "remote branch and SHA in the task comment. If push fails, leave the task in `review` and "
        "post the exact error for the lead. After a successful push, "
        "move successfully merged tasks to `done` with PATCH "
        f"/api/v1/agent/boards/{board.id}/tasks/{{task_id}} and JSON "
        '{"status":"done","comment":"<merge SHA, branch/worktree, checks, and evidence>"}. '
        "A Git conflict alone is not a blocker. Escalate only when you have attempted resolution "
        "and a remaining conflict requires product or implementation judgement you cannot safely "
        "make. If work is uncommitted, missing, checks fail, or conflict resolution still needs a "
        "decision, notify the lead and original developer in the review task comment with the "
        "attempted resolution, exact files/hunks, and decision needed, and also post one concise "
        "board chat message via POST "
        f'/api/v1/agent/boards/{board.id}/memory with tags ["chat","merge_blocker"]. '
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
    review_actions: list[_LeadReviewAction] | None = None,
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
    if review_actions:
        details.append("Lead review actions:")
        for action in review_actions[:10]:
            task_path = f"/api/v1/agent/boards/{board.id}/tasks/{action['task_id']}"
            details.append(
                "- "
                f"Task {action['task_id']}: {action['title']} | "
                f"latest escalation: {_truncate_snippet(action['comment'], limit=260)}"
            )
            details.append(f"  exact comments endpoint: GET {_agent_api_url(task_path)}/comments")
            details.append(f"  exact update endpoint: PATCH {_agent_api_url(task_path)}")
    return (
        "\n".join(details)
        + "\n\nTake action now: inspect the board, assign ready inbox work, check in-progress "
        "developer tasks for progress comments or blockers, and review tasks in `review` for "
        "quality, acceptance criteria, test evidence, and merge readiness. Before calling "
        "AxiaCraft APIs, read the current TOOLS.md and use its current X-Agent-Token; do not "
        "reuse tokens copied from earlier session history. Do not ask the operator whether to "
        "proceed; make assignment decisions now when inbox work is ready.\n\n"
        "Mandatory assignment loop: list inbox tasks, list board agents, choose non-lead "
        "developer owners, PATCH every ready inbox task, then re-read the inbox until every "
        "ready task has an `assigned_agent_id`. Assign developers with PATCH "
        f"`/api/v1/agent/boards/{board.id}/tasks/{{task_id}}` and JSON "
        '{"assigned_agent_id":"<developer_agent_id>"}. Assignment is an AxiaCraft API write, '
        "not a chat/message operation. Do not use OpenClaw direct-message tools, "
        "channel/message tools, session labels, `sessions.resolve`, `dev-1`, `dev-2`, "
        "`dev-agent-1`, or `dev-agent-2` for developer assignment; those labels may not exist. "
        "If a message/channel tool returns `Action send requires a target`, `Channel is "
        "required`, or any similar routing error, abandon that path immediately and use the "
        "PATCH assignment endpoint instead. Assignment via AxiaCraft wakes the worker "
        "automatically. For webhook alert triage tasks, including any that have incorrectly "
        "landed in `review`, do not send them to the merge agent and do not leave them in "
        "`review`: decide whether they are duplicate/noise/already-covered/genuine. For genuine "
        "work, assign a non-lead developer and start the same task with JSON "
        '{"assigned_agent_id":"<developer_agent_id>","status":"in_progress",'
        '"comment":"<triage decision and reason>"}. If duplicate/noise/already-covered, close '
        "or comment with the decision and evidence. Make the board-lead decision using "
        "the task comments, merge evidence, and "
        "available checks. Do not mark review tasks `done` before the code is merged to mainline. "
        "If the work is ready, wake or mention the merge agent with the task id, "
        "branch/commit/worktree evidence, and expected checks. If the merge agent reports that "
        "mainline contains the work but the task is still in `review`, run or inspect any "
        "available checks from the lead workspace. If checks cannot be run or queried from this "
        "runtime and there is no concrete failing evidence, accept the merge evidence, note the "
        "CI visibility limitation in the task comment, and move it to `done` with the exact "
        "per-task PATCH endpoint listed above. Copy the listed board id and task id exactly; do "
        "not reconstruct them from memory. Use JSON "
        '{"status":"done","comment":"<merge SHA, checks, and evidence>"}. '
        "A task comment stating that a commit is now in main via a merge commit is sufficient "
        "merge evidence; do not block solely because the lead workspace or local git remote "
        "does not contain that merge SHA. "
        "Read task comments with the exact per-task comments endpoint listed above, or with GET "
        f"/api/v1/agent/boards/{board.id}/tasks/{{task_id}}/comments; do not omit the "
        "`/tasks/` path segment. If work "
        "is blocked, read recent board chat for merge_blocker messages, post a task comment "
        "naming the blocker, and send it back to the developer when rework is needed."
    )


def _comment_needs_lead_review_action(message: str | None) -> bool:
    text = (message or "").lower()
    if "@lead" not in text and "lead" not in text:
        return False
    action_terms = (
        "verify",
        "ci",
        "checks",
        "main",
        "merge commit",
        "merged",
        "move to done",
        "marking done",
        "mark done",
    )
    return any(term in text for term in action_terms)


async def _lead_review_actions_for_board(
    session: AsyncSession,
    *,
    board_id: object,
) -> list[_LeadReviewAction]:
    review_tasks = (
        await session.exec(
            select(Task)
            .where(col(Task.board_id) == board_id)
            .where(col(Task.status) == "review")
            .order_by(col(Task.updated_at).desc()),
        )
    ).all()
    actions: list[_LeadReviewAction] = []
    for task in review_tasks:
        latest_comment = (
            await session.exec(
                select(ActivityEvent)
                .where(col(ActivityEvent.task_id) == task.id)
                .where(col(ActivityEvent.event_type) == "task.comment")
                .order_by(col(ActivityEvent.created_at).desc()),
            )
        ).first()
        if latest_comment is None or not _comment_needs_lead_review_action(latest_comment.message):
            assigned_agent = None
            if task.assigned_agent_id is not None:
                assigned_agent = await Agent.objects.by_id(task.assigned_agent_id).first(session)
            still_lead_triage = task.auto_reason == "webhook_alert_triage" and (
                task.assigned_agent_id is None
                or (assigned_agent is not None and assigned_agent.is_board_lead)
            )
            if not still_lead_triage:
                continue
            comment = (
                "Webhook alert triage task is in `review`; this is not merge-ready code. "
                "Lead must triage duplicate/storm/already-covered/genuine, then assign and "
                "start a developer with status `in_progress` or close with evidence."
            )
            created_at = task.updated_at or task.created_at
        else:
            comment = latest_comment.message or ""
            created_at = latest_comment.created_at
        actions.append(
            {
                "task_id": task.id,
                "title": task.title,
                "comment": comment,
                "created_at": created_at,
            }
        )
    return actions


def _has_new_lead_review_action(agent: Agent, actions: list[_LeadReviewAction]) -> bool:
    if not actions:
        return False
    if agent.last_wake_sent_at is None:
        return True
    return any(action["created_at"] > agent.last_wake_sent_at for action in actions)


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


async def _refresh_stale_agent_workspace_token(
    *,
    session: AsyncSession,
    gateway: Gateway,
    board: Board,
    agent: Agent,
) -> bool:
    """Rewrite agent files only when the persisted workspace token cannot auth."""

    if not agent.agent_token_hash:
        return False
    workspace_token = await _read_workspace_auth_token(
        gateway=gateway,
        agent=agent,
        board=board,
    )
    if (
        workspace_token
        and agent.agent_token_hash
        and verify_agent_token(workspace_token, agent.agent_token_hash)
    ):
        return False

    raw_token = mint_agent_token(agent)
    agent.updated_at = utcnow()
    session.add(agent)
    await session.flush()
    db_templates = await fetch_db_template_overrides(
        session,
        board_id=board.id,
        organization_id=gateway.organization_id,
    )
    await OpenClawGatewayProvisioner().apply_agent_lifecycle(
        agent=agent,
        gateway=gateway,
        board=board,
        auth_token=raw_token,
        user=None,
        action="update",
        force_bootstrap=False,
        reset_session=False,
        wake=False,
        deliver_wakeup=False,
        db_templates=db_templates or None,
        patch_heartbeat=True,
    )
    logger.warning(
        "board_agent_work_recovery.workspace_token_refreshed agent_id=%s board_id=%s token_missing=%s",
        agent.id,
        board.id,
        workspace_token is None,
    )
    return True


async def _wake_session_with_lazy_registration(
    *,
    session: AsyncSession,
    dispatch: GatewayDispatchService,
    gateway: Gateway,
    config: GatewayConfig,
    board: Board,
    agent: Agent,
    message: str,
    reset_session: bool = False,
) -> OpenClawGatewayError | None:
    """Wake an existing session, refreshing stale runtime files only when needed."""

    await _refresh_stale_agent_workspace_token(
        session=session,
        gateway=gateway,
        board=board,
        agent=agent,
    )
    error = await dispatch.try_wake_agent_session(
        session_key=agent.openclaw_session_id or "",
        config=config,
        agent_name=agent.name,
        message=message,
        model=_agent_session_model(agent),
        clear_model_override=_agent_session_should_clear_model(agent),
        reset_session=reset_session,
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
            reset_session=reset_session,
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
            session=session,
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            board=board,
            agent=agent,
            message=message,
            reset_session=(
                agent.is_board_lead and task.auto_reason == "webhook_alert_triage"
            ),
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
    if agent.checkin_deadline_at is not None:
        return agent.checkin_deadline_at <= now
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
            .outerjoin(Agent, col(Agent.id) == col(Task.assigned_agent_id))
            .where(col(Task.status) == "review")
            .where(
                not_(
                    and_(
                        col(Task.auto_reason) == "webhook_alert_triage",
                        or_(col(Task.assigned_agent_id).is_(None), col(Agent.is_board_lead).is_(True)),
                    )
                )
            )
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
            session=session,
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            board=board,
            agent=agent,
            message=message,
            reset_session=True,
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
        review_actions = await _lead_review_actions_for_board(session, board_id=board.id)
        if not _agent_needs_work_wake(agent) and not _has_new_lead_review_action(
            agent,
            review_actions,
        ):
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
            review_actions=review_actions,
        )
        error = await _wake_session_with_lazy_registration(
            session=session,
            dispatch=dispatch,
            gateway=gateway,
            config=config,
            board=board,
            agent=agent,
            message=message,
            reset_session=True,
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
