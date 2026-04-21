"""Agent audit log listing and export endpoints."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_
from sqlmodel import col, select

from app.api.deps import require_audit_access, require_compliance_export
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agent_audit_log import AgentAuditLog
from app.schemas.audit import AuditLogRead
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/audit", tags=["audit"])

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_audit_access)
ORG_ADMIN_DEP = Depends(require_compliance_export)

_RUNTIME_TYPE_REFERENCES = (UUID, datetime)


@router.get("", response_model=DefaultLimitOffsetPage[AuditLogRead], tags=["audit"])
async def list_audit_log(
    agent_id: UUID | None = Query(default=None),
    board_id: UUID | None = Query(default=None),
    event_category: str | None = Query(default=None),
    source: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_MEMBER_DEP,
) -> "LimitOffsetPage[AuditLogRead]":
    """Paginated audit trail with optional filters."""
    filters = [col(AgentAuditLog.organization_id) == ctx.organization.id]
    if agent_id is not None:
        filters.append(col(AgentAuditLog.agent_id) == agent_id)
    if board_id is not None:
        filters.append(col(AgentAuditLog.board_id) == board_id)
    if event_category is not None:
        filters.append(col(AgentAuditLog.event_category) == event_category)
    if source is not None:
        filters.append(col(AgentAuditLog.source) == source)
    if since is not None:
        filters.append(col(AgentAuditLog.created_at) >= since)
    if until is not None:
        filters.append(col(AgentAuditLog.created_at) <= until)

    stmt = (
        select(AgentAuditLog).where(and_(*filters)).order_by(col(AgentAuditLog.created_at).desc())
    )

    def _to_read(rows: Sequence[Any]) -> Sequence[AuditLogRead]:
        return [AuditLogRead.model_validate(row, from_attributes=True) for row in rows]

    return await paginate(session, stmt, transformer=_to_read)


@router.get("/export", tags=["audit"])
async def export_audit_log(
    format: str = Query(default="csv"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    event_category: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    session: "AsyncSession" = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Response:
    """Export audit records as CSV or JSON for compliance evidence."""
    filters = [col(AgentAuditLog.organization_id) == ctx.organization.id]
    if agent_id is not None:
        filters.append(col(AgentAuditLog.agent_id) == agent_id)
    if event_category is not None:
        filters.append(col(AgentAuditLog.event_category) == event_category)
    if since is not None:
        filters.append(col(AgentAuditLog.created_at) >= since)
    if until is not None:
        filters.append(col(AgentAuditLog.created_at) <= until)

    stmt = select(AgentAuditLog).where(and_(*filters)).order_by(col(AgentAuditLog.created_at).asc())
    rows = (await session.exec(stmt)).all()

    if format == "json":
        import json

        data = [
            AuditLogRead.model_validate(r, from_attributes=True).model_dump(mode="json")
            for r in rows
        ]
        return Response(
            content=json.dumps(data, default=str),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit_export.json"'},
        )

    # Default: CSV
    output = io.StringIO()
    fieldnames = [
        "id",
        "created_at",
        "event_category",
        "event_action",
        "source",
        "actor_type",
        "actor_id",
        "agent_id",
        "board_id",
        "task_id",
        "session_key",
        "model_id",
        "token_input",
        "token_output",
        "cost_usd",
        "correlation_id",
        "ip_address",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        r = AuditLogRead.model_validate(row, from_attributes=True)
        writer.writerow(r.model_dump(mode="json", include=set(fieldnames)))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_export.csv"'},
    )
