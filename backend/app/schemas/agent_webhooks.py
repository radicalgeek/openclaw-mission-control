"""Schemas for agent webhook configuration and payload capture."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BeforeValidator
from sqlmodel import SQLModel

from app.schemas.common import NonEmptyStr

RUNTIME_ANNOTATION_TYPES = (datetime, UUID, NonEmptyStr)

_HTTP_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _normalize_secret(v: str | None) -> str | None:
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None


def _normalize_signature_header(v: str | None) -> str | None:
    if v is None:
        return None
    stripped = v.strip()
    if not stripped:
        return None
    if not _HTTP_TOKEN_RE.match(stripped):
        msg = "signature_header must be a valid HTTP header name (ASCII token characters only)"
        raise ValueError(msg)
    return stripped


NormalizedSecret = Annotated[str | None, BeforeValidator(_normalize_secret)]
NormalizedSignatureHeader = Annotated[str | None, BeforeValidator(_normalize_signature_header)]


class AgentWebhookCreate(SQLModel):
    """Payload for creating an agent webhook."""

    description: NonEmptyStr
    enabled: bool = True
    secret: NormalizedSecret = None
    signature_header: NormalizedSignatureHeader = None


class AgentWebhookUpdate(SQLModel):
    """Payload for updating an agent webhook."""

    description: NonEmptyStr | None = None
    enabled: bool | None = None
    secret: NormalizedSecret = None
    signature_header: NormalizedSignatureHeader = None


class AgentWebhookRead(SQLModel):
    """Serialized agent webhook configuration."""

    id: UUID
    agent_id: UUID
    organization_id: UUID
    description: str
    enabled: bool
    has_secret: bool = False
    signature_header: str | None = None
    endpoint_path: str
    endpoint_url: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentWebhookPayloadRead(SQLModel):
    """Serialized stored agent webhook payload."""

    id: UUID
    agent_id: UUID
    webhook_id: UUID
    payload: dict[str, object] | list[object] | str | int | float | bool | None = None
    headers: dict[str, str] | None = None
    source_ip: str | None = None
    content_type: str | None = None
    received_at: datetime


class AgentWebhookIngestResponse(SQLModel):
    """Response payload for inbound agent webhook ingestion."""

    ok: bool = True
    agent_id: UUID
    webhook_id: UUID
