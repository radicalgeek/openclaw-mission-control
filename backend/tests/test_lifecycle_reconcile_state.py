# ruff: noqa: INP001
"""Lifecycle reconcile state helpers."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.core.time import utcnow
from app.models.agents import AGENT_TYPE_BOARD_WORKER, AGENT_TYPE_STANDALONE, Agent
from app.services.openclaw.constants import (
    CHECKIN_DEADLINE_AFTER_WAKE,
    MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN,
    OFFLINE_AFTER,
)
from app.services.openclaw.lifecycle_reconcile import (
    _can_retry_after_max_wake_attempts,
    _has_checked_in_since_wake,
    _should_reset_session_for_reconcile,
)


def _agent(
    *,
    last_seen_offset_s: int | None,
    last_wake_offset_s: int | None,
    agent_type: str = AGENT_TYPE_BOARD_WORKER,
) -> Agent:
    now = utcnow()
    return Agent(
        name="reconcile-test",
        gateway_id=uuid4(),
        last_seen_at=(
            (now + timedelta(seconds=last_seen_offset_s))
            if last_seen_offset_s is not None
            else None
        ),
        last_wake_sent_at=(
            (now + timedelta(seconds=last_wake_offset_s))
            if last_wake_offset_s is not None
            else None
        ),
        agent_type=agent_type,
    )


def test_checked_in_since_wake_when_last_seen_after_wake() -> None:
    agent = _agent(last_seen_offset_s=5, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is True


def test_not_checked_in_since_wake_when_last_seen_before_wake() -> None:
    agent = _agent(last_seen_offset_s=-5, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is False


def test_not_checked_in_since_wake_when_missing_last_seen() -> None:
    agent = _agent(last_seen_offset_s=None, last_wake_offset_s=0)
    assert _has_checked_in_since_wake(agent) is False


def test_reset_session_when_agent_never_checked_in() -> None:
    agent = _agent(last_seen_offset_s=None, last_wake_offset_s=0)
    assert _should_reset_session_for_reconcile(agent) is True


def test_reset_session_when_standalone_agent_misses_wake() -> None:
    stale_offset = -int(OFFLINE_AFTER.total_seconds()) - 60
    agent = _agent(
        last_seen_offset_s=stale_offset,
        last_wake_offset_s=-30,
        agent_type=AGENT_TYPE_STANDALONE,
    )
    assert _should_reset_session_for_reconcile(agent) is True


def test_preserve_session_when_board_worker_misses_wake_after_checkin() -> None:
    stale_offset = -int(OFFLINE_AFTER.total_seconds()) - 60
    agent = _agent(
        last_seen_offset_s=stale_offset,
        last_wake_offset_s=-30,
        agent_type=AGENT_TYPE_BOARD_WORKER,
    )
    assert _should_reset_session_for_reconcile(agent) is False


def test_allow_max_attempt_retry_for_stale_standalone_session() -> None:
    stale_offset = -int(OFFLINE_AFTER.total_seconds()) - 60
    agent = _agent(
        last_seen_offset_s=stale_offset,
        last_wake_offset_s=-30,
        agent_type=AGENT_TYPE_STANDALONE,
    )
    assert _can_retry_after_max_wake_attempts(agent) is True


def test_preserve_max_attempt_stop_for_stale_board_worker_session() -> None:
    stale_offset = -int(OFFLINE_AFTER.total_seconds()) - 60
    agent = _agent(
        last_seen_offset_s=stale_offset,
        last_wake_offset_s=-30,
        agent_type=AGENT_TYPE_BOARD_WORKER,
    )
    assert _can_retry_after_max_wake_attempts(agent) is False


def test_lifecycle_convergence_policy_constants() -> None:
    # These module-level constants are kept for import compatibility; the live
    # code reads from settings (agent_checkin_deadline_seconds /
    # agent_max_wake_attempts) which default to the same values.
    assert CHECKIN_DEADLINE_AFTER_WAKE == timedelta(seconds=120)
    assert MAX_WAKE_ATTEMPTS_WITHOUT_CHECKIN == 5
