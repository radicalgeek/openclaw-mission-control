# ruff: noqa: INP001
"""Org-agent reconcile queue dedup helpers."""

from __future__ import annotations

from app.services.openclaw.org_agent_reconcile_queue import (
    clear_org_agent_reconcile_lock,
    enqueue_org_agent_reconcile,
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


def test_enqueue_org_reconcile_records_task_id(
    monkeypatch,
) -> None:
    captured: dict[str, QueuedTask] = {}
    fake_redis = _FakeRedis()

    monkeypatch.setattr(
        "app.services.openclaw.org_agent_reconcile_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )
    monkeypatch.setattr(
        "app.services.openclaw.org_agent_reconcile_queue.enqueue_task_with_delay",
        lambda task, queue_name, *, delay_seconds, redis_url=None: captured.setdefault(
            "task",
            task,
        )
        is task,
    )

    assert enqueue_org_agent_reconcile() is True

    task = captured["task"]
    assert isinstance(task.payload["task_id"], str)
    assert fake_redis.value == task.payload["task_id"]


def test_clear_org_reconcile_lock_requires_owner(
    monkeypatch,
) -> None:
    fake_redis = _FakeRedis()
    fake_redis.value = "newer-task"

    monkeypatch.setattr(
        "app.services.openclaw.org_agent_reconcile_queue._redis_client",
        lambda redis_url=None: fake_redis,
    )

    clear_org_agent_reconcile_lock(None)
    clear_org_agent_reconcile_lock("older-task")
    assert fake_redis.value == "newer-task"
    assert fake_redis.deleted is False

    clear_org_agent_reconcile_lock("newer-task")
    assert fake_redis.value is None
    assert fake_redis.deleted is True
