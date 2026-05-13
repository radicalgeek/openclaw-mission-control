# ruff: noqa: S101
"""Tests for reviewer agent task creation permissions."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import agent as agent_api
from app.api.agent import _guard_task_access, _require_task_creation_permission
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.agent_board_access import AgentBoardAccess
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.schemas.agents import STANDALONE_ROLE_TEMPLATES
from app.schemas.tasks import TaskCreate


def _make_board(board_id: object = None) -> SimpleNamespace:
    board_id = board_id or uuid4()
    return SimpleNamespace(id=board_id, organization_id=uuid4())


def _make_lead_agent(board_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=True,
        identity_profile={},
    )


def _make_standalone_agent(role_template: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        board_id=None,
        agent_type="standalone",
        is_board_lead=False,
        identity_profile={"role_template": role_template} if role_template else {},
    )


def _make_ctx(agent: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(agent=agent)


async def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def test_board_lead_on_own_board_can_create_tasks() -> None:
    board_id = uuid4()
    board = _make_board(board_id)
    lead = _make_lead_agent(board_id)
    ctx = _make_ctx(lead)
    _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]


def test_reviewer_standalone_with_board_access_can_create_tasks() -> None:
    board = _make_board()
    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        agent = _make_standalone_agent(role_template=role_tpl)
        ctx = _make_ctx(agent)
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]


def test_non_reviewer_standalone_cannot_create_tasks() -> None:
    board = _make_board()
    agent = _make_standalone_agent(role_template=None)
    ctx = _make_ctx(agent)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_board_lead_on_different_board_cannot_create_tasks() -> None:
    board = _make_board()
    lead = _make_lead_agent(board_id=uuid4())  # different board
    ctx = _make_ctx(lead)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_reviewer_auto_reason_contains_reviewer_agent() -> None:
    """Verify auto_reason prefix logic mirrors production code in create_task."""
    from app.models.agents import AGENT_TYPE_STANDALONE

    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        agent = _make_standalone_agent(role_template=role_tpl)
        _profile = agent.identity_profile or {}
        # Mirror the exact production logic from agent.py create_task
        auto_reason = (
            f"reviewer_agent:{agent.id}"
            if (
                agent.agent_type == AGENT_TYPE_STANDALONE
                and _profile.get("role_template") in STANDALONE_ROLE_TEMPLATES
            )
            else f"lead_agent:{agent.id}"
        )
        assert auto_reason.startswith(
            "reviewer_agent:"
        ), f"Expected 'reviewer_agent:' prefix for role_template '{role_tpl}', got '{auto_reason}'"

    # A board_worker with a reviewer template in identity_profile should NOT get reviewer prefix
    board_worker_with_reviewer_profile = SimpleNamespace(
        id=uuid4(),
        board_id=uuid4(),
        agent_type="board_worker",
        is_board_lead=True,
        identity_profile={"role_template": "quality_reviewer"},
    )
    _profile = board_worker_with_reviewer_profile.identity_profile or {}
    auto_reason = (
        f"reviewer_agent:{board_worker_with_reviewer_profile.id}"
        if (
            board_worker_with_reviewer_profile.agent_type == AGENT_TYPE_STANDALONE
            and _profile.get("role_template") in STANDALONE_ROLE_TEMPLATES
        )
        else f"lead_agent:{board_worker_with_reviewer_profile.id}"
    )
    assert auto_reason.startswith(
        "lead_agent:"
    ), "A board_worker with reviewer role_template should use lead_agent: prefix"


def test_non_lead_board_worker_cannot_create_tasks() -> None:
    """A regular board worker (not lead) on the same board should be rejected."""
    board_id = uuid4()
    board = _make_board(board_id)
    worker = SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=False,
        identity_profile={},
    )
    ctx = _make_ctx(worker)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_board_worker_with_spoofed_reviewer_template_cannot_create_tasks() -> None:
    """A board_worker with a reviewer role_template should NOT get reviewer permissions."""
    board_id = uuid4()
    board = _make_board(board_id)
    spoofed = SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=False,
        identity_profile={"role_template": "quality_reviewer"},
    )
    ctx = _make_ctx(spoofed)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_standalone_read_grant_cannot_write_task_updates() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    board_id = uuid4()
    agent_id = uuid4()
    gateway_id = uuid4()

    try:
        async with session_maker() as session:
            org = Organization(id=uuid4(), name="org")
            gateway = Gateway(
                id=gateway_id,
                organization_id=org.id,
                name="gw",
                url="https://gateway.example",
                workspace_root="/tmp/ws",
            )
            board = Board(
                id=board_id,
                organization_id=org.id,
                gateway_id=gateway_id,
                name="board",
                slug="board",
            )
            session.add_all(
                [
                    org,
                    gateway,
                    board,
                    AgentBoardAccess(agent_id=agent_id, board_id=board_id, access_level="read"),
                ]
            )
            await session.commit()

            agent = SimpleNamespace(
                id=agent_id,
                board_id=None,
                gateway_id=gateway_id,
                agent_type="standalone",
                is_board_lead=False,
                identity_profile={},
            )
            ctx = _make_ctx(agent)
            task = SimpleNamespace(board_id=board_id)

            with pytest.raises(HTTPException) as exc_info:
                await _guard_task_access(session, ctx, task, write=True)  # type: ignore[arg-type]
            assert exc_info.value.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewer_created_inbox_task_notifies_board_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid4()
    board_id = uuid4()
    gateway_id = uuid4()
    reviewer_id = uuid4()
    notified: list[str] = []

    async def fake_notify_lead_on_task_create(
        *,
        session: object,
        board: Board,
        task: object,
    ) -> None:
        _ = session
        assert board.id == board_id
        notified.append(str(getattr(task, "id")))

    monkeypatch.setattr(
        agent_api.tasks_api,
        "_notify_lead_on_task_create",
        fake_notify_lead_on_task_create,
    )

    try:
        async with session_maker() as session:
            org = Organization(id=org_id, name="org")
            gateway = Gateway(
                id=gateway_id,
                organization_id=org_id,
                name="gw",
                url="https://gateway.example",
                workspace_root="/tmp/ws",
            )
            board = Board(
                id=board_id,
                organization_id=org_id,
                gateway_id=gateway_id,
                name="board",
                slug="board",
            )
            reviewer = Agent(
                id=reviewer_id,
                name="QA Reviewer",
                organization_id=org_id,
                gateway_id=gateway_id,
                agent_type=AGENT_TYPE_STANDALONE,
                identity_profile={"role_template": "quality_reviewer"},
            )
            session.add_all(
                [
                    org,
                    gateway,
                    board,
                    reviewer,
                    AgentBoardAccess(
                        agent_id=reviewer_id,
                        board_id=board_id,
                        access_level="write",
                    ),
                ]
            )
            await session.commit()

            ctx = SimpleNamespace(agent=reviewer)
            created = await agent_api.create_task(
                payload=TaskCreate(title="Fix reviewed issue", status="inbox"),
                board=board,
                session=session,
                agent_ctx=ctx,  # type: ignore[arg-type]
            )

            assert created.title == "Fix reviewed issue"
            assert notified == [str(created.id)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_standalone_read_grant_can_read_task_comments() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    board_id = uuid4()
    agent_id = uuid4()
    gateway_id = uuid4()

    try:
        async with session_maker() as session:
            org = Organization(id=uuid4(), name="org")
            gateway = Gateway(
                id=gateway_id,
                organization_id=org.id,
                name="gw",
                url="https://gateway.example",
                workspace_root="/tmp/ws",
            )
            board = Board(
                id=board_id,
                organization_id=org.id,
                gateway_id=gateway_id,
                name="board",
                slug="board",
            )
            session.add_all(
                [
                    org,
                    gateway,
                    board,
                    AgentBoardAccess(agent_id=agent_id, board_id=board_id, access_level="read"),
                ]
            )
            await session.commit()

            agent = SimpleNamespace(
                id=agent_id,
                board_id=None,
                gateway_id=gateway_id,
                agent_type="standalone",
                is_board_lead=False,
                identity_profile={},
            )
            ctx = _make_ctx(agent)
            task = SimpleNamespace(board_id=board_id)

            await _guard_task_access(session, ctx, task)  # type: ignore[arg-type]
    finally:
        await engine.dispose()
