# ruff: noqa: INP001
"""Queue payload helpers for lifecycle reconcile tasks."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.time import utcnow
from app.services.openclaw.lifecycle_queue import (
    QueuedAgentLifecycleReconcile,
    decode_lifecycle_task,
    defer_lifecycle_reconcile,
    enqueue_lifecycle_reconcile,
)
from app.services.queue import QueuedTask


class _FakeRedis:
    def __init__(self, *, acquired: bool = True) -> None:
        self.acquired = acquired
        self.set_calls: list[tuple[str, str, bool | None, int | None]] = []
        self.deleted: list[str] = []

    def set(self, key: str, value: str, *, nx: bool | None = None, ex: int | None = None) -> bool:
        self.set_calls.append((key, value, nx, ex))
        return self.acquired

    def delete(self, key: str) -> None:
        self.deleted.append(key)


def test_enqueue_lifecycle_reconcile_uses_delayed_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_enqueue_with_delay(
        task: QueuedTask,
        queue_name: str,
        *,
        delay_seconds: float,
        redis_url: str | None = None,
    ) -> bool:
        captured["task"] = task
        captured["queue_name"] = queue_name
        captured["delay_seconds"] = delay_seconds
        captured["redis_url"] = redis_url
        return True

    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue.enqueue_task_with_delay",
        _fake_enqueue_with_delay,
    )
    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue._redis_client",
        lambda redis_url=None: _FakeRedis(),
    )

    payload = QueuedAgentLifecycleReconcile(
        agent_id=uuid4(),
        gateway_id=uuid4(),
        board_id=uuid4(),
        generation=7,
        checkin_deadline_at=utcnow() + timedelta(seconds=30),
        attempts=0,
    )

    assert enqueue_lifecycle_reconcile(payload) is True
    task = captured["task"]
    assert isinstance(task, QueuedTask)
    assert task.task_type == "agent_lifecycle_reconcile"
    assert float(captured["delay_seconds"]) > 0


def test_enqueue_lifecycle_reconcile_skips_duplicate_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[QueuedTask] = []

    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue._redis_client",
        lambda redis_url=None: _FakeRedis(acquired=False),
    )
    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue.enqueue_task_with_delay",
        lambda task, queue_name, *, delay_seconds, redis_url=None: calls.append(task) or True,
    )

    payload = QueuedAgentLifecycleReconcile(
        agent_id=uuid4(),
        gateway_id=uuid4(),
        board_id=None,
        generation=7,
        checkin_deadline_at=utcnow(),
    )

    assert enqueue_lifecycle_reconcile(payload) is False
    assert calls == []


def test_enqueue_lifecycle_reconcile_releases_dedup_when_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FakeRedis()
    agent_id = uuid4()

    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )
    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue.enqueue_task_with_delay",
        lambda task, queue_name, *, delay_seconds, redis_url=None: False,
    )

    payload = QueuedAgentLifecycleReconcile(
        agent_id=agent_id,
        gateway_id=uuid4(),
        board_id=None,
        generation=9,
        checkin_deadline_at=utcnow(),
    )

    assert enqueue_lifecycle_reconcile(payload) is False
    assert fake_redis.deleted == [f"axiacraft:agent_lifecycle_reconcile:{agent_id}:9"]


def test_defer_lifecycle_reconcile_keeps_attempt_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_enqueue_with_delay(
        task: QueuedTask,
        queue_name: str,
        *,
        delay_seconds: float,
        redis_url: str | None = None,
    ) -> bool:
        captured["task"] = task
        captured["queue_name"] = queue_name
        captured["delay_seconds"] = delay_seconds
        captured["redis_url"] = redis_url
        return True

    monkeypatch.setattr(
        "app.services.openclaw.lifecycle_queue.enqueue_task_with_delay",
        _fake_enqueue_with_delay,
    )
    deadline = utcnow() + timedelta(minutes=1)
    task = QueuedTask(
        task_type="agent_lifecycle_reconcile",
        payload={
            "agent_id": str(uuid4()),
            "gateway_id": str(uuid4()),
            "board_id": None,
            "generation": 3,
            "checkin_deadline_at": deadline.isoformat(),
        },
        created_at=utcnow(),
        attempts=2,
    )
    assert defer_lifecycle_reconcile(task, delay_seconds=12) is True
    deferred_task = captured["task"]
    assert isinstance(deferred_task, QueuedTask)
    assert deferred_task.attempts == 2
    assert float(captured["delay_seconds"]) == 12


def test_decode_lifecycle_task_roundtrip() -> None:
    deadline = utcnow() + timedelta(minutes=3)
    agent_id = uuid4()
    gateway_id = uuid4()
    board_id = uuid4()
    task = QueuedTask(
        task_type="agent_lifecycle_reconcile",
        payload={
            "agent_id": str(agent_id),
            "gateway_id": str(gateway_id),
            "board_id": str(board_id),
            "generation": 5,
            "checkin_deadline_at": deadline.isoformat(),
        },
        created_at=utcnow(),
        attempts=1,
    )

    decoded = decode_lifecycle_task(task)
    assert decoded.agent_id == agent_id
    assert decoded.gateway_id == gateway_id
    assert decoded.board_id == board_id
    assert decoded.generation == 5
    assert decoded.checkin_deadline_at == deadline
    assert decoded.attempts == 1
