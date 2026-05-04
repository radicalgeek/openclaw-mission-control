"""Plan CRUD, chat, and task-promotion endpoints for the planning feature."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import (
    get_board_for_actor_read,
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.plans import Plan
from app.models.tasks import Task
from app.schemas.common import OkResponse
from app.schemas.plans import (
    VALID_DECOMPOSITION_TARGETS,
    PlanAgentUpdateRequest,
    PlanChatRequest,
    PlanChatResponse,
    PlanCommitTicketsResponse,
    PlanCreate,
    PlanPromoteRequest,
    PlanRead,
    PlanUpdate,
)
from app.services.activity_log import record_activity
from app.services.openclaw.planning_service import PlanningMessagingService
from app.services.planning import (
    build_decompose_prompt,
    build_plan_system_prompt,
    build_plan_turn_prompt,
    extract_plan_content,
    generate_slug,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/boards/{board_id}/plans", tags=["plans"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
USER_AUTH_DEP = Depends(require_user_auth)
BOARD_READ_DEP = Depends(get_board_for_user_read)
BOARD_WRITE_DEP = Depends(get_board_for_user_write)


def _planning_enabled_check() -> None:
    if not settings.planning_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _require_plan(
    session: AsyncSession,
    plan_id: UUID,
    board: Board,
) -> Plan:
    plan = await session.get(Plan, plan_id)
    if plan is None or plan.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return plan


async def _task_status_for_plan(session: AsyncSession, plan: Plan) -> str | None:
    if plan.task_id is None:
        return None
    task = await session.get(Task, plan.task_id)
    return task.status if task else None


def _plan_to_read(plan: Plan, task_status: str | None) -> PlanRead:
    return PlanRead(
        id=plan.id,
        board_id=plan.board_id,
        title=plan.title,
        slug=plan.slug,
        content=plan.content,
        status=plan.status,
        decomposition_target=plan.decomposition_target,
        created_by_user_id=plan.created_by_user_id,
        task_id=plan.task_id,
        task_status=task_status,
        messages=plan.messages,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


# ---------------------------------------------------------------------------
# List plans
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PlanRead])
async def list_plans(
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _auth: AuthContext = USER_AUTH_DEP,
    plan_status: str | None = Query(default=None, alias="status"),
) -> list[PlanRead]:
    """List plans for a board, optionally filtered by status."""
    _planning_enabled_check()
    query = select(Plan).where(col(Plan.board_id) == board.id)
    if plan_status:
        query = query.where(col(Plan.status) == plan_status)
    query = query.order_by(col(Plan.updated_at).desc())
    result = await session.exec(query)
    plans = result.all()

    out: list[PlanRead] = []
    for plan in plans:
        task_status = await _task_status_for_plan(session, plan)
        out.append(_plan_to_read(plan, task_status))
    return out


# ---------------------------------------------------------------------------
# Create plan
# ---------------------------------------------------------------------------


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PlanCreate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> PlanRead:
    """Create a new plan and optionally send an opening message to the lead agent."""
    _planning_enabled_check()

    slug = generate_slug(str(payload.title))
    target = payload.decomposition_target
    if target not in VALID_DECOMPOSITION_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"decomposition_target must be one of {sorted(VALID_DECOMPOSITION_TARGETS)}",
        )
    plan = Plan(
        board_id=board.id,
        title=str(payload.title),
        slug=slug,
        content="",
        status="draft",
        decomposition_target=target,
        created_by_user_id=auth.user.id if auth.user else None,
        session_key="",
        messages=[],
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)

    # If a gateway is configured and an initial prompt provided, kick off the session.
    if payload.initial_prompt:
        try:
            dispatcher = PlanningMessagingService(session)
            prompt = build_plan_system_prompt(
                board_name=board.name,
                board_objective=board.objective,
                current_content="",
                base_url=settings.base_url,
                board_id=str(board.id),
                plan_id=str(plan.id),
            )
            full_prompt = f"{prompt}\n\n## Opening Message\n{payload.initial_prompt}"
            session_key = await dispatcher.dispatch_plan_start(
                board=board,
                prompt=full_prompt,
                correlation_id=f"planning.create:{plan.id}",
            )
            plan.session_key = session_key
            plan.messages = [{"role": "user", "content": payload.initial_prompt}]
            plan.updated_at = utcnow()
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
        except HTTPException:
            # Gateway unavailable — plan created without agent session; not fatal.
            logger.warning(
                "planning.create.gateway_unavailable board_id=%s plan_id=%s",
                board.id,
                plan.id,
            )

    record_activity(
        session,
        event_type="plan_created",
        message=f"Plan created: {plan.title}",
        board_id=board.id,
    )
    await session.commit()

    return _plan_to_read(plan, None)


# ---------------------------------------------------------------------------
# Get plan
# ---------------------------------------------------------------------------


@router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(
    plan_id: UUID,
    board: Board = BOARD_READ_DEP,
    session: AsyncSession = SESSION_DEP,
    _auth: AuthContext = USER_AUTH_DEP,
) -> PlanRead:
    """Get a single plan with its full chat transcript and current content."""
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)
    task_status = await _task_status_for_plan(session, plan)
    return _plan_to_read(plan, task_status)


# ---------------------------------------------------------------------------
# Update plan (manual content edit, title, status)
# ---------------------------------------------------------------------------


@router.patch("/{plan_id}", response_model=PlanRead)
async def update_plan(
    plan_id: UUID,
    payload: PlanUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _auth: AuthContext = USER_AUTH_DEP,
) -> PlanRead:
    """Partially update a plan's title, content (manual edit), or status."""
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)

    if plan.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed plans cannot be edited.",
        )

    previous_status = plan.status
    if payload.title is not None:
        plan.title = payload.title
    if payload.content is not None:
        plan.content = payload.content
    if payload.status is not None:
        allowed = {"draft", "active", "archived"}
        if payload.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Allowed: {', '.join(sorted(allowed))}",
            )
        plan.status = payload.status

    plan.updated_at = utcnow()
    session.add(plan)
    await session.commit()
    await session.refresh(plan)

    # Auto-trigger decomposition when a plan transitions draft → active and has
    # content + a non-board target (org_triager / org_planner). Mirrors the
    # explicit POST /decompose path so the user can drive the same flow either
    # by clicking "Activate" or by invoking decompose directly.
    activated = previous_status == "draft" and plan.status == "active"
    has_org_target = plan.decomposition_target in {"org_triager", "org_planner"}
    if activated and has_org_target and plan.content:
        try:
            dispatcher = PlanningMessagingService(session)
            await dispatcher.dispatch_plan_decompose(
                board=board,
                plan=plan,
                prompt=build_decompose_prompt(str(plan.id), str(board.id)),
                correlation_id=f"planning.decompose:{plan.id}",
            )
            record_activity(
                session,
                event_type="plan_decompose_requested",
                message=f"Decompose auto-triggered on plan activation: {plan.title}",
                board_id=board.id,
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "plan.activate_dispatch_failed plan_id=%s err=%s", plan.id, exc
            )

    task_status = await _task_status_for_plan(session, plan)
    return _plan_to_read(plan, task_status)


# ---------------------------------------------------------------------------
# Delete (archive) plan
# ---------------------------------------------------------------------------


@router.delete("/{plan_id}", response_model=OkResponse)
async def delete_plan(
    plan_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    _auth: AuthContext = USER_AUTH_DEP,
) -> OkResponse:
    """Archive a plan, or permanently delete it if it is already archived."""
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)
    if plan.status == "archived":
        # Second delete = permanent removal
        record_activity(
            session,
            event_type="plan_deleted",
            message=f"Plan permanently deleted: {plan.title}",
            board_id=board.id,
        )
        await session.delete(plan)
    else:
        plan.status = "archived"
        plan.updated_at = utcnow()
        session.add(plan)
        record_activity(
            session,
            event_type="plan_archived",
            message=f"Plan archived: {plan.title}",
            board_id=board.id,
        )
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Chat with lead agent
# ---------------------------------------------------------------------------


@router.post("/{plan_id}/chat", response_model=PlanChatResponse)
async def chat_plan(
    plan_id: UUID,
    payload: PlanChatRequest,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> PlanChatResponse:
    """Send a message to the lead agent and receive an updated plan content."""
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)

    if plan.status in {"completed", "archived"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot chat on a completed or archived plan.",
        )

    messages: list[dict[str, object]] = list(plan.messages or [])
    user_message = str(payload.message)
    messages.append({"role": "user", "content": user_message})

    # Build context-aware prompt for the agent
    turn_prompt = build_plan_turn_prompt(
        user_message=user_message,
        current_content=plan.content,
    )

    # Initialise or reuse gateway session
    dispatcher = PlanningMessagingService(session)
    if not plan.session_key:
        system_prompt = build_plan_system_prompt(
            board_name=board.name,
            board_objective=board.objective,
            current_content=plan.content,
            base_url=settings.base_url,
            board_id=str(board.id),
            plan_id=str(plan.id),
        )
        full_prompt = f"{system_prompt}\n\n{turn_prompt}"
        session_key = await dispatcher.dispatch_plan_start(
            board=board,
            prompt=full_prompt,
            correlation_id=f"planning.chat.start:{plan.id}",
        )
        plan.session_key = session_key
    else:
        await dispatcher.dispatch_plan_message(
            board=board,
            plan=plan,
            message=turn_prompt,
            correlation_id=f"planning.chat:{plan.id}",
        )

    # ---- Simulate synchronous reply polling ----------------------------------
    # Note: in production the gateway pushes responses back via the agent-update
    # endpoint. For the initial synchronous implementation we return the
    # current state and let the frontend poll GET /{plan_id} for the reply.
    # The agent will POST to /agent-update when its response is ready.
    agent_reply = "(Agent is processing your message. Please wait a moment and refresh.)"
    updated_content = plan.content

    # Persist the user turn immediately
    plan.messages = messages
    plan.updated_at = utcnow()
    session.add(plan)
    await session.commit()
    await session.refresh(plan)

    return PlanChatResponse(
        messages=list(plan.messages or []),
        content=updated_content,
        agent_reply=agent_reply,
    )


# ---------------------------------------------------------------------------
# Agent push-update endpoint (called by the gateway agent)
# ---------------------------------------------------------------------------


@router.post("/{plan_id}/agent-update", response_model=OkResponse)
async def agent_update_plan(
    plan_id: UUID,
    payload: PlanAgentUpdateRequest,
    board: Board = Depends(get_board_for_actor_read),
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Receive a plan update pushed by the gateway lead agent.

    The agent POSTs ``{reply: str, content?: str}`` after processing a user
    chat turn.  This endpoint appends the assistant message to the transcript
    and (when content is provided) updates ``plan.content``.
    """
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)

    reply = payload.reply
    pushed_content = payload.content

    messages: list[dict[str, object]] = list(plan.messages or [])
    if reply:
        assistant_msg: dict[str, object] = {"role": "assistant", "content": reply}
        if payload.content_type and payload.content_type != "text":
            assistant_msg["content_type"] = payload.content_type
        if payload.app_metadata:
            assistant_msg["metadata"] = payload.app_metadata
        messages.append(assistant_msg)

    # Prefer explicitly pushed content; otherwise try extracting from reply.
    new_content: str | None = None
    if isinstance(pushed_content, str) and pushed_content.strip():
        new_content = pushed_content.strip()
    elif reply:
        new_content = extract_plan_content(reply)

    if new_content is not None:
        plan.content = new_content

    # Store decomposed tickets if agent provided them
    if payload.tickets:
        plan.decomposed_tickets = [
            {"title": t.title, "description": t.description, "priority": t.priority}
            for t in payload.tickets
        ]

    plan.messages = messages
    plan.updated_at = utcnow()
    session.add(plan)
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Promote plan to task
# ---------------------------------------------------------------------------


@router.post("/{plan_id}/promote", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
async def promote_plan(
    plan_id: UUID,
    payload: PlanPromoteRequest,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> PlanRead:
    """Promote a plan to a board task and link them together."""
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)

    if plan.status not in {"draft", "active"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or active plans can be promoted to tasks.",
        )
    if plan.task_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This plan has already been promoted to a task.",
        )

    from app.schemas.tasks import priority_to_score  # noqa: PLC0415

    task_title = payload.task_title or plan.title
    # Resolve priority_score: use explicit score from payload, else derive from priority label
    resolved_priority_score = payload.task_priority_score
    if resolved_priority_score == 50:  # default: auto-set from priority label
        resolved_priority_score = priority_to_score(payload.task_priority)
    # Determine target status: "inbox" (on-board) or "backlog" (off-board)
    target_status = (
        payload.target_status if payload.target_status in {"inbox", "backlog"} else "inbox"
    )
    is_backlog_task = target_status == "backlog"
    task = Task(
        board_id=board.id,
        title=task_title,
        description=plan.content or f"See plan: {plan.title}",
        status=target_status,
        priority=payload.task_priority,
        priority_score=resolved_priority_score,
        estimate_minutes=payload.estimate_minutes,
        assigned_agent_id=payload.assigned_agent_id,
        created_by_user_id=auth.user.id if auth.user else None,
        auto_created=True,
        auto_reason="promoted_from_plan",
        is_backlog=is_backlog_task,
    )
    session.add(task)
    await session.flush()  # populate task.id

    plan.task_id = task.id
    plan.status = "active"
    plan.updated_at = utcnow()
    session.add(plan)

    record_activity(
        session,
        event_type="plan_promoted_to_task",
        message=f"Plan promoted to task: {plan.title} → {task_title}",
        task_id=task.id,
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(plan)

    return _plan_to_read(plan, task.status)


# ---------------------------------------------------------------------------
# Decompose plan → backlog tickets
# ---------------------------------------------------------------------------


@router.post("/{plan_id}/decompose", response_model=OkResponse)
async def decompose_plan(
    plan_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> OkResponse:
    """Dispatch a gateway session that decomposes the plan into backlog tickets.

    The agent will reply via ``agent-update`` with a ``tickets`` list.
    Promotes ``draft`` plans to ``active`` so the triager's heartbeat scan
    (``GET /plans?status=active``) picks the plan up alongside the chat
    prompt.
    """
    _planning_enabled_check()
    plan = await _require_plan(session, plan_id, board)

    if not plan.content:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan has no content to decompose.",
        )

    if plan.status == "draft":
        plan.status = "active"
        plan.updated_at = utcnow()
        session.add(plan)
        await session.commit()
        await session.refresh(plan)

    decompose_prompt = build_decompose_prompt(str(plan.id), str(board.id))

    try:
        dispatcher = PlanningMessagingService(session)
        await dispatcher.dispatch_plan_decompose(
            board=board,
            plan=plan,
            prompt=decompose_prompt,
            correlation_id=f"planning.decompose:{plan_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan.decompose_dispatch_failed plan_id=%s err=%s", plan_id, exc)

    record_activity(
        session,
        event_type="plan_decompose_requested",
        message=f"Decompose requested for plan: {plan.title}",
        board_id=board.id,
    )
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Commit decomposed tickets to the board backlog
# ---------------------------------------------------------------------------


@router.post(
    "/{plan_id}/commit-tickets",
    response_model=PlanCommitTicketsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def commit_plan_tickets(
    plan_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = USER_AUTH_DEP,
) -> PlanCommitTicketsResponse:
    """Commit a plan's decomposed_tickets to the backlog as Task rows.

    Idempotent: if any task already exists with this plan_id, the call returns
    409 to prevent duplicate creation. To re-commit, delete the existing tasks
    first.
    """
    _planning_enabled_check()
    from app.schemas.tasks import priority_to_score  # noqa: PLC0415

    plan = await _require_plan(session, plan_id, board)

    tickets = plan.decomposed_tickets or []
    if not tickets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan has no decomposed tickets to commit.",
        )

    existing_for_plan = await session.exec(
        select(Task).where(col(Task.plan_id) == plan.id),
    )
    if existing_for_plan.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tickets for this plan have already been committed.",
        )

    actor_user_id = auth.user.id if auth.user else None
    created_ids: list[UUID] = []
    for raw in tickets:
        # raw is either a DecomposedTicket (validated) or a plain dict from JSON.
        if isinstance(raw, dict):
            title = str(raw.get("title", "")).strip()
            description = str(raw.get("description") or "")
            priority = str(raw.get("priority") or "medium")
            score_raw = raw.get("priority_score")
            estimate_raw = raw.get("estimate_minutes")
        else:
            title = str(getattr(raw, "title", "")).strip()
            description = str(getattr(raw, "description", "") or "")
            priority = str(getattr(raw, "priority", "medium"))
            score_raw = getattr(raw, "priority_score", None)
            estimate_raw = getattr(raw, "estimate_minutes", None)
        if not title:
            continue
        priority_score = (
            int(score_raw)
            if isinstance(score_raw, (int, float)) and int(score_raw) > 0
            else priority_to_score(priority)
        )
        estimate_minutes: int | None = (
            int(estimate_raw) if isinstance(estimate_raw, (int, float)) else None
        )
        task = Task(
            board_id=board.id,
            title=title,
            description=description,
            status="backlog",
            priority=priority,
            priority_score=priority_score,
            estimate_minutes=estimate_minutes,
            is_backlog=True,
            plan_id=plan.id,
            created_by_user_id=actor_user_id,
            auto_created=True,
            auto_reason="committed_from_plan",
        )
        session.add(task)
        await session.flush()
        created_ids.append(task.id)

    if not created_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan decomposed_tickets contained no usable entries.",
        )

    plan.status = "active"
    plan.updated_at = utcnow()
    session.add(plan)
    record_activity(
        session,
        event_type="plan_tickets_committed",
        message=f"Committed {len(created_ids)} backlog tickets from plan: {plan.title}",
        board_id=board.id,
    )
    await session.commit()

    return PlanCommitTicketsResponse(
        plan_id=plan.id,
        task_ids=created_ids,
        count=len(created_ids),
    )
