"""Sprint CRUD, lifecycle, ticket management, and backlog API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.boards import Board
from app.models.sprints import Sprint, SprintTicket
from app.models.tasks import Task
from app.schemas.common import OkResponse
from app.schemas.sprints import (
    SprintCreate,
    SprintRead,
    SprintTicketAddRequest,
    SprintTicketRead,
    SprintTicketReorderRequest,
    SprintUpdate,
)
from app.schemas.tasks import TaskCreate, TaskRead
from app.services.activity_log import record_activity
from app.services.planning import generate_slug

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext

router = APIRouter(prefix="/boards/{board_id}", tags=["sprints"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
BOARD_READ_DEP = Depends(get_board_for_user_read)
BOARD_WRITE_DEP = Depends(get_board_for_user_write)
USER_AUTH_DEP = Depends(require_user_auth)


# ---------------------------------------------------------------------------
# Batch backlog schemas (must be defined before routes that use them)
# ---------------------------------------------------------------------------


class _BatchBacklogTicket(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
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
    """Return (total_tickets, done_tickets) for a sprint."""
    tickets = (
        await session.exec(
            select(SprintTicket).where(col(SprintTicket.sprint_id) == sprint_id)
        )
    ).all()
    total = len(tickets)
    done = 0
    for ticket in tickets:
        task = await session.get(Task, ticket.task_id)
        if task is not None and task.status == "done":
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
        status=sprint.status,  # type: ignore[arg-type]
        started_at=sprint.started_at,
        completed_at=sprint.completed_at,
        created_by_user_id=sprint.created_by_user_id,
        created_at=sprint.created_at,
        updated_at=sprint.updated_at,
        ticket_count=ticket_count,
        tickets_done_count=tickets_done_count,
    )


def _task_to_read(task: Task) -> TaskRead:
    return TaskRead(
        id=task.id,
        board_id=task.board_id,
        title=task.title,
        description=task.description,
        status=task.status,  # type: ignore[arg-type]
        priority=task.priority,
        due_at=task.due_at,
        assigned_agent_id=task.assigned_agent_id,
        depends_on_task_ids=[],
        tag_ids=[],
        created_by_user_id=task.created_by_user_id,
        in_progress_at=task.in_progress_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        thread_id=task.thread_id,
        is_backlog=task.is_backlog,
        sprint_id=task.sprint_id,
    )


# ---------------------------------------------------------------------------
# Sprint CRUD
# ---------------------------------------------------------------------------


@router.get("/sprints", response_model=list[SprintRead])
async def list_sprints(
    board: Board = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    auth: "AuthContext" = USER_AUTH_DEP,
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
        created_by_user_id=auth.user.id if auth.user else None,
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
    board: Board = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed or cancelled sprints cannot be edited.",
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
    board: Board = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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

    out: list[TaskRead] = []
    for ticket in tickets:
        task = await session.get(Task, ticket.task_id)
        if task is None:
            continue
        if ticket_status and task.status != ticket_status:
            continue
        out.append(_task_to_read(task))
    return out


@router.post("/sprints/{sprint_id}/tickets", response_model=list[SprintTicketRead])
async def add_sprint_tickets(
    sprint_id: UUID,
    payload: SprintTicketAddRequest,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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
            await session.exec(
                select(SprintTicket).where(col(SprintTicket.task_id) == task_id)
            )
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
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
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
    board: Board = BOARD_READ_DEP,
    session: "AsyncSession" = SESSION_DEP,
    _auth: "AuthContext" = USER_AUTH_DEP,
    sprint_id: UUID | None = Query(default=None),
    unassigned: bool = Query(default=False),
) -> list[TaskRead]:
    """List all backlog tasks for a board, filterable by sprint or unassigned."""
    query = (
        select(Task)
        .where(col(Task.board_id) == board.id)
        .where(col(Task.is_backlog).is_(True))
        .order_by(col(Task.created_at).desc())
    )
    if sprint_id is not None:
        query = query.where(col(Task.sprint_id) == sprint_id)
    elif unassigned:
        query = query.where(col(Task.sprint_id).is_(None))

    tasks = (await session.exec(query)).all()
    return [_task_to_read(t) for t in tasks]


@router.post("/backlog", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_backlog_task(
    payload: TaskCreate,
    board: Board = BOARD_WRITE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    auth: "AuthContext" = USER_AUTH_DEP,
) -> TaskRead:
    """Create a task directly in the backlog (is_backlog=True)."""
    task = Task(
        board_id=board.id,
        title=payload.title,
        description=payload.description,
        status="inbox",
        priority=payload.priority,
        due_at=payload.due_at,
        assigned_agent_id=payload.assigned_agent_id,
        created_by_user_id=payload.created_by_user_id or (auth.user.id if auth.user else None),
        is_backlog=True,
    )
    session.add(task)
    record_activity(
        session,
        event_type="backlog_task_created",
        message=f"Backlog task created: {payload.title}",
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(task)
    return _task_to_read(task)


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
            status="inbox",
            priority=item.priority,
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
    return created
