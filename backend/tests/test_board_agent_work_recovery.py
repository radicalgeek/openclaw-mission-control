from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.agent_tokens import hash_agent_token, verify_agent_token
from app.core.time import utcnow
from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.tasks import Task
from app.services import board_agent_work_recovery as recovery
from app.services.openclaw.constants import OFFLINE_AFTER
from app.services.openclaw.gateway_rpc import OpenClawGatewayError


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
    *,
    wake_errors: list[OpenClawGatewayError | None] | None = None,
    registrations: list[dict[str, Any]] | None = None,
    heartbeat_patches: (
        list[list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]]] | None
    ) = None,
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
            if wake_errors:
                return wake_errors.pop(0)
            return None

    class _FakeControlPlane:
        def __init__(self, config: object) -> None:
            self.config = config

        async def upsert_agent(self, registration: object) -> None:
            if registrations is not None:
                registrations.append(
                    {
                        "agent_id": registration.agent_id,
                        "name": registration.name,
                        "workspace_path": registration.workspace_path,
                        "model": registration.model,
                    }
                )

        async def patch_agent_heartbeats(
            self,
            entries: list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]],
        ) -> None:
            if heartbeat_patches is not None:
                heartbeat_patches.append(entries)

    monkeypatch.setattr(recovery, "GatewayDispatchService", _FakeDispatch)
    monkeypatch.setattr(recovery, "OpenClawGatewayControlPlane", _FakeControlPlane)


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
            assert wake_calls[0]["model"] is None
            assert wake_calls[0]["clear_model_override"] is True
            assert wake_calls[0]["reset_stuck_session"] is True
            assert "TASK WAKE" in wake_calls[0]["message"]
            assert "Repo URL: https://example.test/repo.git" in wake_calls[0]["message"]
            assert "CODE_WORKTREE_PATH:" in wake_calls[0]["message"]

            reloaded_agent = (
                await session.exec(select(Agent).where(col(Agent.id) == agent_id))
            ).one()
            assert reloaded_agent.last_wake_sent_at is not None
            assert reloaded_agent.checkin_deadline_at is not None
            assert reloaded_agent.status == "online"
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
            comments = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.comment"),
                )
            ).all()
            assert comments == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_respects_pending_checkin_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    heartbeat_patches: list[
        list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]]
    ] = []
    _patch_wake_services(monkeypatch, wake_calls, heartbeat_patches=heartbeat_patches)
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
            assert heartbeat_patches == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_after_checkin_deadline_expires(
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
            now = utcnow()
            session.add(
                Agent(
                    id=agent_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    openclaw_session_id="agent:worker:main",
                    last_seen_at=now,
                    checkin_deadline_at=now - timedelta(minutes=1),
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Do the work",
                    status="in_progress",
                    assigned_agent_id=agent_id,
                    in_progress_at=now - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert len(wake_calls) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_refreshes_runtime_agent_then_retries_if_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake_calls: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    heartbeat_patches: list[
        list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]]
    ] = []
    _patch_wake_services(
        monkeypatch,
        wake_calls,
        wake_errors=[
            OpenClawGatewayError('Agent "mc-worker" no longer exists in configuration'),
            None,
        ],
        registrations=registrations,
        heartbeat_patches=heartbeat_patches,
    )
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
                    title="Do the work",
                    status="in_progress",
                    assigned_agent_id=agent_id,
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert len(wake_calls) == 2
            expected_registration = {
                "agent_id": "worker",
                "name": "worker",
                "workspace_path": "/tmp/openclaw/workspace-worker",
                "model": {"primary": "azure-foundry/kimi-k2-6"},
            }
            assert registrations == [expected_registration]
            assert len(heartbeat_patches) == 1
            assert heartbeat_patches[0] == [
                (
                    "worker",
                    "/tmp/openclaw/workspace-worker",
                    heartbeat_patches[0][0][2],
                    {"primary": "azure-foundry/kimi-k2-6"},
                )
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_does_not_refresh_runtime_model_policy_before_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery.settings,
        "agent_model_routing",
        json.dumps(
            {
                "roles": {
                    "developer": {
                        "primary": "azure-foundry/kimi-k2-6",
                        "fallbacks": ["azure-foundry/deepseek-v3"],
                    },
                },
            }
        ),
    )
    wake_calls: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    heartbeat_patches: list[
        list[tuple[str, str, dict[str, Any], dict[str, object] | str | None]]
    ] = []
    _patch_wake_services(
        monkeypatch,
        wake_calls,
        registrations=registrations,
        heartbeat_patches=heartbeat_patches,
    )
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
                ),
            )
            session.add(
                Agent(
                    id=agent_id,
                    name="Developer Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:developer-agent:main",
                    identity_profile={"role_template": "developer"},
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
            assert registrations == []
            assert heartbeat_patches == []
            assert wake_calls[0]["model"] is None
            assert wake_calls[0]["clear_model_override"] is True
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
            reloaded_agent = (
                await session.exec(select(Agent).where(col(Agent.id) == agent_id))
            ).one()
            assert reloaded_agent.status == "online"

            events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.assignee_woken"),
                )
            ).all()
            assert len(events) == 1
            assert "(assigned_inbox_work_recovery)" in (events[0].message or "")
            comments = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.task_id) == task_id)
                    .where(col(ActivityEvent.event_type) == "task.comment"),
                )
            ).all()
            assert comments == []
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
            reloaded_agent = (
                await session.exec(select(Agent).where(col(Agent.id) == agent_id))
            ).one()
            assert reloaded_agent.status == "online"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_stale_merge_agent_for_board_work(
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
            worker_id = uuid4()
            merger_id = uuid4()
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
                    id=worker_id,
                    name="worker",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    openclaw_session_id="agent:worker:main",
                    last_seen_at=utcnow(),
                ),
            )
            session.add(
                Agent(
                    id=merger_id,
                    name="Merge Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:merge:main",
                    identity_profile={"role_template": "merger"},
                    last_seen_at=utcnow() - timedelta(hours=2),
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Developer work",
                    status="review",
                    assigned_agent_id=worker_id,
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert len(wake_calls) == 1
            assert wake_calls[0]["session_key"] == "agent:merge:main"
            assert wake_calls[0]["reset_session"] is True
            assert "MERGE WATCH WAKE" in wake_calls[0]["message"]
            assert "inspect all tasks currently in `review`" in wake_calls[0]["message"]
            assert "custom fields are missing" in wake_calls[0]["message"]
            assert "read the current TOOLS.md" in wake_calls[0]["message"]
            assert "current X-Agent-Token" in wake_calls[0]["message"]
            assert "If Git reports conflicts, resolve them" in wake_calls[0]["message"]
            assert "push the updated mainline branch to origin" in wake_calls[0]["message"]
            assert "pushed remote branch and SHA" in wake_calls[0]["message"]
            assert "A Git conflict alone is not a blocker" in wake_calls[0]["message"]
            assert '{"status":"done","comment":"<merge SHA' in wake_calls[0]["message"]
            assert 'tags ["chat","merge_blocker"]' in wake_calls[0]["message"]
            assert "Do not use OpenClaw message/channel-send tools" in wake_calls[0]["message"]
            assert "CODE_WORKTREE_PATH: /tmp/openclaw/shared-src/boards/board/worktrees/merge" in (
                wake_calls[0]["message"]
            )
            reloaded_merger = (
                await session.exec(select(Agent).where(col(Agent.id) == merger_id))
            ).one()
            assert reloaded_merger.status == "online"

            events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.board_id) == board_id)
                    .where(col(ActivityEvent.event_type) == "board.merge_agent_woken"),
                )
            ).all()
            assert len(events) == 1
            assert "review tasks: 1" in (events[0].message or "")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_stale_board_lead_for_orchestration(
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
            lead_id = uuid4()
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
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="offline",
                    openclaw_session_id="agent:lead:main",
                    is_board_lead=True,
                    wake_attempts=99,
                    last_seen_at=utcnow() - timedelta(hours=2),
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Ready work",
                    status="inbox",
                ),
            )
            session.add(
                Task(
                    board_id=board_id,
                    title="Active work",
                    status="in_progress",
                    in_progress_at=utcnow() - timedelta(minutes=30),
                ),
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert len(wake_calls) == 1
            assert wake_calls[0]["session_key"] == "agent:lead:main"
            assert wake_calls[0]["reset_session"] is True
            assert wake_calls[0]["reset_stuck_session"] is True
            assert "BOARD LEAD WATCH WAKE" in wake_calls[0]["message"]
            assert "Inbox tasks: 1" in wake_calls[0]["message"]
            assert "Active assigned tasks: 1" in wake_calls[0]["message"]
            assert "read the current TOOLS.md" in wake_calls[0]["message"]
            assert "current X-Agent-Token" in wake_calls[0]["message"]
            assert "Do not ask the operator whether to proceed" in wake_calls[0]["message"]
            assert "Do not mark review tasks `done` before the code is merged" in (
                wake_calls[0]["message"]
            )
            assert "accept the merge evidence" in wake_calls[0]["message"]
            assert "wake or mention the merge agent" in wake_calls[0]["message"]
            assert "do not block solely because the lead workspace" in wake_calls[0]["message"]
            assert "read recent board chat for merge_blocker messages" in wake_calls[0]["message"]
            assert "CODE_WORKTREE_PATH:" in wake_calls[0]["message"]

            reloaded_lead = (
                await session.exec(select(Agent).where(col(Agent.id) == lead_id))
            ).one()
            assert reloaded_lead.status == "online"
            assert reloaded_lead.wake_attempts == 100

            events = (
                await session.exec(
                    select(ActivityEvent)
                    .where(col(ActivityEvent.board_id) == board_id)
                    .where(col(ActivityEvent.event_type) == "board.lead_woken"),
                )
            ).all()
            assert len(events) == 1
            assert "Inbox tasks: 1" in (events[0].message or "")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_work_recovery_wakes_lead_for_new_review_escalation(
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
            lead_id = uuid4()
            task_id = uuid4()
            now = utcnow()
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
                    id=lead_id,
                    name="Lead Agent",
                    board_id=board_id,
                    gateway_id=gateway_id,
                    status="online",
                    openclaw_session_id="agent:lead:main",
                    is_board_lead=True,
                    last_seen_at=now,
                    last_wake_sent_at=now - timedelta(minutes=1),
                    checkin_deadline_at=now + timedelta(minutes=9),
                ),
            )
            session.add(
                Task(
                    id=task_id,
                    board_id=board_id,
                    title="Deploy-time schema migrations",
                    status="review",
                    updated_at=now,
                ),
            )
            session.add(
                ActivityEvent(
                    event_type="task.comment",
                    task_id=task_id,
                    board_id=board_id,
                    created_at=now,
                    message=(
                        "Merge agent resolved integration conflicts. Commit a1ab90e is now "
                        "in main via merge commit 3bbf180. @lead verify CI before marking done."
                    ),
                )
            )
            await session.commit()

            woken = await recovery.wake_stale_board_agents_with_active_work(session)

            assert woken == 1
            assert len(wake_calls) == 1
            message = wake_calls[0]["message"]
            assert wake_calls[0]["session_key"] == "agent:lead:main"
            assert wake_calls[0]["reset_session"] is True
            assert "Lead review actions:" in message
            assert f"Task {task_id}" in message
            assert "Deploy-time schema migrations" in message
            assert "a1ab90e is now in main via merge commit 3bbf180" in message
            task_path = f"/api/v1/agent/boards/{board_id}/tasks/{task_id}"
            assert "exact update endpoint: PATCH" in message
            assert "exact comments endpoint: GET" in message
            assert task_path in message
            assert f"{task_path}/comments" in message
            assert "do not reconstruct them from memory" in message
            assert "do not omit the `/tasks/` path segment" in message

            reloaded_lead = (
                await session.exec(select(Agent).where(col(Agent.id) == lead_id))
            ).one()
            assert reloaded_lead.checkin_deadline_at is not None
            assert reloaded_lead.checkin_deadline_at > now + timedelta(minutes=5)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_stale_workspace_token_rotates_and_rewrites_agent_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle_calls: list[dict[str, Any]] = []

    async def _fake_read_workspace_auth_token(**kwargs: Any) -> str:
        return "stale-token"

    class _FakeProvisioner:
        async def apply_agent_lifecycle(self, **kwargs: Any) -> None:
            lifecycle_calls.append(kwargs)

    async def _fake_fetch_db_template_overrides(*args: Any, **kwargs: Any) -> dict[str, str]:
        return {}

    monkeypatch.setattr(recovery, "_read_workspace_auth_token", _fake_read_workspace_auth_token)
    monkeypatch.setattr(recovery, "OpenClawGatewayProvisioner", _FakeProvisioner)
    monkeypatch.setattr(recovery, "fetch_db_template_overrides", _fake_fetch_db_template_overrides)

    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            org_id = uuid4()
            gateway_id = uuid4()
            board_id = uuid4()
            agent_id = uuid4()
            session.add(Organization(id=org_id, name="org"))
            gateway = Gateway(
                id=gateway_id,
                organization_id=org_id,
                name="gateway",
                url="https://gateway.local",
                workspace_root="/tmp/openclaw",
            )
            board = Board(
                id=board_id,
                organization_id=org_id,
                name="board",
                slug="board",
                gateway_id=gateway_id,
            )
            agent = Agent(
                id=agent_id,
                name="Lead Agent",
                board_id=board_id,
                gateway_id=gateway_id,
                status="online",
                openclaw_session_id="agent:lead:main",
                agent_token_hash=hash_agent_token("current-token"),
            )
            session.add(gateway)
            session.add(board)
            session.add(agent)
            await session.commit()

            refreshed = await recovery._refresh_stale_agent_workspace_token(
                session=session,
                gateway=gateway,
                board=board,
                agent=agent,
            )

            assert refreshed is True
            assert len(lifecycle_calls) == 1
            call = lifecycle_calls[0]
            assert call["action"] == "update"
            assert call["wake"] is False
            assert call["reset_session"] is False
            assert call["auth_token"] != "stale-token"
            assert call["auth_token"] != "current-token"
            assert verify_agent_token(call["auth_token"], agent.agent_token_hash or "")
    finally:
        await engine.dispose()
