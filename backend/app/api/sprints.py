"""Sprint CRUD, lifecycle, ticket management, and backlog API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    ACTOR_DEP,
    ActorContext,
    get_board_for_actor_read,
    get_board_for_actor_write,
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.sprints import Sprint, SprintTicket
from app.models.tasks import Task
from app.schemas.common import OkResponse
from app.schemas.sprint_reviews import SprintReviewGateRead
from app.schemas.sprints import (
    SprintCreate,
    SprintRead,
    SprintTicketAddRequest,
    SprintTicketRead,
    SprintTicketReorderRequest,
    SprintUpdate,
)
from app.schemas.tags import TagRef
from app.schemas.tasks import TaskCreate, TaskRead
from app.services.activity_log import record_activity
from app.services.planning import generate_slug
from app.services.tags import load_tag_state, replace_tags, validate_tag_ids

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/boards/{board_id}", tags=["sprints"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
BOARD_READ_DEP = Depends(get_board_for_user_read)
BOARD_WRITE_DEP = Depends(get_board_for_user_write)
BOARD_ACTOR_WRITE_DEP = Depends(get_board_for_actor_write)
USER_AUTH_DEP = Depends(require_user_auth)
BOARD_ACTOR_READ_DEP = Depends(get_board_for_actor_read)


# ---------------------------------------------------------------------------
# Batch backlog schemas (must be defined before routes that use them)
# ---------------------------------------------------------------------------


class _BatchBacklogTicket(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    priority_score: int = 35  # numeric 1-100; auto-set from priority if not provided
    estimate_minutes: int | None = None
    sprint_id: UUID | None = None
    assigned_agent_id: UUID | None = None


class _BatchBacklogCreate(BaseModel):
    tickets: list[_BatchBacklogTicket]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_sprint(
    session: "AsyncSession",
    sprint_id: UUID,
    board: Board,
) -> Sprint:
    sprint = await session.get(Sprint, sprint_id)
    if sprint is None or sprint.board_id != board.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return sprint


async def _sprint_ticket_counts(
    session: "AsyncSession",
    sprint_id: UUID,
) -> tuple[int, int]:
    """Return (total_tickets, completed_tickets) for a sprint."""
    sprint = await session.get(Sprint, sprint_id)
    tickets = (
        await session.exec(select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint_id))
    ).all()
    total = len(tickets)
    done = 0
    for ticket in tickets:
        task = await session.get(Task, ticket.task_id)
        completed_statuses = {"done"}
        if sprint is not None and sprint.status in {"completed", "cancelled"}:
            completed_statuses.add("archived")
        if task is not None and task.status in completed_statuses:
            done += 1
    return total, done


def _sprint_to_read(
    sprint: Sprint,
    ticket_count: int = 0,
    tickets_done_count: int = 0,
) -> SprintRead:
    return SprintRead(
        id=sprint.id,
        board_id=sprint.board_id,
        name=sprint.name,
        slug=sprint.slug,
        goal=sprint.goal,
        position=sprint.position,
        status=sprint.status,
        started_at=sprint.started_at,
        completed_at=sprint.completed_at,
        created_by_user_id=sprint.created_by_user_id,
        created_at=sprint.created_at,
        updated_at=sprint.updated_at,
        ticket_count=ticket_count,
        tickets_done_count=tickets_done_count,
        committed_minutes=sprint.committed_minutes,
        completed_minutes=sprint.completed_minutes,
        actual_minutes=sprint.actual_minutes,
    )


def _task_to_read(
    task: Task,
    tags: list[TagRef] | None = None,
    tag_ids: list[UUID] | None = None,
) -> TaskRead:
    return TaskRead(
        id=task.id,
        board_id=task.board_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        priority_score=task.priority_score,
        estimate_minutes=task.estimate_minutes,
        actual_minutes=task.actual_minutes,
        done_at=task.done_at,
        due_at=task.due_at,
        assigned_agent_id=task.assigned_agent_id,
        depends_on_task_ids=[],
        tag_ids=tag_ids or [],
        tags=tags or [],
        created_by_user_id=task.created_by_user_id,
        in_progress_at=task.in_progress_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        thread_id=task.thread_id,
        is_backlog=task.is_backlog,
        sprint_id=task.sprint_id,
    )


async def _tasks_to_read_with_tags(
    session: "AsyncSession",
    tasks: list[Task],
) -> list[TaskRead]:
    """Convert tasks to TaskRead, batch-loading tags in a single query."""
    if not tasks:
        return []
    tag_state_map = await load_tag_state(
        session, task_ids=[t.id for t in tasks if t.id is not None]
    )
    result: list[TaskRead] = []
    for task in tasks:
        state = tag_state_map.get(task.id)
        result.append(
            _task_to_read(
                task,
                tags=state.tags if state else None,
                tag_ids=state.tag_ids if state else None,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Sprint CRUD
# ---------------------------------------------------------------------------


@router.get("/sprints", response_model=list[SprintRead])
async def list_sprints(
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
    sprint_status: str | None = Query(default=None, alias="status"),
) -> list[SprintRead]:
    """List sprints for a board, optionally filtered by status."""
    query = select(Sprint).where(col(Sprint.board_id) == board.id)
    if sprint_status:
        statuses = [s.strip() for s in sprint_status.split(",") if s.strip()]
        if statuses:
            query = query.where(col(Sprint.status).in_(statuses))
    query = query.order_by(col(Sprint.position).asc(), col(Sprint.created_at).desc())
    sprints = (await session.exec(query)).all()
    out: list[SprintRead] = []
    for sprint in sprints:
        total, done = await _sprint_ticket_counts(session, sprint.id)
        out.append(_sprint_to_read(sprint, total, done))
    return out


@router.post("/sprints", response_model=SprintRead, status_code=status.HTTP_201_CREATED)
async def create_sprint(
    payload: SprintCreate,
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> SprintRead:
    """Create a new sprint in draft status."""
    slug = generate_slug(payload.name)
    sprint = Sprint(
        organization_id=board.organization_id,
        board_id=board.id,
        name=payload.name,
        slug=slug,
        goal=payload.goal,
        status="draft",
        position=0,
        created_by_user_id=actor.user.id if actor.user else None,
    )
    session.add(sprint)
    record_activity(
        session,
        event_type="sprint_created",
        message=f"Sprint created: {payload.name}",
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(sprint)
    return _sprint_to_read(sprint)


@router.get("/sprints/{sprint_id}", response_model=SprintRead)
async def get_sprint(
    sprint_id: UUID,
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
) -> SprintRead:
    """Get a single sprint with ticket counts."""
    sprint = await _require_sprint(session, sprint_id, board)
    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _sprint_to_read(sprint, total, done)


@router.patch("/sprints/{sprint_id}", response_model=SprintRead)
async def update_sprint(
    sprint_id: UUID,
    payload: SprintUpdate,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintRead:
    """Update sprint name, goal, position, or queue it."""
    sprint = await _require_sprint(session, sprint_id, board)

    if sprint.status in {"completed", "cancelled"}:
        updates = payload.model_dump(exclude_unset=True)
        if set(updates) != {"name"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Completed or cancelled sprints can only be renamed.",
            )

    if payload.name is not None:
        sprint.name = payload.name
    if payload.goal is not None:
        sprint.goal = payload.goal
    if payload.position is not None:
        sprint.position = payload.position
    if payload.status is not None:
        if payload.status == "queued" and sprint.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft sprints can be queued.",
            )
        sprint.status = payload.status

    sprint.updated_at = utcnow()
    session.add(sprint)
    await session.commit()
    await session.refresh(sprint)
    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _sprint_to_read(sprint, total, done)


@router.delete("/sprints/{sprint_id}", response_model=OkResponse)
async def delete_sprint(
    sprint_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> OkResponse:
    """Delete a sprint (only allowed for draft/queued sprints)."""
    sprint = await _require_sprint(session, sprint_id, board)

    if sprint.status not in {"draft", "queued"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or queued sprints can be deleted.",
        )

    await session.delete(sprint)
    record_activity(
        session,
        event_type="sprint_deleted",
        message=f"Sprint deleted: {sprint.name}",
        board_id=board.id,
    )
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Sprint Lifecycle
# ---------------------------------------------------------------------------


class _AutoFromBacklogRequest(BaseModel):
    """Payload for auto-building a sprint from the board backlog."""

    name: str
    goal: str | None = None
    take: int | str = "all"  # "all" or a positive int
    start: bool = False  # if true, start the sprint after attaching tickets


class _AutoFromBacklogResponse(BaseModel):
    """Response detailing the sprint and tickets created."""

    sprint: SprintRead
    task_ids: list[UUID]


@router.post("/sprints/auto-from-backlog", response_model=_AutoFromBacklogResponse)
async def auto_sprint_from_backlog(
    payload: _AutoFromBacklogRequest,
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
) -> _AutoFromBacklogResponse:
    """Create a draft sprint and attach the highest-priority backlog tasks.

    Tasks are sorted by ``priority_score`` desc then ``created_at`` asc so the
    most urgent items land first. Setting ``start=true`` immediately runs the
    existing sprint start lifecycle (tickets move backlog → inbox).
    """
    from sqlalchemy import or_  # noqa: PLC0415

    take: int | None
    if isinstance(payload.take, str):
        if payload.take.lower() == "all":
            take = None
        else:
            try:
                take = int(payload.take)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="take must be 'all' or a positive integer",
                ) from exc
    else:
        take = int(payload.take)
    if take is not None and take <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="take must be 'all' or a positive integer",
        )

    backlog_stmt = (
        select(Task)
        .where(col(Task.board_id) == board.id)
        .where(
            or_(
                col(Task.status).in_(["triage", "backlog"]),
                col(Task.is_backlog).is_(True),
            ),
        )
        .where(col(Task.sprint_id).is_(None))
        .order_by(col(Task.priority_score).desc(), col(Task.created_at).asc())
    )
    backlog = list((await session.exec(backlog_stmt)).all())
    if not backlog:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No unassigned backlog tasks available to attach.",
        )
    selected = backlog if take is None else backlog[:take]

    sprint = Sprint(
        organization_id=board.organization_id,
        board_id=board.id,
        name=payload.name,
        slug=generate_slug(payload.name),
        goal=payload.goal,
        status="draft",
        position=0,
        created_by_user_id=actor.user.id if actor.user else None,
    )
    session.add(sprint)
    await session.flush()

    for idx, task in enumerate(selected):
        link = SprintTicket(sprint_id=sprint.id, task_id=task.id, position=idx)
        session.add(link)
        task.sprint_id = sprint.id
        task.updated_at = utcnow()
        session.add(task)

    record_activity(
        session,
        event_type="sprint_auto_from_backlog",
        message=f"Auto-built sprint '{payload.name}' from {len(selected)} backlog tasks",
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(sprint)

    if payload.start:
        from app.services.sprint_lifecycle import SprintService  # noqa: PLC0415

        await SprintService.start_sprint(session, sprint=sprint, board=board)
        await session.refresh(sprint)

    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _AutoFromBacklogResponse(
        sprint=_sprint_to_read(sprint, total, done),
        task_ids=[t.id for t in selected],
    )


@router.post("/sprints/{sprint_id}/start", response_model=SprintRead)
async def start_sprint(
    sprint_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintRead:
    """Start a sprint: validate no active sprint, push tickets to Inbox."""
    sprint = await _require_sprint(session, sprint_id, board)
    from app.services.sprint_lifecycle import SprintService  # noqa: PLC0415

    await SprintService.start_sprint(session, sprint=sprint, board=board)
    await session.refresh(sprint)
    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _sprint_to_read(sprint, total, done)


@router.post("/sprints/{sprint_id}/complete", response_model=SprintRead)
async def complete_sprint(
    sprint_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintRead:
    """Manually complete an active sprint."""
    sprint = await _require_sprint(session, sprint_id, board)
    from app.services.sprint_lifecycle import SprintService  # noqa: PLC0415

    await SprintService.complete_sprint(session, sprint=sprint, board=board)
    await session.refresh(sprint)
    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _sprint_to_read(sprint, total, done)


class _RunReviewResponse(BaseModel):
    """Response from POST /sprints/{id}/run-review."""

    sprint_id: UUID
    dispatched_reviewers: list[str]
    skipped_reviewers: list[dict[str, str]]  # [{role, reason}]


@router.post("/sprints/{sprint_id}/run-review", response_model=_RunReviewResponse)
async def run_sprint_review(
    sprint_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> _RunReviewResponse:
    """Dispatch QA, Security, and Architecture reviewer agents over the sprint scope."""
    sprint = await _require_sprint(session, sprint_id, board)
    from app.services.sprint_reviews import begin_sprint_review  # noqa: PLC0415

    result = await begin_sprint_review(session, sprint=sprint, board=board)
    return _RunReviewResponse(
        sprint_id=result.sprint_id,
        dispatched_reviewers=result.dispatched_reviewers,
        skipped_reviewers=result.skipped_reviewers,
    )


@router.get("/sprints/{sprint_id}/reviews", response_model=SprintReviewGateRead)
async def get_sprint_reviews(
    sprint_id: UUID,
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
) -> SprintReviewGateRead:
    """Get aggregate review gate status for a sprint."""
    sprint = await _require_sprint(session, sprint_id, board)
    from app.services.sprint_reviews import sprint_review_gate  # noqa: PLC0415

    return await sprint_review_gate(session, sprint=sprint)


@router.post("/sprints/{sprint_id}/cancel", response_model=SprintRead)
async def cancel_sprint(
    sprint_id: UUID,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
) -> SprintRead:
    """Cancel a sprint, returning unfinished tickets to backlog."""
    sprint = await _require_sprint(session, sprint_id, board)
    from app.services.sprint_lifecycle import SprintService  # noqa: PLC0415

    await SprintService.cancel_sprint(session, sprint=sprint, board=board)
    await session.refresh(sprint)
    total, done = await _sprint_ticket_counts(session, sprint.id)
    return _sprint_to_read(sprint, total, done)


# ---------------------------------------------------------------------------
# Sprint Ticket Management
# ---------------------------------------------------------------------------


@router.get("/sprints/{sprint_id}/tickets", response_model=list[TaskRead])
async def list_sprint_tickets(
    sprint_id: UUID,
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
    ticket_status: str | None = Query(default=None, alias="status"),
) -> list[TaskRead]:
    """List tasks linked to this sprint."""
    sprint = await _require_sprint(session, sprint_id, board)
    tickets = (
        await session.exec(
            select(SprintTicket)
            .where(col(SprintTicket.sprint_id) == sprint.id)
            .order_by(col(SprintTicket.position).asc())
        )
    ).all()

    task_list: list[Task] = []
    for ticket in tickets:
        task = await session.get(Task, ticket.task_id)
        if task is None:
            continue
        if ticket_status and task.status != ticket_status:
            continue
        task_list.append(task)
    return await _tasks_to_read_with_tags(session, task_list)


@router.post("/sprints/{sprint_id}/tickets", response_model=list[SprintTicketRead])
async def add_sprint_tickets(
    sprint_id: UUID,
    payload: SprintTicketAddRequest,
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> list[SprintTicketRead]:
    """Add existing backlog tasks to a sprint."""
    sprint = await _require_sprint(session, sprint_id, board)

    existing_last = (
        await session.exec(
            select(SprintTicket)
            .where(col(SprintTicket.sprint_id) == sprint.id)
            .order_by(col(SprintTicket.position).desc())
        )
    ).first()
    next_position = (existing_last.position + 1) if existing_last else 0

    added: list[SprintTicketRead] = []
    for task_id in payload.task_ids:
        task = await session.get(Task, task_id)
        if task is None or task.board_id != board.id:
            continue

        existing_link = (
            await session.exec(select(SprintTicket).where(col(SprintTicket.task_id) == task_id))
        ).first()
        if existing_link is not None:
            continue

        link = SprintTicket(sprint_id=sprint.id, task_id=task_id, position=next_position)
        session.add(link)
        task.sprint_id = sprint.id
        task.updated_at = utcnow()
        session.add(task)
        await session.flush()

        added.append(
            SprintTicketRead(
                id=link.id,
                sprint_id=link.sprint_id,
                task_id=link.task_id,
                position=link.position,
                created_at=link.created_at,
            )
        )
        next_position += 1

    await session.commit()
    return added


@router.delete("/sprints/{sprint_id}/tickets/{task_id}", response_model=OkResponse)
async def remove_sprint_ticket(
    sprint_id: UUID,
    task_id: UUID,
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> OkResponse:
    """Remove a task from a sprint (returns it to unassigned backlog)."""
    sprint = await _require_sprint(session, sprint_id, board)
    link = (
        await session.exec(
            select(SprintTicket)
            .where(col(SprintTicket.sprint_id) == sprint.id)
            .where(col(SprintTicket.task_id) == task_id)
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    task = await session.get(Task, task_id)
    if task is not None:
        task.sprint_id = None
        task.updated_at = utcnow()
        session.add(task)

    await session.delete(link)
    await session.commit()
    return OkResponse()


@router.patch("/sprints/{sprint_id}/tickets/reorder", response_model=OkResponse)
async def reorder_sprint_tickets(
    sprint_id: UUID,
    payload: SprintTicketReorderRequest,
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: ActorContext = ACTOR_DEP,
) -> OkResponse:
    """Update ticket positions within a sprint."""
    sprint = await _require_sprint(session, sprint_id, board)
    for position, task_id in enumerate(payload.task_ids):
        link = (
            await session.exec(
                select(SprintTicket)
                .where(col(SprintTicket.sprint_id) == sprint.id)
                .where(col(SprintTicket.task_id) == task_id)
            )
        ).first()
        if link is not None:
            link.position = position
            session.add(link)
    await session.commit()
    return OkResponse()


# ---------------------------------------------------------------------------
# Backlog (board-level)
# ---------------------------------------------------------------------------


@router.get("/backlog", response_model=list[TaskRead])
async def list_backlog(
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
    sprint_id: UUID | None = Query(default=None),
    unassigned: bool = Query(default=False),
    task_status: str | None = Query(default=None, alias="status"),
) -> list[TaskRead]:
    """List all backlog tasks for a board, filterable by sprint or unassigned."""
    from sqlalchemy import or_  # noqa: PLC0415

    query = select(Task).where(col(Task.board_id) == board.id).order_by(col(Task.created_at).desc())
    if task_status is not None:
        # Explicit status filter
        statuses = [s.strip() for s in task_status.split(",") if s.strip()]
        query = query.where(col(Task.status).in_(statuses))
    else:
        # Default: show off-board items — either status-based or legacy is_backlog flag
        query = query.where(
            or_(
                col(Task.status).in_(["triage", "backlog"]),
                col(Task.is_backlog).is_(True),
            )
        )
    if sprint_id is not None:
        query = query.where(col(Task.sprint_id) == sprint_id)
    elif unassigned:
        query = query.where(col(Task.sprint_id).is_(None))

    tasks = list((await session.exec(query)).all())
    return await _tasks_to_read_with_tags(session, tasks)


@router.post("/backlog", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_backlog_task(
    payload: TaskCreate,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    auth: "AuthContext" = USER_AUTH_DEP,
) -> TaskRead:
    """Create a task directly in the backlog (is_backlog=True)."""
    normalized_tag_ids = await validate_tag_ids(
        session,
        organization_id=board.organization_id,
        tag_ids=list(payload.tag_ids),
    )
    task = Task(
        board_id=board.id,
        title=payload.title,
        description=payload.description,
        status="backlog",
        priority=payload.priority,
        priority_score=payload.priority_score if hasattr(payload, "priority_score") else 35,
        due_at=payload.due_at,
        assigned_agent_id=payload.assigned_agent_id,
        created_by_user_id=payload.created_by_user_id or (auth.user.id if auth.user else None),
        is_backlog=True,
    )
    session.add(task)
    await session.flush()
    if normalized_tag_ids:
        await replace_tags(session, task_id=task.id, tag_ids=normalized_tag_ids)
    record_activity(
        session,
        event_type="backlog_task_created",
        message=f"Backlog task created: {payload.title}",
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(task)

    if board.auto_organise_backlog:
        try:
            await _dispatch_organise_agents(session, board=board)
            await session.commit()
        except Exception:
            logger.warning("backlog.auto_organise.failed board_id=%s", board.id)

    reads = await _tasks_to_read_with_tags(session, [task])
    return reads[0]


class _BacklogOrchestrationResponse(BaseModel):
    """Response from backlog estimate / prioritise dispatch."""

    dispatched: bool
    task_count: int
    task_ids: list[UUID]
    skipped_existing: int
    agent_session: str | None
    reason: str | None = None


def _build_estimate_prompt(board: Board, tasks: list[Task]) -> str:
    """Build the prompt sent to the org estimator for a batch of backlog tasks."""
    lines = [
        f"BACKLOG ESTIMATION REQUEST for board '{board.name}'.",
        "Estimate each task in minutes and write the value to the task field, not a comment.",
        "For each task, call:",
        f"  PATCH /api/v1/agent/boards/{board.id}/tasks/{{task_id}} "
        'with body {"estimate_minutes": <int>}',
        "Do not post an estimate-only comment. The estimate_minutes field is the source of truth.",
        "Use ranges 15, 30, 60, 120, 240, 480 minutes. Pick the closest fit.",
        "",
        "Tasks needing estimates:",
    ]
    for t in tasks:
        lines.append(
            f"- task_id={t.id} | title={t.title} | priority={t.priority} | "
            f"description={(t.description or '').replace(chr(10), ' ')[:200]}",
        )
    return "\n".join(lines)


def _build_prioritise_prompt(board: Board, tasks: list[Task]) -> str:
    """Build the prompt sent to the org prioritiser for a batch of backlog tasks."""
    lines = [
        f"BACKLOG PRIORITISATION REQUEST for board '{board.name}'.",
        "Choose priority (low | medium | high | critical) and a numeric "
        "priority_score (1–100). Higher = more urgent. For each task, call:",
        '  PATCH /api/v1/tasks/{task_id} with body {"priority": "...", "priority_score": <int>}',
        "Consider the board objective when ranking.",
        f"Board objective: {board.objective or '(not set)'}",
        "",
        "Tasks needing priority:",
    ]
    for t in tasks:
        lines.append(
            f"- task_id={t.id} | title={t.title} | "
            f"description={(t.description or '').replace(chr(10), ' ')[:200]}",
        )
    return "\n".join(lines)


def _build_planning_prompt(board: Board) -> str:
    """Build the prompt sent to the org planner when backlog auto-organise is enabled."""
    return "\n".join(
        [
            f"BACKLOG SPRINT PLANNING REQUEST for board '{board.name}'.",
            "This board has auto-organise backlog enabled. New backlog tickets have been "
            "created or updated, so ensure they are planned into a draft sprint once they "
            "have estimate_minutes and priority_score values.",
            "",
            "Workflow:",
            "1. Read the board backlog with /api/v1/agent/boards/<board_id>/tasks?is_backlog=true.",
            "2. Select estimated, unassigned backlog tickets using priority_score, dependencies, "
            "recent sprint velocity, and workstream balance.",
            "3. Reuse an existing empty draft sprint when one exists; otherwise create a draft sprint.",
            "4. Add selected tickets with POST /api/v1/agent/boards/<board_id>/sprints/<sprint_id>/tickets.",
            "5. Verify the selected tickets are attached and post the sprint plan rationale to board memory.",
            "",
            "Do not start the sprint. The lead or auto-advance sprint policy handles sprint start.",
            "If tickets still need estimates or priorities, notify @estimator or @priority-agent "
            "and return after a fresh read records that planning is waiting on those fields.",
        ]
    )


async def _select_backlog_tasks_missing_field(
    session: "AsyncSession",
    *,
    board_id: UUID,
    field: str,
) -> tuple[list[Task], int]:
    """Return (tasks_missing_field, skipped_count_with_value).

    ``field`` is either ``estimate_minutes`` or ``priority_score`` (when force=False).
    """
    from sqlalchemy import or_  # noqa: PLC0415

    stmt = (
        select(Task)
        .where(col(Task.board_id) == board_id)
        .where(
            or_(
                col(Task.status).in_(["triage", "backlog"]),
                col(Task.is_backlog).is_(True),
            ),
        )
    )
    rows = list((await session.exec(stmt)).all())
    if field == "estimate_minutes":
        missing = [t for t in rows if t.estimate_minutes is None]
    elif field == "priority_score":
        # priority_score=50 is the default — treat as "not yet prioritised".
        missing = [t for t in rows if t.priority_score in (None, 50)]
    else:
        missing = []
    return missing, len(rows) - len(missing)


@router.post("/backlog/estimate", response_model=_BacklogOrchestrationResponse)
async def dispatch_backlog_estimate(
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
    force: bool = Query(default=False),
) -> _BacklogOrchestrationResponse:
    """Dispatch the org estimator agent to fill estimate_minutes on backlog tasks.

    Idempotent: skips tasks that already have an estimate unless ``force=true``.
    Kicks off a single dispatch with all relevant tasks; the agent is expected
    to update each task via ``PATCH /tasks/{id}``.
    """
    from app.services.openclaw.planning_service import (  # noqa: PLC0415
        PlanningMessagingService,
    )

    if force:
        from sqlalchemy import or_  # noqa: PLC0415

        stmt = (
            select(Task)
            .where(col(Task.board_id) == board.id)
            .where(
                or_(
                    col(Task.status).in_(["triage", "backlog"]),
                    col(Task.is_backlog).is_(True),
                ),
            )
        )
        tasks = list((await session.exec(stmt)).all())
        skipped = 0
    else:
        tasks, skipped = await _select_backlog_tasks_missing_field(
            session,
            board_id=board.id,
            field="estimate_minutes",
        )
    if not tasks:
        return _BacklogOrchestrationResponse(
            dispatched=False,
            task_count=0,
            task_ids=[],
            skipped_existing=skipped,
            agent_session=None,
            reason="no_backlog_tasks_need_estimate",
        )
    prompt = _build_estimate_prompt(board, tasks)
    dispatcher = PlanningMessagingService(session)
    session_key = await dispatcher.dispatch_to_configured_org_agent(
        board=board,
        configured_agent_id=settings.org_estimator_agent_id,
        role_template="estimator",
        prompt=prompt,
        log_prefix="backlog.estimate",
        correlation_id=f"backlog.estimate:{board.id}",
    )
    if session_key is None:
        return _BacklogOrchestrationResponse(
            dispatched=False,
            task_count=len(tasks),
            task_ids=[t.id for t in tasks],
            skipped_existing=skipped,
            agent_session=None,
            reason="org_estimator_agent_unavailable",
        )
    record_activity(
        session,
        event_type="backlog_estimate_dispatched",
        message=f"Dispatched estimator to {len(tasks)} backlog tasks",
        board_id=board.id,
    )
    await session.commit()
    return _BacklogOrchestrationResponse(
        dispatched=True,
        task_count=len(tasks),
        task_ids=[t.id for t in tasks],
        skipped_existing=skipped,
        agent_session=session_key,
    )


@router.post("/backlog/prioritise", response_model=_BacklogOrchestrationResponse)
async def dispatch_backlog_prioritise(
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
    force: bool = Query(default=False),
) -> _BacklogOrchestrationResponse:
    """Dispatch the org prioritiser agent to fill priority + priority_score.

    Idempotent: skips tasks already prioritised (priority_score != 50) unless
    ``force=true``. Single dispatch covers the whole batch.
    """
    from app.services.openclaw.planning_service import (  # noqa: PLC0415
        PlanningMessagingService,
    )

    if force:
        from sqlalchemy import or_  # noqa: PLC0415

        stmt = (
            select(Task)
            .where(col(Task.board_id) == board.id)
            .where(
                or_(
                    col(Task.status).in_(["triage", "backlog"]),
                    col(Task.is_backlog).is_(True),
                ),
            )
        )
        tasks = list((await session.exec(stmt)).all())
        skipped = 0
    else:
        tasks, skipped = await _select_backlog_tasks_missing_field(
            session,
            board_id=board.id,
            field="priority_score",
        )
    if not tasks:
        return _BacklogOrchestrationResponse(
            dispatched=False,
            task_count=0,
            task_ids=[],
            skipped_existing=skipped,
            agent_session=None,
            reason="no_backlog_tasks_need_priority",
        )
    prompt = _build_prioritise_prompt(board, tasks)
    dispatcher = PlanningMessagingService(session)
    session_key = await dispatcher.dispatch_to_configured_org_agent(
        board=board,
        configured_agent_id=settings.org_prioritiser_agent_id,
        role_template="priority",
        prompt=prompt,
        log_prefix="backlog.prioritise",
        correlation_id=f"backlog.prioritise:{board.id}",
    )
    if session_key is None:
        return _BacklogOrchestrationResponse(
            dispatched=False,
            task_count=len(tasks),
            task_ids=[t.id for t in tasks],
            skipped_existing=skipped,
            agent_session=None,
            reason="org_prioritiser_agent_unavailable",
        )
    record_activity(
        session,
        event_type="backlog_prioritise_dispatched",
        message=f"Dispatched prioritiser to {len(tasks)} backlog tasks",
        board_id=board.id,
    )
    await session.commit()
    return _BacklogOrchestrationResponse(
        dispatched=True,
        task_count=len(tasks),
        task_ids=[t.id for t in tasks],
        skipped_existing=skipped,
        agent_session=session_key,
    )


class _BacklogOrganiseResponse(BaseModel):
    """Response from POST /backlog/organise."""

    estimate_dispatched: bool
    estimate_task_count: int
    estimate_agent_session: str | None
    prioritise_dispatched: bool
    prioritise_task_count: int
    prioritise_agent_session: str | None
    planner_dispatched: bool = False
    planner_agent_session: str | None = None
    sprint_id: UUID | None = None
    sprint_name: str | None = None
    sprint_task_ids: list[UUID] = []
    reason: str | None = None


async def _dispatch_organise_agents(
    session: "AsyncSession",
    *,
    board: Board,
    force: bool = False,
) -> tuple[bool, str | None, int, bool, str | None, int, bool, str | None]:
    """Dispatch estimate, prioritise, and planner agents for the board backlog.

    Returns (est_dispatched, est_session, est_count, pri_dispatched, pri_session,
    pri_count, planner_dispatched, planner_session).
    Swallows exceptions so callers (auto-trigger) do not fail on agent errors.
    """
    from app.services.openclaw.planning_service import (  # noqa: PLC0415
        PlanningMessagingService,
    )

    dispatcher = PlanningMessagingService(session)

    # --- estimate ---
    if force:
        from sqlalchemy import or_  # noqa: PLC0415

        stmt = (
            select(Task)
            .where(col(Task.board_id) == board.id)
            .where(
                or_(
                    col(Task.status).in_(["triage", "backlog"]),
                    col(Task.is_backlog).is_(True),
                ),
            )
        )
        est_tasks = list((await session.exec(stmt)).all())
    else:
        est_tasks, _ = await _select_backlog_tasks_missing_field(
            session, board_id=board.id, field="estimate_minutes"
        )

    est_dispatched = False
    est_session: str | None = None
    if est_tasks:
        prompt = _build_estimate_prompt(board, est_tasks)
        est_session = await dispatcher.dispatch_to_configured_org_agent(
            board=board,
            configured_agent_id=settings.org_estimator_agent_id,
            role_template="estimator",
            prompt=prompt,
            log_prefix="backlog.organise.estimate",
            correlation_id=f"backlog.organise.estimate:{board.id}",
        )
        est_dispatched = est_session is not None

    # --- prioritise ---
    if force:
        from sqlalchemy import or_  # noqa: PLC0415

        stmt = (
            select(Task)
            .where(col(Task.board_id) == board.id)
            .where(
                or_(
                    col(Task.status).in_(["triage", "backlog"]),
                    col(Task.is_backlog).is_(True),
                ),
            )
        )
        pri_tasks = list((await session.exec(stmt)).all())
    else:
        pri_tasks, _ = await _select_backlog_tasks_missing_field(
            session, board_id=board.id, field="priority_score"
        )

    pri_dispatched = False
    pri_session: str | None = None
    if pri_tasks:
        prompt = _build_prioritise_prompt(board, pri_tasks)
        pri_session = await dispatcher.dispatch_to_configured_org_agent(
            board=board,
            configured_agent_id=settings.org_prioritiser_agent_id,
            role_template="priority",
            prompt=prompt,
            log_prefix="backlog.organise.prioritise",
            correlation_id=f"backlog.organise.prioritise:{board.id}",
        )
        pri_dispatched = pri_session is not None

    plan_session = await dispatcher.dispatch_to_configured_org_agent(
        board=board,
        configured_agent_id=settings.org_planner_agent_id,
        role_template="planner",
        prompt=_build_planning_prompt(board),
        log_prefix="backlog.organise.plan",
        correlation_id=f"backlog.organise.plan:{board.id}",
    )
    plan_dispatched = plan_session is not None

    return (
        est_dispatched,
        est_session,
        len(est_tasks),
        pri_dispatched,
        pri_session,
        len(pri_tasks),
        plan_dispatched,
        plan_session,
    )


@router.post("/backlog/organise", response_model=_BacklogOrganiseResponse)
async def organise_backlog(
    board: Board = BOARD_ACTOR_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    actor: ActorContext = ACTOR_DEP,
    include_sprint: bool = Query(default=False),
    force: bool = Query(default=False),
    sprint_name: str | None = Query(default=None),
) -> _BacklogOrganiseResponse:
    """Dispatch estimate + prioritise agents over the backlog, and optionally build a sprint.

    Idempotent for agent dispatch (skips tasks with existing data unless ``force=true``).
    With ``include_sprint=true``, a draft sprint is created from the current backlog sorted by
    ``priority_score`` desc. The sprint name is auto-generated if not supplied.
    """
    (
        est_dispatched,
        est_session,
        est_count,
        pri_dispatched,
        pri_session,
        pri_count,
        planner_dispatched,
        planner_session,
    ) = await _dispatch_organise_agents(session, board=board, force=force)

    sprint_id: UUID | None = None
    sprint_out_name: str | None = None
    sprint_task_ids: list[UUID] = []

    if include_sprint:
        from sqlalchemy import or_  # noqa: PLC0415

        backlog_stmt = (
            select(Task)
            .where(col(Task.board_id) == board.id)
            .where(
                or_(
                    col(Task.status).in_(["triage", "backlog"]),
                    col(Task.is_backlog).is_(True),
                ),
            )
            .where(col(Task.sprint_id).is_(None))
            .order_by(col(Task.priority_score).desc(), col(Task.created_at).asc())
        )
        backlog_tasks = list((await session.exec(backlog_stmt)).all())

        if backlog_tasks:
            # Auto-name: Sprint N+1 based on total sprint count for this board.
            if sprint_name:
                auto_name = sprint_name
            else:
                existing_count = len(
                    (
                        await session.exec(select(Sprint).where(col(Sprint.board_id) == board.id))
                    ).all()
                )
                auto_name = f"Sprint {existing_count + 1}"

            sprint = Sprint(
                organization_id=board.organization_id,
                board_id=board.id,
                name=auto_name,
                slug=generate_slug(auto_name),
                status="draft",
                position=0,
                created_by_user_id=actor.user.id if actor.user else None,
            )
            session.add(sprint)
            await session.flush()

            for idx, task in enumerate(backlog_tasks):
                link = SprintTicket(sprint_id=sprint.id, task_id=task.id, position=idx)
                session.add(link)
                task.sprint_id = sprint.id
                task.updated_at = utcnow()
                session.add(task)

            sprint_id = sprint.id
            sprint_out_name = auto_name
            sprint_task_ids = [t.id for t in backlog_tasks]

    record_activity(
        session,
        event_type="backlog_organised",
        message=(
            f"Backlog organised: {est_count} tasks dispatched for estimation, "
            f"{pri_count} for prioritisation"
            + (f", sprint '{sprint_out_name}' created" if sprint_out_name else "")
        ),
        board_id=board.id,
    )
    await session.commit()

    reason: str | None = None
    if not est_dispatched and not pri_dispatched and not planner_dispatched and not sprint_id:
        reason = "no_tasks_need_processing"

    return _BacklogOrganiseResponse(
        estimate_dispatched=est_dispatched,
        estimate_task_count=est_count,
        estimate_agent_session=est_session,
        prioritise_dispatched=pri_dispatched,
        prioritise_task_count=pri_count,
        prioritise_agent_session=pri_session,
        planner_dispatched=planner_dispatched,
        planner_agent_session=planner_session,
        sprint_id=sprint_id,
        sprint_name=sprint_out_name,
        sprint_task_ids=sprint_task_ids,
        reason=reason,
    )


@router.post("/backlog/batch", response_model=list[TaskRead], status_code=status.HTTP_201_CREATED)
async def batch_create_backlog(
    payload: _BatchBacklogCreate,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    auth: "AuthContext" = USER_AUTH_DEP,
) -> list[TaskRead]:
    """Batch-create multiple backlog tasks (used by plan decompose flow)."""
    created: list[TaskRead] = []
    for item in payload.tickets:
        task = Task(
            board_id=board.id,
            title=item.title,
            description=item.description,
            status="backlog",
            priority=item.priority,
            priority_score=item.priority_score,
            estimate_minutes=item.estimate_minutes,
            assigned_agent_id=item.assigned_agent_id,
            created_by_user_id=auth.user.id if auth.user else None,
            is_backlog=True,
        )
        session.add(task)
        await session.flush()

        if item.sprint_id is not None:
            sprint = await session.get(Sprint, item.sprint_id)
            if sprint is not None and sprint.board_id == board.id:
                link = SprintTicket(sprint_id=sprint.id, task_id=task.id, position=0)
                session.add(link)
                task.sprint_id = sprint.id
                session.add(task)

        created.append(_task_to_read(task))

    record_activity(
        session,
        event_type="backlog_batch_created",
        message=f"{len(created)} backlog tasks created",
        board_id=board.id,
    )
    await session.commit()

    if board.auto_organise_backlog:
        try:
            await _dispatch_organise_agents(session, board=board)
            await session.commit()
        except Exception:
            logger.warning("backlog.auto_organise.failed board_id=%s", board.id)

    return created


# ---------------------------------------------------------------------------
# Velocity & Accuracy
# ---------------------------------------------------------------------------


class _SprintVelocityItem(BaseModel):
    sprint_id: str
    name: str
    committed_minutes: int | None
    completed_minutes: int | None
    actual_minutes: int | None
    estimation_accuracy: float | None  # completed / actual (closer to 1.0 = better)
    started_at: str | None
    completed_at: str | None


class _VelocityResponse(BaseModel):
    sprints: list[_SprintVelocityItem]
    rolling_velocity_minutes: int | None  # avg completed_minutes over last N sprints
    rolling_accuracy: float | None  # avg estimation_accuracy over last N sprints


@router.get("/velocity", response_model=_VelocityResponse)
async def board_velocity(
    board: Board = BOARD_ACTOR_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _actor: object = ACTOR_DEP,
    window: int = Query(default=5, ge=1, le=20),
) -> _VelocityResponse:
    """Return velocity and estimation accuracy for the last N completed sprints."""
    completed = (
        await session.exec(
            select(Sprint)
            .where(col(Sprint.board_id) == board.id)
            .where(col(Sprint.status) == "completed")
            .order_by(col(Sprint.completed_at).desc())
            .limit(window)
        )
    ).all()

    items: list[_SprintVelocityItem] = []
    velocity_values: list[int] = []
    accuracy_values: list[float] = []

    for sprint in reversed(list(completed)):
        acc: float | None = None
        if sprint.completed_minutes and sprint.actual_minutes:
            acc = round(sprint.completed_minutes / sprint.actual_minutes, 3)
        items.append(
            _SprintVelocityItem(
                sprint_id=str(sprint.id),
                name=sprint.name,
                committed_minutes=sprint.committed_minutes,
                completed_minutes=sprint.completed_minutes,
                actual_minutes=sprint.actual_minutes,
                estimation_accuracy=acc,
                started_at=sprint.started_at.isoformat() if sprint.started_at else None,
                completed_at=sprint.completed_at.isoformat() if sprint.completed_at else None,
            )
        )
        if sprint.completed_minutes is not None:
            velocity_values.append(sprint.completed_minutes)
        if acc is not None:
            accuracy_values.append(acc)

    rolling_velocity = (
        round(sum(velocity_values) / len(velocity_values)) if velocity_values else None
    )
    rolling_accuracy = (
        round(sum(accuracy_values) / len(accuracy_values), 3) if accuracy_values else None
    )

    return _VelocityResponse(
        sprints=items,
        rolling_velocity_minutes=rolling_velocity,
        rolling_accuracy=rolling_accuracy,
    )
