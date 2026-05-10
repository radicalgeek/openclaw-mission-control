# ruff: noqa: INP001
"""Queue worker active board-work recovery pulse tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import queue_worker


class _FakeSession:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


@pytest.mark.asyncio
async def test_active_work_recovery_pulse_runs_before_lifecycle_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monotonic = iter([100.0, 120.0, 161.0])

    monkeypatch.setattr(queue_worker, "_last_active_work_recovery_monotonic", 0.0)
    monkeypatch.setattr(queue_worker, "time", SimpleNamespace(monotonic=lambda: next(monotonic)))
    monkeypatch.setattr(queue_worker, "async_session_maker", lambda: _FakeSession())

    async def _fake_recover(session: object) -> int:
        calls.append("recover")
        return 1

    monkeypatch.setattr(queue_worker, "wake_stale_board_agents_with_active_work", _fake_recover)

    await queue_worker._pulse_active_work_recovery()
    await queue_worker._pulse_active_work_recovery()
    await queue_worker._pulse_active_work_recovery()

    assert calls == ["recover", "recover"]
