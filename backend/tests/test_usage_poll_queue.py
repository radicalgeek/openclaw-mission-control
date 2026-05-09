# ruff: noqa: INP001
"""Usage-poll queue dedup helpers."""

from __future__ import annotations

import pytest

from app.core.time import utcnow
from app.services.telemetry.usage_poll_queue import (
    TASK_TYPE,
    clear_usage_poll_lock,
    enqueue_usage_poll,
    is_current_usage_poll_task,
)
from app.services.queue import QueuedTask


class _FakeRedis:
    def __init__(self) -> None:
        self.value: str | None = None
        self.deleted = False

    def set(self, key: str, value: str, *, nx: bool | None = None, ex: int | None = None) -> bool:
        if nx and self.value is not None:
            return False
        self.value = value
        return True

    def get(self, key: str) -> bytes | None:
        return self.value.encode("utf-8") if self.value is not None else None

    def delete(self, key: str) -> None:
        self.deleted = True
        self.value = None


def test_enqueue_usage_poll_records_task_id(monkeypatch) -> None:
    captured: dict[str, QueuedTask] = {}
    fake_redis = _FakeRedis()

    monkeypatch.setattr(
        "app.services.telemetry.usage_poll_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )
    monkeypatch.setattr(
        "app.services.telemetry.usage_poll_queue.enqueue_task_with_delay",
        lambda task, queue_name, *, delay_seconds, redis_url=None: captured.setdefault(
            "task",
            task,
        )
        is task,
    )

    assert enqueue_usage_poll() is True

    task = captured["task"]
    assert isinstance(task.payload["task_id"], str)
    assert fake_redis.value == task.payload["task_id"]


def test_usage_poll_current_task_requires_owner(monkeypatch) -> None:
    fake_redis = _FakeRedis()
    fake_redis.value = "newer-task"

    monkeypatch.setattr(
        "app.services.telemetry.usage_poll_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )

    assert is_current_usage_poll_task(None) is False
    assert is_current_usage_poll_task("older-task") is False
    assert is_current_usage_poll_task("newer-task") is True


def test_clear_usage_poll_lock_requires_owner(monkeypatch) -> None:
    fake_redis = _FakeRedis()
    fake_redis.value = "newer-task"

    monkeypatch.setattr(
        "app.services.telemetry.usage_poll_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )

    clear_usage_poll_lock(None)
    clear_usage_poll_lock("older-task")
    assert fake_redis.value == "newer-task"
    assert fake_redis.deleted is False

    clear_usage_poll_lock("newer-task")
    assert fake_redis.value is None
    assert fake_redis.deleted is True


@pytest.mark.asyncio
async def test_stale_usage_poll_task_skips_work(monkeypatch) -> None:
    from app.services.telemetry import usage_poll_worker

    calls: list[str] = []

    monkeypatch.setattr(
        usage_poll_worker,
        "is_current_usage_poll_task",
        lambda task_id: task_id == "current-task",
    )
    monkeypatch.setattr(
        usage_poll_worker,
        "enqueue_usage_poll",
        lambda *, delay_seconds=0: calls.append("enqueue") or True,
    )
    monkeypatch.setattr(
        usage_poll_worker,
        "async_session_maker",
        lambda: calls.append("session"),
    )

    task = QueuedTask(
        task_type=TASK_TYPE,
        payload={"task_id": "stale-task"},
        created_at=utcnow(),
    )

    await usage_poll_worker.process_usage_poll_task(task)

    assert calls == []
