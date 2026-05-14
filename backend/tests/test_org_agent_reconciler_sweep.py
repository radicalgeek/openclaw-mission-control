# ruff: noqa: INP001
"""Org-agent stuck sweep regression tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.services.openclaw.org_agent_reconciler as org_agent_reconciler
from app.core.config import settings
from app.core.time import utcnow
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services.openclaw.constants import OFFLINE_AFTER
from app.services.openclaw.internal.session_keys import standalone_agent_session_key
from app.services.openclaw.lifecycle_queue import QueuedAgentLifecycleReconcile


@dataclass
class _FakeSession:
    exec_results: list[list[Agent]]
    added: list[Agent] = field(default_factory=list)
    commits: int = 0

    async def exec(self, _statement: Any) -> list[Agent]:
        if not self.exec_results:
            return []
        return self.exec_results.pop(0)

    def add(self, agent: Agent) -> None:
        self.added.append(agent)

    async def commit(self) -> None:
        self.commits += 1


def _stale_agent(
    *,
    status: str,
    wake_attempts: int,
    last_seen_at: Literal["stale"] | None = "stale",
    board_id: bool = False,
    openclaw_session: bool = False,
) -> Agent:
    now = utcnow()
    if last_seen_at == "stale":
        seen_at = now - OFFLINE_AFTER - timedelta(minutes=1)
    else:
        seen_at = None

    agent_id = uuid4()
    return Agent(
        id=uuid4(),
        name=f"{status}-agent",
        board_id=uuid4() if board_id else None,
        gateway_id=uuid4(),
        status=status,
        openclaw_session_id=f"agent:{agent_id}:main" if openclaw_session else None,
        updated_at=now - timedelta(seconds=settings.agent_stuck_provisioning_sweep_seconds + 1),
        last_seen_at=seen_at,
        wake_attempts=wake_attempts,
        lifecycle_generation=12,
    )


@pytest.mark.asyncio
async def test_reconcile_repairs_existing_standalone_agent_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        org = Organization(name="OAG")
        session.add(org)
        await session.flush()
        gateway = Gateway(
            organization_id=org.id,
            name="Primary Gateway",
            url="https://gateway.example",
            workspace_root="/workspace",
        )
        session.add(gateway)
        await session.flush()
        agent = Agent(
            name="Primary Gateway Gateway Agent",
            gateway_id=gateway.id,
            board_id=None,
            agent_type=AGENT_TYPE_STANDALONE,
            status="offline",
            openclaw_session_id=None,
            identity_profile={
                "role": "Gateway Agent",
                "role_template": "quality_reviewer",
                "communication_style": "chatty",
                "emoji": ":robot_face:",
            },
        )
        session.add(agent)
        await session.commit()

        outcome = await org_agent_reconciler.reconcile_org_standalone_agents(
            session,
            organization_id=org.id,
        )

        repaired = (await session.exec(select(Agent).where(Agent.id == agent.id))).one()

    assert outcome["quality_reviewer"] == "repaired"
    assert repaired.name == "Quality Reviewer"
    assert repaired.openclaw_session_id == standalone_agent_session_key(repaired.id)
    assert repaired.identity_profile == {
        "role": "Quality Reviewer",
        "role_template": "quality_reviewer",
        "communication_style": "direct, concise, practical",
        "emoji": ":white_check_mark:",
    }

    await engine.dispose()


@pytest.mark.asyncio
async def test_sweep_preserves_online_unseen_wake_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(status="online", wake_attempts=3, board_id=True)
    session = _FakeSession(exec_results=[[], [agent], [], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 1
    assert agent.wake_attempts == 3
    assert session.added == []
    assert session.commits == 0
    assert captured[0].agent_id == agent.id
    assert captured[0].generation == agent.lifecycle_generation


@pytest.mark.asyncio
async def test_sweep_skips_board_agent_with_session_for_work_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(
        status="online",
        wake_attempts=3,
        board_id=True,
        openclaw_session=True,
    )
    session = _FakeSession(exec_results=[[], [agent], [], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 0
    assert captured == []
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_sweep_preserves_updating_wake_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(status="updating", wake_attempts=4, board_id=True)
    session = _FakeSession(exec_results=[[], [], [agent], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 1
    assert agent.wake_attempts == 4
    assert session.added == []
    assert session.commits == 0
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_sweep_skips_offline_agent_that_exhausted_wake_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(
        status="offline",
        wake_attempts=settings.agent_max_wake_attempts,
        board_id=True,
    )
    session = _FakeSession(exec_results=[[], [], [], [agent]])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 0
    assert captured == []
    assert agent.wake_attempts == settings.agent_max_wake_attempts
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_sweep_skips_online_unseen_agent_that_exhausted_wake_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(
        status="online",
        wake_attempts=settings.agent_max_wake_attempts,
        board_id=True,
    )
    session = _FakeSession(exec_results=[[], [agent], [], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 0
    assert captured == []
    assert agent.wake_attempts == settings.agent_max_wake_attempts
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_sweep_skips_updating_agent_that_exhausted_wake_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(
        status="updating",
        wake_attempts=settings.agent_max_wake_attempts,
        board_id=True,
    )
    session = _FakeSession(exec_results=[[], [], [agent], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 0
    assert captured == []
    assert agent.wake_attempts == settings.agent_max_wake_attempts
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_sweep_skips_already_provisioned_non_board_agent_without_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[QueuedAgentLifecycleReconcile] = []
    agent = _stale_agent(status="online", wake_attempts=0, board_id=False)
    session = _FakeSession(exec_results=[[], [agent], [], []])

    monkeypatch.setattr(
        org_agent_reconciler,
        "enqueue_lifecycle_reconcile",
        lambda payload: captured.append(payload) or True,
    )

    count = await org_agent_reconciler.sweep_stuck_provisioning_agents(session)

    assert count == 0
    assert captured == []
    assert session.added == []
    assert session.commits == 0
