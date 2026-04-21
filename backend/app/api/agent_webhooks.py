"""Agent webhook configuration and inbound payload ingestion endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import col, select

from app.api.deps import require_org_admin
from app.core.client_ip import get_client_ip
from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import webhook_ingest_limiter
from app.core.time import utcnow
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agent_webhooks import AgentWebhook, AgentWebhookPayload
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.schemas.agent_webhooks import (
    AgentWebhookCreate,
    AgentWebhookIngestResponse,
    AgentWebhookPayloadRead,
    AgentWebhookRead,
    AgentWebhookUpdate,
)
from app.schemas.common import OkResponse
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.organizations import OrganizationContext
from app.services.webhooks.queue import (
    QueuedAgentWebhookDelivery,
    enqueue_agent_webhook_delivery,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

# ---- per-agent management routes (org admin) --------------------------------
router = APIRouter(prefix="/agents/{agent_id}/webhooks", tags=["agent-webhooks"])
# ---- public ingest endpoint -------------------------------------------------
ingest_router = APIRouter(prefix="/webhooks/agent", tags=["agent-webhooks"])

SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)

logger = get_logger(__name__)


def _webhook_endpoint_path(agent_id: UUID, webhook_id: UUID) -> str:
    return f"/api/v1/webhooks/agent/{webhook_id}"


def _webhook_endpoint_url(endpoint_path: str) -> str | None:
    base_url = (settings.base_url or "").rstrip("/")
    if not base_url:
        return None
    return f"{base_url}{endpoint_path}"


def _to_webhook_read(webhook: AgentWebhook) -> AgentWebhookRead:
    endpoint_path = _webhook_endpoint_path(webhook.agent_id, webhook.id)
    return AgentWebhookRead(
        id=webhook.id,
        agent_id=webhook.agent_id,
        organization_id=webhook.organization_id,
        description=webhook.description,
        enabled=webhook.enabled,
        has_secret=bool(webhook.secret),
        signature_header=webhook.signature_header,
        endpoint_path=endpoint_path,
        endpoint_url=_webhook_endpoint_url(endpoint_path),
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
    )


def _to_payload_read(payload: AgentWebhookPayload) -> AgentWebhookPayloadRead:
    return AgentWebhookPayloadRead.model_validate(payload, from_attributes=True)


async def _require_agent_webhook(
    session: AsyncSession,
    *,
    agent_id: UUID,
    webhook_id: UUID,
) -> AgentWebhook:
    webhook = (
        await session.exec(
            select(AgentWebhook)
            .where(col(AgentWebhook.id) == webhook_id)
            .where(col(AgentWebhook.agent_id) == agent_id),
        )
    ).first()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return webhook


async def _require_standalone_agent(
    session: AsyncSession,
    *,
    agent_id: UUID,
    ctx: OrganizationContext,
) -> Agent:
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if agent.agent_type != AGENT_TYPE_STANDALONE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Agent webhooks are only supported for standalone agents",
        )
    from app.services.openclaw.policies import OpenClawAuthorizationPolicy

    OpenClawAuthorizationPolicy.require_gateway_in_org(
        gateway=None,
        organization_id=ctx.organization.id,
    )
    # Verify gateway belongs to org by checking agent's gateway
    from app.models.gateways import Gateway

    gateway = await Gateway.objects.by_id(agent.gateway_id).first(session)
    if gateway is None or gateway.organization_id != ctx.organization.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return agent


def _decode_payload(
    raw_body: bytes,
    *,
    content_type: str | None,
) -> dict[str, object] | list[object] | str | int | float | bool | None:
    if not raw_body:
        return {}
    body_text = raw_body.decode("utf-8", errors="replace")
    normalized = (content_type or "").lower()
    should_parse = (
        "application/json" in normalized
        or body_text.startswith(("{", "[", '"'))
        or body_text
        in {
            "true",
            "false",
        }
    )
    if should_parse:
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError:
            return body_text
        if isinstance(parsed, (dict, list, str, int, float, bool)) or parsed is None:
            return parsed
    return body_text


def _verify_signature(
    webhook: AgentWebhook,
    raw_body: bytes,
    request: Request,
) -> None:
    if not webhook.secret:
        return
    if webhook.signature_header:
        sig_header = request.headers.get(webhook.signature_header.lower())
    else:
        sig_header = request.headers.get("x-hub-signature-256") or request.headers.get(
            "x-webhook-signature"
        )
    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing webhook signature header.",
        )
    sig_value = sig_header
    if sig_value.lower().startswith("sha256="):
        sig_value = sig_value[7:]
    sig_value = sig_value.strip().lower()
    expected = hmac.new(
        webhook.secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig_value, expected.strip().lower()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )


_REDACTED_HEADERS = frozenset({"x-hub-signature-256", "x-webhook-signature", "authorization"})


def _captured_headers(
    request: Request,
    *,
    extra_redacted: str | None = None,
) -> dict[str, str] | None:
    redacted = _REDACTED_HEADERS
    if extra_redacted:
        redacted = redacted | {extra_redacted.lower()}
    captured: dict[str, str] = {}
    for header, value in request.headers.items():
        normalized = header.lower()
        if normalized in redacted:
            continue
        if normalized in {"content-type", "user-agent"} or normalized.startswith("x-"):
            captured[normalized] = value
    return captured or None


# ---- Management routes (org admin) ------------------------------------------


@router.get("", response_model=DefaultLimitOffsetPage[AgentWebhookRead])
async def list_agent_webhooks(
    agent_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[AgentWebhookRead]:
    """List webhooks configured for a standalone agent."""
    # Verify agent exists and belongs to org
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    statement = (
        select(AgentWebhook)
        .where(col(AgentWebhook.agent_id) == agent_id)
        .order_by(col(AgentWebhook.created_at).desc())
    )

    def _transform(items: Sequence[object]) -> Sequence[object]:
        webhooks = [item for item in items if isinstance(item, AgentWebhook)]
        return [_to_webhook_read(wh) for wh in webhooks]

    return await paginate(session, statement, transformer=_transform)


@router.post("", response_model=AgentWebhookRead)
async def create_agent_webhook(
    agent_id: UUID,
    payload: AgentWebhookCreate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentWebhookRead:
    """Create a webhook for a standalone agent."""
    agent = await _require_standalone_agent(session, agent_id=agent_id, ctx=ctx)
    webhook = AgentWebhook(
        agent_id=agent.id,
        organization_id=ctx.organization.id,
        description=payload.description,
        enabled=payload.enabled,
        secret=payload.secret,
        signature_header=payload.signature_header,
    )
    await crud.save(session, webhook)
    return _to_webhook_read(webhook)


@router.get("/{webhook_id}", response_model=AgentWebhookRead)
async def get_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentWebhookRead:
    """Get one agent webhook configuration."""
    webhook = await _require_agent_webhook(session, agent_id=agent_id, webhook_id=webhook_id)
    return _to_webhook_read(webhook)


@router.patch("/{webhook_id}", response_model=AgentWebhookRead)
async def update_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    payload: AgentWebhookUpdate,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AgentWebhookRead:
    """Update an agent webhook configuration."""
    webhook = await _require_agent_webhook(session, agent_id=agent_id, webhook_id=webhook_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(webhook, key, value)
    webhook.updated_at = utcnow()
    await crud.save(session, webhook)
    return _to_webhook_read(webhook)


@router.delete("/{webhook_id}", response_model=OkResponse)
async def delete_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OkResponse:
    """Delete an agent webhook configuration."""
    webhook = await _require_agent_webhook(session, agent_id=agent_id, webhook_id=webhook_id)
    await session.delete(webhook)
    await session.commit()
    return OkResponse()


@router.get(
    "/{webhook_id}/payloads", response_model=DefaultLimitOffsetPage[AgentWebhookPayloadRead]
)
async def list_agent_webhook_payloads(
    agent_id: UUID,
    webhook_id: UUID,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    session: AsyncSession = SESSION_DEP,
) -> LimitOffsetPage[AgentWebhookPayloadRead]:
    """List received payloads for an agent webhook."""
    await _require_agent_webhook(session, agent_id=agent_id, webhook_id=webhook_id)
    statement = (
        select(AgentWebhookPayload)
        .where(col(AgentWebhookPayload.agent_id) == agent_id)
        .where(col(AgentWebhookPayload.webhook_id) == webhook_id)
        .order_by(col(AgentWebhookPayload.received_at).desc())
    )

    def _transform(items: Sequence[object]) -> Sequence[object]:
        payloads = [item for item in items if isinstance(item, AgentWebhookPayload)]
        return [_to_payload_read(p) for p in payloads]

    return await paginate(session, statement, transformer=_transform)


# ---- Public ingest endpoint -------------------------------------------------


@ingest_router.post("/{webhook_id}", response_model=AgentWebhookIngestResponse)
async def ingest_agent_webhook(
    webhook_id: UUID,
    request: Request,
    session: AsyncSession = SESSION_DEP,
) -> AgentWebhookIngestResponse:
    """Public endpoint for receiving external webhook payloads destined for a standalone agent."""
    client_ip = get_client_ip(request)
    if not await webhook_ingest_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    webhook = (
        await session.exec(
            select(AgentWebhook)
            .where(col(AgentWebhook.id) == webhook_id)
            .where(col(AgentWebhook.enabled).is_(True)),
        )
    ).first()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    raw_body = await request.body()
    _verify_signature(webhook, raw_body, request)

    content_type = request.headers.get("content-type")
    parsed_payload = _decode_payload(raw_body, content_type=content_type)
    headers = _captured_headers(
        request,
        extra_redacted=webhook.signature_header,
    )
    source_ip = get_client_ip(request)

    payload = AgentWebhookPayload(
        agent_id=webhook.agent_id,
        webhook_id=webhook.id,
        payload=parsed_payload,
        headers=headers,
        source_ip=source_ip,
        content_type=content_type,
        received_at=utcnow(),
    )
    await crud.save(session, payload)
    await session.commit()
    await session.refresh(payload)

    enqueue_agent_webhook_delivery(
        QueuedAgentWebhookDelivery(
            agent_id=webhook.agent_id,
            webhook_id=webhook.id,
            payload_id=payload.id,
            received_at=payload.received_at,
        )
    )

    logger.info(
        "agent_webhook.ingest.accepted",
        extra={
            "agent_id": str(webhook.agent_id),
            "webhook_id": str(webhook_id),
            "payload_id": str(payload.id),
        },
    )
    return AgentWebhookIngestResponse(
        ok=True,
        agent_id=webhook.agent_id,
        webhook_id=webhook.id,
    )
