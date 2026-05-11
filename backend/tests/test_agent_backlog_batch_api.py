# ruff: noqa: INP001
"""Tests for agent-scoped backlog batch creation."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.api import agent as agent_api
from app.core.agent_auth import AgentAuthContext
from app.models.agents import Agent
from app.models.boards import Board
from app.models.tasks import Task
from app.schemas.tasks import TaskCreate
from app.schemas.tasks import TaskUpdate


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
async def test_agent_task_list_forwards_backlog_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    board_id = uuid4()
    captured: dict[str, Any] = {}

    async def fake_guard(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_list_tasks(**kwargs: object) -> object:
        captured.update(kwargs)
        return {"items": [], "total": 0}

    monkeypatch.setattr(agent_api, "_guard_board_access", fake_guard)
    monkeypatch.setattr(agent_api.tasks_api, "list_tasks", fake_list_tasks)

    result = await agent_api.list_tasks(
        filters=agent_api.AgentTaskListFilters(is_backlog=True),
        board=_board(board_id),
        session=object(),  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id),
    )

    assert result == {"items": [], "total": 0}
    assert captured["is_backlog"] is True
    assert captured["status_filter"] is None


@pytest.mark.asyncio
async def test_agent_task_detail_returns_single_task(monkeypatch: pytest.MonkeyPatch) -> None:
    board_id = uuid4()
    task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Implement work",
        description="Do the thing",
        status="in_progress",
    )
    captured: dict[str, Any] = {}

    async def fake_guard(*_args: object, **kwargs: object) -> None:
        captured["write"] = kwargs["write"]

    async def fake_task_read_response(*args: object, **kwargs: object) -> object:
        captured["session"] = args[0]
        captured.update(kwargs)
        return {"id": str(task.id), "title": task.title}

    monkeypatch.setattr(agent_api, "_guard_task_access", fake_guard)
    monkeypatch.setattr(agent_api.tasks_api, "_task_read_response", fake_task_read_response)

    result = await agent_api.get_task(
        task=task,
        session=object(),  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id),
    )

    assert result == {"id": str(task.id), "title": task.title}
    assert captured["write"] is False
    assert captured["session"] is not None
    assert captured["task"] is task
    assert captured["board_id"] == board_id


@pytest.mark.asyncio
async def test_agent_task_status_endpoint_forwards_to_task_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board_id = uuid4()
    task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Implement work",
        status="in_progress",
    )
    payload = TaskUpdate(status="review", comment="Implemented and tested.")
    captured: dict[str, Any] = {}

    async def fake_guard(*_args: object, **kwargs: object) -> None:
        captured["write"] = kwargs["write"]

    async def fake_update_task(**kwargs: object) -> object:
        captured.update(kwargs)
        return {"id": str(task.id), "status": "review"}

    monkeypatch.setattr(agent_api, "_guard_task_access", fake_guard)
    monkeypatch.setattr(agent_api.tasks_api, "update_task", fake_update_task)

    result = await agent_api.update_task_status(
        payload=payload,
        task=task,
        session=object(),  # type: ignore[arg-type]
        agent_ctx=_agent_ctx(board_id),
    )

    assert result == {"id": str(task.id), "status": "review"}
    assert captured["write"] is True
    assert captured["payload"] is payload
    assert captured["task"] is task
    assert captured["actor"].agent.board_id == board_id


@pytest.mark.asyncio
async def test_agent_task_status_endpoint_requires_status() -> None:
    board_id = uuid4()
    task = Task(
        id=uuid4(),
        board_id=board_id,
        title="Implement work",
        status="in_progress",
    )

    with pytest.raises(agent_api.HTTPException) as exc:
        await agent_api.update_task_status(
            payload=TaskUpdate(comment="Just a note."),
            task=task,
            session=object(),  # type: ignore[arg-type]
            agent_ctx=_agent_ctx(board_id),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "status is required"


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
