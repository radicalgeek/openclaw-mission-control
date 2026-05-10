from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services import board_agent_work_recovery as recovery
from app.services.openclaw.constants import OFFLINE_AFTER


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _patch_wake_services(
    monkeypatch: pytest.MonkeyPatch,
    wake_calls: list[dict[str, Any]],
) -> None:
    class _FakeDispatch:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def require_gateway_config_for_board(self, board: Board) -> tuple[Gateway, object]:
            gateway = await Gateway.objects.by_id(board.gateway_id).first(self.session)
            assert gateway is not None
            return gateway, object()

        async def try_wake_agent_session(self, **kwargs: Any) -> None:
            wake_calls.append(kwargs)
            return None

    class _FakeProvisioner:
        async def sync_gateway_agent_heartbeats(
            self,
            gateway: Gateway,
            agents: list[Agent],
        ) -> None:
            assert gateway.workspace_root
            assert agents

    monkeypatch.setattr(recovery, "GatewayDispatchService", _FakeDispatch)
    monkeypatch.setattr(recovery, "OpenClawGatewayProvisioner", _FakeProvisioner)


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_offline_agent_even_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    _patch_wake_services(monkeypatch, wake_calls)
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            agent_id = uuid4()
            task_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/openclaw",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                    context={"source_repo_url": "https://example.test/repo.git"},
                ),
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:worker:main",
                    wake_attempts=99,
                    last_seen_at=utcnow() - timedelta(hours=2),
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="Do the work",
                    status="in_progress",
                    assigned_agent_id=agent_id,
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert wake_calls
            assert wake_calls[0]["session_key"] == "agent:worker:main"
            assert wake_calls[0]["model"] == "azure-foundry/gpt-4.1"
            assert wake_calls[0]["reset_stuck_session"] is True
            assert "TASK WAKE" in wake_calls[0]["message"]
            assert "Repo URL: https://example.test/repo.git" in wake_calls[0]["message"]
            assert "CODE_WORKTREE_PATH:" in wake_calls[0]["message"]

            reloaded_agent = (
                await session.exec(select(Agent).where(col(Agent.id) == agent_id))
            ).one()
            assert reloaded_agent.last_wake_sent_at is not None
            assert reloaded_agent.checkin_deadline_at is not None
            assert reloaded_agent.wake_attempts == 100

            events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.assignee_woken"),
                )
            ).all()
            assert len(events) == 1
            assert events[0].message is not None
            assert "(active_work_recovery)" in events[0].message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_respects_pending_checkin_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    _patch_wake_services(monkeypatch, wake_calls)
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            agent_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/openclaw",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:worker:main",
                    checkin_deadline_at=utcnow() + timedelta(minutes=5),
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Do the work",
                    status="in_progress",
                    assigned_agent_id=agent_id,
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 0
            assert wake_calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_agent_with_assigned_inbox_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    _patch_wake_services(monkeypatch, wake_calls)
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            agent_id = uuid4()
            task_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/openclaw",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                    context={"source_repo_url": "https://example.test/repo.git"},
                ),
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:worker:main",
                    last_seen_at=utcnow() - timedelta(hours=2),
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="Pick up assigned work",
                    status="inbox",
                    assigned_agent_id=agent_id,
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert wake_calls
            assert "Status: inbox" in wake_calls[0]["message"]
            assert "Wake reason: assigned_inbox_work_recovery" in wake_calls[0]["message"]

            events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.assignee_woken"),
                )
            ).all()
            assert len(events) == 1
            assert "(assigned_inbox_work_recovery)" in (events[0].message or "")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_online_agent_with_stale_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    _patch_wake_services(monkeypatch, wake_calls)
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            agent_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            session.add(
                Gateway(
                    id=gateway_id,
                    organization_id=org_id,
                    name="gateway",
                    url="https://gateway.local",
                    workspace_root="/tmp/openclaw",
                ),
            )
            session.add(
                Board(
                    id=board_id,
                    organization_id=org_id,
                    name="board",
                    slug="board",
                    gateway_id=gateway_id,
                ),
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    openclaw_session_id="agent:worker:main",
                    last_seen_at=utcnow() - OFFLINE_AFTER - timedelta(minutes=1),
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Do the work",
                    status="in_progress",
                    assigned_agent_id=agent_id,
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert wake_calls
    finally:
        await engine.dispose()
