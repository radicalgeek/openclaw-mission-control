"""Helpers for aggregating usage snapshots safely across time windows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from uuid import UUID

from app.models.usage_snapshots import (
    SNAPSHOT_TYPE_AGENT_REPORT,
    SNAPSHOT_TYPE_PERIODIC,
    SNAPSHOT_TYPE_SESSION_END,
    UsageSnapshot,
)

CUMULATIVE_SNAPSHOT_TYPES = frozenset({SNAPSHOT_TYPE_PERIODIC, SNAPSHOT_TYPE_SESSION_END})


@dataclass(frozen=True)
class UsageAggregate:
    """Normalized usage totals for a single logical series in a time window."""

    gateway_id: UUID
    agent_id: UUID | None
    session_key: str | None
    model_id: str
    snapshot_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


def count_window_snapshots(
    snapshots: Iterable[UsageSnapshot],
    *,
    since: datetime | None,
    until: datetime | None,
) -> int:
    """Count raw snapshots whose capture time falls inside the requested window."""
    return sum(1 for snapshot in snapshots if _is_in_window(snapshot, since=since, until=until))


def aggregate_usage_window(
    snapshots: Iterable[UsageSnapshot],
    *,
    since: datetime | None,
    until: datetime | None,
) -> list[UsageAggregate]:
    """Aggregate usage rows for the requested time window.

    `agent_report` rows are treated as interval events and summed directly.
    `periodic` and `session_end` rows are treated as cumulative snapshots and
    converted into window deltas.
    """
    bounded = [snapshot for snapshot in snapshots if until is None or snapshot.captured_at <= until]

    aggregates: list[UsageAggregate] = []
    cumulative_groups: dict[
        tuple[str, UUID, UUID | None, str | None, str],
        list[UsageSnapshot],
    ] = defaultdict(list)

    for snapshot in bounded:
        if snapshot.snapshot_type == SNAPSHOT_TYPE_AGENT_REPORT:
            if _is_in_window(snapshot, since=since, until=until):
                aggregates.append(
                    UsageAggregate(
                        gateway_id=snapshot.gateway_id,
                        agent_id=snapshot.agent_id,
                        session_key=snapshot.session_key,
                        model_id=snapshot.model_id,
                        snapshot_type=snapshot.snapshot_type,
                        prompt_tokens=int(snapshot.prompt_tokens or 0),
                        completion_tokens=int(snapshot.completion_tokens or 0),
                        total_tokens=int(snapshot.total_tokens or 0),
                        cost_usd=float(snapshot.cost_usd or 0),
                    )
                )
            continue

        if snapshot.snapshot_type in CUMULATIVE_SNAPSHOT_TYPES:
            key = (
                snapshot.snapshot_type,
                snapshot.gateway_id,
                snapshot.agent_id,
                snapshot.session_key,
                snapshot.model_id,
            )
            cumulative_groups[key].append(snapshot)

    for key, rows in cumulative_groups.items():
        rows.sort(key=lambda row: (row.captured_at, str(row.id)))
        end_row = rows[-1]
        baseline = None
        if since is not None:
            for row in rows:
                if row.captured_at < since:
                    baseline = row
                else:
                    break

        prompt_tokens = _clamp_delta(
            end_row.prompt_tokens, baseline.prompt_tokens if baseline else None
        )
        completion_tokens = _clamp_delta(
            end_row.completion_tokens,
            baseline.completion_tokens if baseline else None,
        )
        total_tokens = _clamp_delta(
            end_row.total_tokens, baseline.total_tokens if baseline else None
        )
        cost_usd = _clamp_cost_delta(end_row.cost_usd, baseline.cost_usd if baseline else None)

        if not any((prompt_tokens, completion_tokens, total_tokens, cost_usd)):
            continue

        snapshot_type, gateway_id, agent_id, session_key, model_id = key
        aggregates.append(
            UsageAggregate(
                gateway_id=gateway_id,
                agent_id=agent_id,
                session_key=session_key,
                model_id=model_id,
                snapshot_type=snapshot_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
            )
        )

    return aggregates


def _is_in_window(
    snapshot: UsageSnapshot,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    if since is not None and snapshot.captured_at < since:
        return False
    if until is not None and snapshot.captured_at > until:
        return False
    return True


def _clamp_delta(current: int | None, baseline: int | None) -> int:
    current_value = int(current or 0)
    baseline_value = int(baseline or 0)
    return max(current_value - baseline_value, 0)


def _clamp_cost_delta(current: float | int | None, baseline: float | int | None) -> float:
    current_value = float(current or 0)
    baseline_value = float(baseline or 0)
    return max(current_value - baseline_value, 0.0)
