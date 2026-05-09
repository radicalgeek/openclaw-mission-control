"""Org-level standalone agent reconciler.

Idempotently provisions one standalone agent per role template from
``STANDALONE_ROLE_TEMPLATES`` for each organization that has a gateway.

Designed for two call sites:
1. Right after org creation (best-effort, fire-and-forget on errors).
2. Periodic background reconciliation via the queue worker.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.agents import (
    AGENT_TYPE_STANDALONE,
    Agent,
)
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.schemas.agents import STANDALONE_ROLE_TEMPLATES
from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG, OFFLINE_AFTER
from app.services.openclaw.db_agent_state import mint_agent_token
from app.services.openclaw.internal.session_keys import standalone_agent_session_key
from app.services.openclaw.lifecycle_orchestrator import AgentLifecycleOrchestrator
from app.services.openclaw.lifecycle_queue import (
    QueuedAgentLifecycleReconcile,
    enqueue_lifecycle_reconcile,
)

logger = get_logger(__name__)

# Human-readable display names used as the agent ``name`` and ``identity.role``.
_ROLE_DISPLAY_NAMES: dict[str, str] = {
    "triager": "Triager",
    "planner": "Planner",
    "estimator": "Estimator",
    "priority": "Priority Agent",
    "quality_reviewer": "Quality Reviewer",
    "security_reviewer": "Security Reviewer",
    "architecture_reviewer": "Architecture Reviewer",
}

# Emoji identifiers for the identity profile.
_ROLE_EMOJIS: dict[str, str] = {
    "triager": ":inbox_tray:",
    "planner": ":spiral_notepad:",
    "estimator": ":straight_ruler:",
    "priority": ":dart:",
    "quality_reviewer": ":white_check_mark:",
    "security_reviewer": ":lock:",
    "architecture_reviewer": ":building_construction:",
}


def _build_identity_profile(role_template: str) -> dict[str, str]:
    display_name = _ROLE_DISPLAY_NAMES.get(role_template, role_template.replace("_", " ").title())
    emoji = _ROLE_EMOJIS.get(role_template, ":robot_face:")
    return {
        "role": display_name,
        "role_template": role_template,
        "communication_style": "direct, concise, practical",
        "emoji": emoji,
    }


async def _get_existing_role_templates(
    session: Any,
    gateway_id: UUID,
) -> set[str]:
    """Return the set of role_template values already provisioned for a gateway."""
    agents = (
        await session.exec(
            select(Agent)
            .where(col(Agent.gateway_id) == gateway_id)
            .where(col(Agent.agent_type) == AGENT_TYPE_STANDALONE),
        )
    ).all()
    result: set[str] = set()
    for agent in agents:
        profile = agent.identity_profile
        if isinstance(profile, dict):
            rt = profile.get("role_template")
            if rt:
                result.add(str(rt))
    return result


async def _provision_standalone_agent(
    *,
    session: Any,
    gateway: Gateway,
    role_template: str,
) -> Agent | None:
    """Create and provision a single standalone agent on the given gateway.

    Returns the created ``Agent`` on success, or ``None`` if provisioning
    failed (errors are logged but not re-raised to keep reconciliation atomic).
    """
    from app.core.time import utcnow

    display_name = _ROLE_DISPLAY_NAMES.get(role_template, role_template.replace("_", " ").title())
    now = utcnow()

    agent = Agent(
        name=display_name,
        gateway_id=gateway.id,
        board_id=None,
        agent_type=AGENT_TYPE_STANDALONE,
        is_board_lead=False,
        status="provisioning",
        heartbeat_config=DEFAULT_HEARTBEAT_CONFIG.copy(),
        identity_profile=_build_identity_profile(role_template),
        created_at=now,
        updated_at=now,
    )
    raw_token = mint_agent_token(agent)
    session.add(agent)
    await session.flush()
    agent.openclaw_session_id = standalone_agent_session_key(agent.id)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    try:
        await AgentLifecycleOrchestrator(session).run_lifecycle(
            gateway=gateway,
            agent_id=agent.id,
            board=None,
            user=None,
            action="provision",
            auth_token=raw_token,
            force_bootstrap=False,
            reset_session=True,
            wake=True,
            deliver_wakeup=True,
            wakeup_verb="provisioned",
            clear_confirm_token=True,
            raise_gateway_errors=False,
            extra_files=None,
        )
        logger.info(
            "org_agent_reconciler.agent_provisioned agent_id=%s role_template=%s gateway_id=%s",
            agent.id,
            role_template,
            gateway.id,
        )
    except Exception:
        logger.exception(
            "org_agent_reconciler.provision_failed agent_id=%s role_template=%s gateway_id=%s",
            agent.id,
            role_template,
            gateway.id,
        )

    return agent


async def reconcile_org_standalone_agents(
    session: Any,
    *,
    organization_id: UUID,
) -> dict[str, str]:
    """Ensure all STANDALONE_ROLE_TEMPLATES agents exist for an org's gateway.

    Returns a dict mapping role_template → outcome ("created", "exists", "no_gateway").
    """
    outcomes: dict[str, str] = {}

    gateway = (
        await session.exec(
            select(Gateway).where(col(Gateway.organization_id) == organization_id),
        )
    ).first()

    if gateway is None:
        logger.info(
            "org_agent_reconciler.no_gateway org_id=%s",
            organization_id,
        )
        for template in STANDALONE_ROLE_TEMPLATES:
            outcomes[template] = "no_gateway"
        return outcomes

    existing = await _get_existing_role_templates(session, gateway.id)
    logger.info(
        "org_agent_reconciler.reconcile_start org_id=%s gateway_id=%s existing=%s",
        organization_id,
        gateway.id,
        sorted(existing),
    )

    for role_template in sorted(STANDALONE_ROLE_TEMPLATES):
        if role_template in existing:
            outcomes[role_template] = "exists"
            continue
        try:
            agent = await _provision_standalone_agent(
                session=session,
                gateway=gateway,
                role_template=role_template,
            )
            outcomes[role_template] = "created" if agent is not None else "failed"
        except Exception:
            logger.exception(
                "org_agent_reconciler.error org_id=%s role_template=%s",
                organization_id,
                role_template,
            )
            outcomes[role_template] = "error"

    logger.info(
        "org_agent_reconciler.reconcile_done org_id=%s outcomes=%s",
        organization_id,
        outcomes,
    )
    return outcomes


async def reconcile_all_orgs(session: Any) -> None:
    """Reconcile standalone agents for every organization in the database."""
    orgs = (await session.exec(select(Organization))).all()
    logger.info("org_agent_reconciler.full_sweep org_count=%d", len(orgs))
    for org in orgs:
        try:
            await reconcile_org_standalone_agents(session, organization_id=org.id)
        except Exception:
            logger.exception(
                "org_agent_reconciler.org_error org_id=%s",
                org.id,
            )


async def sweep_stuck_provisioning_agents(session: Any) -> int:
    """Re-enqueue lifecycle reconcile tasks for agents that need re-waking.

    Catches four conditions so agents auto-recover after a gateway worker
    restart (which wipes the in-memory ``agents.list`` and leaves every agent
    in ``offline`` / ``updating`` with a stale ``last_seen_at``):

    - ``status == 'provisioning'`` and ``last_seen_at IS NULL`` and
      ``updated_at < now - threshold`` — agent was created but never
      heartbeated; lifecycle queue task was lost.
    - ``status == 'online'`` and ``(last_seen_at IS NULL OR last_seen_at <
      now - OFFLINE_AFTER)`` and ``updated_at < now - threshold`` — gateway
      provision succeeded (``mark_provision_complete`` set status='online')
      but either the agent never sent its first heartbeat, or its last
      heartbeat is stale (heartbeat loop stopped). The API serialiser's
      ``with_computed_status`` shows these as 'provisioning' (no last_seen)
      or 'offline' (stale last_seen) even though the DB column is 'online',
      so without this case the ``status='offline'`` filter below silently
      misses them and they stay stuck in the UI forever.
    - ``status == 'updating'`` and the agent has not checked in since its
      last wake — a previous update attempt failed (typically a 503 / WS
      handshake timeout from a worker restart).
    - ``status == 'offline'`` with a ``gateway_id`` set and ``updated_at``
      older than the threshold — the agent went offline (worker restart,
      cron didn't fire, etc.) and needs to be re-registered with the gateway
      so its heartbeat schedule fires again.

    The sweep deliberately preserves ``wake_attempts``. Resetting the counter
    here turns stale presence into an infinite re-provision loop: each sweep
    gives the agent a fresh budget before the lifecycle reconciler can reach
    ``agent_max_wake_attempts`` and stop.

    Each matched agent gets a reconcile task enqueued with
    ``checkin_deadline_at=now`` (deadline in the past → fires immediately).

    Returns the number of agents re-enqueued.
    """
    threshold = utcnow() - timedelta(seconds=settings.agent_stuck_provisioning_sweep_seconds)

    stuck_provisioning = list(
        await session.exec(
            select(Agent)
            .where(col(Agent.status) == "provisioning")
            .where(col(Agent.last_seen_at).is_(None))
            .where(col(Agent.updated_at) < threshold)
        )
    )
    offline_cutoff = utcnow() - OFFLINE_AFTER
    stuck_online_unseen = list(
        await session.exec(
            select(Agent)
            .where(col(Agent.status) == "online")
            .where(col(Agent.gateway_id).is_not(None))
            .where(col(Agent.updated_at) < threshold)
            .where(
                or_(
                    col(Agent.last_seen_at).is_(None),
                    col(Agent.last_seen_at) < offline_cutoff,
                )
            )
        )
    )
    stuck_updating = list(
        await session.exec(
            select(Agent)
            .where(col(Agent.status) == "updating")
            .where(col(Agent.updated_at) < threshold)
            .where(
                or_(
                    col(Agent.last_seen_at).is_(None),
                    # Heartbeat older than OFFLINE_AFTER — agent is no
                    # longer responding, regardless of where the last
                    # wake fell. Without this case, agents whose status
                    # got wedged at "updating" by a failed-mid-flight
                    # reconcile (mark_provision_complete never fired)
                    # but happen to have a stale last_seen_at that's
                    # newer than last_wake_sent_at sit forever and the
                    # sweep can't unstick them.
                    col(Agent.last_seen_at) < offline_cutoff,
                    col(Agent.last_wake_sent_at).is_not(None)
                    & (col(Agent.last_seen_at) < col(Agent.last_wake_sent_at)),
                )
            )
        )
    )
    stuck_offline = list(
        await session.exec(
            select(Agent)
            .where(col(Agent.status) == "offline")
            .where(col(Agent.gateway_id).is_not(None))
            .where(col(Agent.updated_at) < threshold)
        )
    )
    stuck_agents = stuck_provisioning + stuck_online_unseen + stuck_updating + stuck_offline
    if not stuck_agents:
        return 0

    logger.info(
        "org_agent_reconciler.stuck_sweep found=%d "
        "(provisioning=%d online_unseen=%d updating=%d offline=%d) threshold_seconds=%d",
        len(stuck_agents),
        len(stuck_provisioning),
        len(stuck_online_unseen),
        len(stuck_updating),
        len(stuck_offline),
        settings.agent_stuck_provisioning_sweep_seconds,
    )
    now = utcnow()
    count = 0
    for agent in stuck_agents:
        try:
            if (
                agent.status == "offline"
                and agent.wake_attempts >= settings.agent_max_wake_attempts
            ):
                logger.info(
                    "org_agent_reconciler.stuck_skip_max_attempts "
                    "agent_id=%s status=%s wake_attempts=%d max_attempts=%d",
                    agent.id,
                    agent.status,
                    agent.wake_attempts,
                    settings.agent_max_wake_attempts,
                )
                continue
            enqueue_lifecycle_reconcile(
                QueuedAgentLifecycleReconcile(
                    agent_id=agent.id,
                    gateway_id=agent.gateway_id,
                    board_id=agent.board_id,
                    generation=agent.lifecycle_generation,
                    checkin_deadline_at=now,  # deadline in the past → fires immediately
                )
            )
            count += 1
            logger.info(
                "org_agent_reconciler.stuck_requeued agent_id=%s status=%s wake_attempts=%d",
                agent.id,
                agent.status,
                agent.wake_attempts,
            )
        except Exception:
            logger.exception(
                "org_agent_reconciler.stuck_requeue_error agent_id=%s",
                agent.id,
            )

    return count
