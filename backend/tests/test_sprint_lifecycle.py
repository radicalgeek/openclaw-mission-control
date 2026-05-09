# ruff: noqa: S101
"""Unit tests for sprint lifecycle service logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.sprints import Sprint, SprintTicket
from app.models.tasks import Task

# ---------------------------------------------------------------------------
# Fake session helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeExecResult:
    items: list[Any] = field(default_factory=list)

    def first(self) -> Any | None:
        return self.items[0] if self.items else None

    def all(self) -> list[Any]:
        return self.items


@dataclass
class _FakeSession:
    objects: dict[UUID, Any] = field(default_factory=dict)
    added: list[Any] = field(default_factory=list)
    deleted: list[Any] = field(default_factory=list)
    commits: int = 0
    _exec_results: list[_FakeExecResult] = field(default_factory=list)

    def _push_result(self, items: list[Any]) -> None:
        self._exec_results.append(_FakeExecResult(items))

    async def get(self, model: type, pk: UUID) -> Any | None:
        return self.objects.get(pk)

    async def exec(self, _query: Any) -> Any:
        if self._exec_results:
            return self._exec_results.pop(0)
        return _FakeExecResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if hasattr(obj, "id") and obj.id is not None:
            self.objects[obj.id] = obj

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _board(*, auto_advance: bool = False) -> Board:
    b = Board(
        id=uuid4(),
        organization_id=uuid4(),
        name="Test Board",
        slug="test-board",
    )
    b.auto_advance_sprint = auto_advance
    return b


def _sprint(board: Board, *, status: str = "draft") -> Sprint:
    s = Sprint(
        id=uuid4(),
        organization_id=board.organization_id,
        board_id=board.id,
        name="Sprint 1",
        slug="sprint-1",
        status=status,
        position=0,
    )
    return s


def _task(board: Board, *, task_status: str = "inbox", is_backlog: bool = False) -> Task:
    t = Task(
        id=uuid4(),
        board_id=board.id,
        title="Task 1",
        description="",
        status=task_status,
        priority="medium",
        is_backlog=is_backlog,
    )
    return t


def _sprint_ticket(sprint: Sprint, task: Task, position: int = 0) -> SprintTicket:
    return SprintTicket(
        id=uuid4(),
        sprint_id=sprint.id,
        task_id=task.id,
        position=position,
    )


# ---------------------------------------------------------------------------
# Tests: start_sprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_sprint_raises_if_not_draft_or_queued() -> None:
    from fastapi import HTTPException

    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="active")
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        await SprintService.start_sprint(session, sprint=sprint, board=board)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_start_sprint_raises_if_active_sprint_exists() -> None:
    from fastapi import HTTPException

    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="draft")
    active_sprint = _sprint(board, status="active")

    session = _FakeSession()
    session._push_result([active_sprint])  # exec for active sprint query returns one result

    with pytest.raises(HTTPException) as exc_info:
        await SprintService.start_sprint(session, sprint=sprint, board=board)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert "already active" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_start_sprint_succeeds_no_active_sprint() -> None:
    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="draft")
    task = _task(board, task_status="inbox", is_backlog=False)
    ticket = _sprint_ticket(sprint, task)

    session = _FakeSession()
    session.objects[task.id] = task
    # exec calls: 1) check for active sprint (empty), 2) get sprint tickets
    session._push_result([])  # no active sprint
    session._push_result([ticket])  # sprint tickets

    await SprintService.start_sprint(session, sprint=sprint, board=board)  # type: ignore[arg-type]

    assert sprint.status == "active"
    assert sprint.started_at is not None


@pytest.mark.asyncio
async def test_start_sprint_registers_runtime_agents_and_wakes_lead(monkeypatch: Any) -> None:
    from app.services import sprint_lifecycle
    from app.services.openclaw import provisioning
    from app.services.openclaw.gateway_dispatch import GatewayDispatchService

    board = _board()
    board.gateway_id = uuid4()
    sprint = _sprint(board, status="draft")
    task = _task(board, task_status="inbox", is_backlog=False)
    ticket = _sprint_ticket(sprint, task)
    gateway = Gateway(
        id=board.gateway_id,
        organization_id=board.organization_id,
        name="Gateway",
        url="ws://gateway",
        token="token",
        workspace_root="/home/node/.openclaw/agents",
        disable_device_pairing=True,
    )
    lead = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="Board Lead",
        is_board_lead=True,
        openclaw_session_id=f"agent:lead-{board.id}:main",
        status="updating",
    )
    developer = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gateway.id,
        name="Developer",
        openclaw_session_id=f"agent:mc-{uuid4()}:main",
        status="offline",
    )
    session = _FakeSession()
    session.objects[task.id] = task
    session.objects[gateway.id] = gateway
    session._push_result([])  # no active sprint
    session._push_result([ticket])  # sprint tickets
    session._push_result([])  # sprint webhooks
    session._push_result([lead, developer])  # board agents

    synced: list[tuple[Gateway, list[Agent]]] = []
    sent: list[dict[str, Any]] = []

    class _Provisioner:
        async def sync_gateway_agent_heartbeats(
            self,
            gateway_arg: Gateway,
            agents_arg: list[Agent],
        ) -> None:
            synced.append((gateway_arg, agents_arg))

    async def _send_agent_message(
        self: GatewayDispatchService,
        *,
        session_key: str,
        config: Any,
        agent_name: str,
        message: str,
        deliver: bool = False,
    ) -> None:
        sent.append(
            {
                "session_key": session_key,
                "agent_name": agent_name,
                "message": message,
                "deliver": deliver,
                "config": config,
            },
        )

    monkeypatch.setattr(provisioning, "OpenClawGatewayProvisioner", _Provisioner)
    monkeypatch.setattr(
        GatewayDispatchService,
        "send_agent_message",
        _send_agent_message,
    )

    await sprint_lifecycle.SprintService.start_sprint(
        session,
        sprint=sprint,
        board=board,
    )  # type: ignore[arg-type]

    assert [(item.name, item.status) for item in synced[0][1]] == [
        ("Board Lead", "updating"),
        ("Developer", "offline"),
    ]
    assert sent == [
        {
            "session_key": lead.openclaw_session_id,
            "agent_name": "Board Lead",
            "message": sent[0]["message"],
            "deliver": True,
            "config": sent[0]["config"],
        },
    ]
    assert "Sprint started on board Test Board" in sent[0]["message"]
    assert "assign the sprint inbox tickets" in sent[0]["message"]
    assert lead.status == "updating"
    assert developer.status == "offline"


# ---------------------------------------------------------------------------
# Tests: cancel_sprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_sprint_raises_if_already_completed() -> None:
    from fastapi import HTTPException

    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="completed")
    session = _FakeSession()

    with pytest.raises(HTTPException) as exc_info:
        await SprintService.cancel_sprint(session, sprint=sprint, board=board)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_sprint_sets_status_cancelled() -> None:
    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="active")
    task = _task(board, task_status="in_progress")
    task.sprint_id = sprint.id
    ticket = _sprint_ticket(sprint, task)

    session = _FakeSession()
    session.objects[task.id] = task
    # exec: get sprint tickets
    session._push_result([ticket])

    await SprintService.cancel_sprint(session, sprint=sprint, board=board)  # type: ignore[arg-type]

    assert sprint.status == "cancelled"


# ---------------------------------------------------------------------------
# Tests: check_sprint_completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_sprint_completion_no_active_sprint() -> None:
    """Should return immediately without error if no active sprint found."""
    from app.services.sprint_lifecycle import SprintService

    board = _board()
    session = _FakeSession()
    session._push_result([])  # no active sprint

    # Should not raise
    await SprintService.check_sprint_completion(session, board_id=board.id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_check_sprint_completion_not_all_done() -> None:
    """Should NOT complete sprint when some tickets are still in progress."""
    from app.services.sprint_lifecycle import SprintService

    board = _board()
    sprint = _sprint(board, status="active")
    task_done = _task(board, task_status="done")
    task_open = _task(board, task_status="in_progress")
    tick1 = _sprint_ticket(sprint, task_done)
    tick2 = _sprint_ticket(sprint, task_open)

    session = _FakeSession()
    session.objects[task_done.id] = task_done
    session.objects[task_open.id] = task_open
    session._push_result([sprint])  # active sprint
    session._push_result([tick1, tick2])  # sprint tickets

    await SprintService.check_sprint_completion(session, board_id=board.id)  # type: ignore[arg-type]

    # Sprint should NOT have been completed
    assert sprint.status == "active"
