# ruff: noqa: INP001
"""Schema and model tests for the graduation workflow field additions.

Covers:
- Plan.decomposition_target (default + explicit values)
- Task.plan_id (FK to plans.id)
- Board.context (JSON blob round-trip)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.boards import Board
from app.models.organizations import Organization
from app.models.plans import Plan
from app.models.tasks import Task
from app.schemas.boards import BoardCreate, BoardUpdate
from app.schemas.plans import VALID_DECOMPOSITION_TARGETS, PlanCreate, PlanRead
from app.schemas.tasks import TaskRead


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


# ── Plan.decomposition_target ────────────────────────────────────────────────


def test_plan_create_defaults_decomposition_target_to_org_triager() -> None:
    payload = PlanCreate(title="My plan")
    assert payload.decomposition_target == "org_triager"


def test_plan_create_accepts_org_planner_target() -> None:
    payload = PlanCreate(title="Graduation brief", decomposition_target="org_planner")
    assert payload.decomposition_target == "org_planner"


def test_plan_create_accepts_org_triager_target() -> None:
    payload = PlanCreate(title="Graduation brief", decomposition_target="org_triager")
    assert payload.decomposition_target == "org_triager"


def test_valid_decomposition_targets_set() -> None:
    assert VALID_DECOMPOSITION_TARGETS == frozenset({"board_lead", "org_planner", "org_triager"})


@pytest.mark.asyncio
async def test_plan_persists_decomposition_target() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            session.add(Organization(id=org_id, name=f"org-{org_id}"))
            session.add(Board(id=board_id, organization_id=org_id, name="b", slug="b"))

            default_plan_id = uuid4()
            org_plan_id = uuid4()
            session.add(Plan(id=default_plan_id, board_id=board_id, title="default", slug="d"))
            session.add(
                Plan(
                    id=org_plan_id,
                    board_id=board_id,
                    title="org",
                    slug="o",
                    decomposition_target="org_planner",
                )
            )
            await session.commit()

            default_plan = await session.get(Plan, default_plan_id)
            org_plan = await session.get(Plan, org_plan_id)
            assert default_plan is not None
            assert default_plan.decomposition_target == "org_triager"
            assert org_plan is not None
            assert org_plan.decomposition_target == "org_planner"
    finally:
        await engine.dispose()


def test_plan_read_exposes_decomposition_target() -> None:
    fields = PlanRead.model_fields
    assert "decomposition_target" in fields


# ── Task.plan_id ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_plan_id_links_to_plan() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            plan_id = uuid4()
            task_id = uuid4()

            session.add(Organization(id=org_id, name=f"org-{org_id}"))
            session.add(Board(id=board_id, organization_id=org_id, name="b", slug="b"))
            session.add(Plan(id=plan_id, board_id=board_id, title="t", slug="s"))
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="committed-from-plan",
                    plan_id=plan_id,
                )
            )
            await session.commit()

            task = await session.get(Task, task_id)
            assert task is not None
            assert task.plan_id == plan_id

            # Tasks unrelated to plans keep plan_id None
            other_task_id = uuid4()
            session.add(Task(id=other_task_id, board_id=board_id, title="orphan"))
            await session.commit()
            other_task = await session.get(Task, other_task_id)
            assert other_task is not None
            assert other_task.plan_id is None

            # Querying tasks by plan_id returns only the linked task
            stmt = select(Task).where(Task.plan_id == plan_id)
            result = await session.exec(stmt)
            linked_tasks = result.all()
            assert len(linked_tasks) == 1
            assert linked_tasks[0].id == task_id
    finally:
        await engine.dispose()


def test_task_read_exposes_plan_id() -> None:
    fields = TaskRead.model_fields
    assert "plan_id" in fields


# ── Board.context ────────────────────────────────────────────────────────────


def test_board_create_accepts_context_json() -> None:
    payload = BoardCreate(
        name="Graduation Board",
        slug="graduation-board",
        description="App graduation",
        gateway_id=uuid4(),
        context={
            "app_id": "cargoflights",
            "graduation_id": str(uuid4()),
            "production_repo_url": "https://dev.azure.com/oag/_git/cargoflights",
        },
    )
    assert payload.context is not None
    assert payload.context["app_id"] == "cargoflights"


def test_board_create_defaults_context_to_none() -> None:
    payload = BoardCreate(
        name="Plain Board",
        slug="plain",
        description="Standard board.",
        gateway_id=uuid4(),
    )
    assert payload.context is None


def test_board_update_supports_context_patch() -> None:
    patch = BoardUpdate(context={"graduation_status": "in_progress"})
    assert patch.context == {"graduation_status": "in_progress"}


@pytest.mark.asyncio
async def test_board_context_round_trips_through_persistence() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            board_id = uuid4()
            ctx = {
                "app_id": "cargoflights",
                "manifest": {"name": "CargoFlights", "stack": "fastapi+react"},
                "spec_excerpt": "Move flight booking to production.",
            }

            session.add(Organization(id=org_id, name=f"org-{org_id}"))
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="Graduation",
                    slug="grad",
                    context=ctx,
                )
            )
            await session.commit()

            board = await session.get(Board, board_id)
            assert board is not None
            assert board.context == ctx
            assert isinstance(board.context, dict)
            assert board.context["manifest"]["stack"] == "fastapi+react"
    finally:
        await engine.dispose()
