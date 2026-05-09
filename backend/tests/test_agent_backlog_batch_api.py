# ruff: noqa: INP001
"""Tests for agent-scoped backlog batch creation."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.tasks import TaskCreate


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: object) -> None:
        return None


def _board(board_id: UUID) -> Board:
    return Board(
        id=board_id,
        organization_id=uuid4(),
        gateway_id=uuid4(),
        name="Delivery Board",
        slug=f"delivery-{uuid4()}",
    )


def _agent_ctx(board_id: UUID) -> AgentAuthContext:
    return AgentAuthContext(
        actor_type="agent",
        agent=Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=uuid4(),
            name="Lead",
            is_board_lead=True,
        ),
    )


@pytest.mark.asyncio
async def test_agent_batch_create_backlog_tasks_links_plan_id() -> None:
    board_id = uuid4()
    plan_id = uuid4()
    session = _FakeSession()

    response = await agent_api.batch_create_backlog_tasks(
        payload=agent_api.AgentBacklogBatchCreate(
            tickets=[
                TaskCreate(
                    title="[API] Add auth guard",
                    description="## Context\nGuard production API routes.",
                    priority="high",
                    plan_id=plan_id,
                ),
                TaskCreate(
                    title="[Docs] Publish runbook",
                    description="## Context\nDocument the release path.",
                    priority="medium",
                    plan_id=plan_id,
                    estimate_minutes=45,
                ),
            ],
        ),
        board=_board(board_id),
        session=session,  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id),
    )

    tasks = [obj for obj in session.added if isinstance(obj, Task)]
    assert session.committed is True
    assert len(tasks) == 2
    assert all(task.status == "backlog" for task in tasks)
    assert all(task.is_backlog is True for task in tasks)
    assert all(task.plan_id == plan_id for task in tasks)
    assert [item.plan_id for item in response] == [plan_id, plan_id]
