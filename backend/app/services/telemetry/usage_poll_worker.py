"""Usage poll worker — snapshots token/cost data from all active gateways."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.gateways import Gateway
from app.models.usage_snapshots import SNAPSHOT_TYPE_PERIODIC, UsageSnapshot
from app.services.openclaw.gateway_resolver import optional_gateway_client_config
from app.services.openclaw.gateway_rpc import OpenClawGatewayError, openclaw_call
from app.services.queue import QueuedTask
from app.services.telemetry.usage_poll_queue import (
    USAGE_POLL_INTERVAL_SECONDS,
    clear_usage_poll_lock,
    enqueue_usage_poll,
)

logger = get_logger(__name__)


def _extract_model_usage(usage_status: Any) -> list[dict[str, Any]]:
    """Parse usage.status payload into per-model usage rows."""
    rows: list[dict[str, Any]] = []
    if not isinstance(usage_status, dict):
        return rows
    # Gateway returns {"models": {"claude-3-5-sonnet": {"used": N, "max": M}, ...}}
    models = usage_status.get("models") or {}
    if isinstance(models, dict):
        for model_id, model_data in models.items():
            if not isinstance(model_data, dict):
                continue
            rows.append(
                {
                    "model_id": str(model_id),
                    "prompt_tokens": int(model_data.get("used", 0)),
                    "completion_tokens": 0,
                    "total_tokens": int(model_data.get("used", 0)),
                    "cost_usd": 0.0,
                }
            )
    return rows


def _extract_cost(usage_cost: Any) -> float:
    """Parse usage.cost payload into a total USD cost float."""
    if isinstance(usage_cost, (int, float)):
        return float(usage_cost)
    if isinstance(usage_cost, dict):
        cost = usage_cost.get("total") or usage_cost.get("cost") or 0
        return float(cost)
    return 0.0


async def _poll_gateway(gateway: Gateway) -> list[UsageSnapshot]:
    """Fetch usage data for a single gateway and return snapshot objects."""
    config = optional_gateway_client_config(gateway)
    if config is None:
        return []

    snapshots: list[UsageSnapshot] = []
    captured_at = utcnow()

    try:
        usage_status = await openclaw_call("usage.status", config=config)
    except (OpenClawGatewayError, Exception):
        logger.warning(
            "usage_poll.usage_status_failed",
            extra={"gateway_id": str(gateway.id)},
        )
        usage_status = None

    try:
        usage_cost = await openclaw_call("usage.cost", config=config)
    except (OpenClawGatewayError, Exception):
        logger.warning(
            "usage_poll.usage_cost_failed",
            extra={"gateway_id": str(gateway.id)},
        )
        usage_cost = None

    total_cost = _extract_cost(usage_cost) if usage_cost is not None else 0.0
    per_model = _extract_model_usage(usage_status) if usage_status is not None else []

    if per_model:
        # Distribute total cost equally across models (approximation)
        cost_per_model = total_cost / len(per_model) if total_cost else 0.0
        for row in per_model:
            snapshots.append(
                UsageSnapshot(
                    id=uuid4(),
                    organization_id=gateway.organization_id,
                    gateway_id=gateway.id,
                    agent_id=None,
                    session_key=None,
                    model_id=row["model_id"],
                    prompt_tokens=row["prompt_tokens"],
                    completion_tokens=row["completion_tokens"],
                    total_tokens=row["total_tokens"],
                    cost_usd=cost_per_model,
                    snapshot_type=SNAPSHOT_TYPE_PERIODIC,
                    captured_at=captured_at,
                )
            )
    elif total_cost > 0:
        # No per-model breakdown — store aggregate
        snapshots.append(
            UsageSnapshot(
                id=uuid4(),
                organization_id=gateway.organization_id,
                gateway_id=gateway.id,
                agent_id=None,
                session_key=None,
                model_id="aggregate",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                cost_usd=total_cost,
                snapshot_type=SNAPSHOT_TYPE_PERIODIC,
                captured_at=captured_at,
            )
        )

    logger.info(
        "usage_poll.gateway_polled",
        extra={
            "gateway_id": str(gateway.id),
            "snapshots": len(snapshots),
        },
    )
    return snapshots


async def process_usage_poll_task(task: QueuedTask) -> None:
    """Process a usage poll task: poll all gateways, persist snapshots, re-enqueue."""
    logger.info("usage_poll.start")
    raw_task_id = task.payload.get("task_id") if isinstance(task.payload, dict) else None
    clear_usage_poll_lock(raw_task_id if isinstance(raw_task_id, str) else None)

    async with async_session_maker() as session:
        from sqlmodel import select

        gateways = (await session.exec(select(Gateway))).all()

        total_snapshots = 0
        for gateway in gateways:
            try:
                snapshots = await _poll_gateway(gateway)
                for snap in snapshots:
                    session.add(snap)
                total_snapshots += len(snapshots)
            except Exception:
                logger.exception(
                    "usage_poll.gateway_error",
                    extra={"gateway_id": str(gateway.id)},
                )

        if total_snapshots > 0:
            await session.commit()

    logger.info("usage_poll.complete", extra={"total_snapshots": total_snapshots})

    # Re-enqueue for next poll cycle
    enqueue_usage_poll(delay_seconds=float(USAGE_POLL_INTERVAL_SECONDS))
