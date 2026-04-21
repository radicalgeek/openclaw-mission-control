# ruff: noqa: INP001
"""Tests for usage snapshot rollups."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from app.models.usage_snapshots import (
    SNAPSHOT_TYPE_AGENT_REPORT,
    SNAPSHOT_TYPE_PERIODIC,
    UsageSnapshot,
)
from app.services.telemetry.usage_rollups import aggregate_usage_window, count_window_snapshots


def test_aggregate_usage_window_deltas_cumulative_snapshots() -> None:
    gateway_id = uuid4()
    org_id = uuid4()
    window_start = datetime(2026, 4, 1, 12, 0, 0)

    snapshots = [
        UsageSnapshot(
            organization_id=org_id,
            gateway_id=gateway_id,
            agent_id=None,
            session_key=None,
            model_id="claude",
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            cost_usd=1.5,
            snapshot_type=SNAPSHOT_TYPE_PERIODIC,
            captured_at=window_start - timedelta(hours=1),
        ),
        UsageSnapshot(
            organization_id=org_id,
            gateway_id=gateway_id,
            agent_id=None,
            session_key=None,
            model_id="claude",
            prompt_tokens=160,
            completion_tokens=70,
            total_tokens=230,
            cost_usd=2.25,
            snapshot_type=SNAPSHOT_TYPE_PERIODIC,
            captured_at=window_start + timedelta(hours=1),
        ),
        UsageSnapshot(
            organization_id=org_id,
            gateway_id=gateway_id,
            agent_id=uuid4(),
            session_key="session-1",
            model_id="claude",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            cost_usd=0.4,
            snapshot_type=SNAPSHOT_TYPE_AGENT_REPORT,
            captured_at=window_start + timedelta(hours=2),
        ),
    ]

    aggregates = aggregate_usage_window(
        snapshots,
        since=window_start,
        until=window_start + timedelta(hours=3),
    )

    assert len(aggregates) == 2

    cumulative = next(item for item in aggregates if item.snapshot_type == SNAPSHOT_TYPE_PERIODIC)
    assert cumulative.prompt_tokens == 60
    assert cumulative.completion_tokens == 30
    assert cumulative.total_tokens == 90
    assert cumulative.cost_usd == 0.75

    direct = next(item for item in aggregates if item.snapshot_type == SNAPSHOT_TYPE_AGENT_REPORT)
    assert direct.total_tokens == 30
    assert direct.cost_usd == 0.4

    assert (
        count_window_snapshots(
            snapshots,
            since=window_start,
            until=window_start + timedelta(hours=3),
        )
        == 2
    )
