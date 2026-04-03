"""API endpoints for reading and writing agent workspace files via the gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import require_org_admin, require_org_member
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.schemas.agent_files import (
    AgentFileContent,
    AgentFileEntry,
    AgentFileList,
    AgentFileWrite,
)
from app.schemas.common import OkResponse
from app.services.activity_log import record_activity
from app.services.openclaw.gateway_resolver import gateway_client_config
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.internal.agent_key import agent_key as _agent_key
from app.services.openclaw.provisioning import OpenClawGatewayControlPlane

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

router = APIRouter(prefix="/agents", tags=["agents"])
logger = get_logger(__name__)

SESSION_DEP = Depends(get_session)
ORG_MEMBER_DEP = Depends(require_org_member)
ORG_ADMIN_DEP = Depends(require_org_admin)
RESET_SESSION_QUERY = Query(default=False)


async def _require_agent(
    agent_id: str,
    session: "AsyncSession",
    organization_id: UUID,
) -> Agent:
    """Load an agent by id and verify it belongs to the caller's organization."""
    agent = await Agent.objects.by_id(agent_id).first(session)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    gateway = await session.get(Gateway, agent.gateway_id)
    if gateway is None or gateway.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


async def _build_control_plane(
    agent: Agent,
    session: "AsyncSession",
) -> tuple[OpenClawGatewayControlPlane, str]:
    """Return a control plane + gateway agent id for the given agent."""
    gateway = await session.get(Gateway, agent.gateway_id)
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gateway not found for agent."
        )
    config = gateway_client_config(gateway)
    control_plane = OpenClawGatewayControlPlane(config)
    gw_agent_id = _agent_key(agent)
    return control_plane, gw_agent_id


def _extract_file_content(payload: Any, name: str) -> str:
    """Extract text content from an agents.files.get gateway response."""
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content
        # Some gateway versions nest under "file"
        file_obj = payload.get("file")
        if isinstance(file_obj, dict):
            content = file_obj.get("content")
            if isinstance(content, str):
                return content
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Gateway returned unexpected payload for file '{name}'.",
    )


# ---------------------------------------------------------------------------
# Phase 1 – Read endpoints (org member)
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/files", response_model=AgentFileList)
async def list_agent_files(
    agent_id: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_MEMBER_DEP,
) -> AgentFileList:
    """List workspace files for an agent.

    Proxies ``agents.files.list`` to the connected gateway.
    """
    agent = await _require_agent(agent_id, session, ctx.organization.id)
    control_plane, gw_agent_id = await _build_control_plane(agent, session)

    try:
        raw = await control_plane.list_agent_files(gw_agent_id)
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error listing files: {exc}",
        ) from exc

    entries: list[AgentFileEntry] = []
    for name, meta in raw.items():
        entries.append(
            AgentFileEntry(
                name=name,
                size=meta.get("size") if isinstance(meta, dict) else None,
                modified_at=str(meta.get("modified_at", "")) if isinstance(meta, dict) else None,
                missing=bool(meta.get("missing")) if isinstance(meta, dict) else False,
            )
        )
    entries.sort(key=lambda e: e.name)

    return AgentFileList(
        agent_id=UUID(agent_id),
        gateway_agent_id=gw_agent_id,
        files=entries,
    )


@router.get("/{agent_id}/files/{file_name:path}", response_model=AgentFileContent)
async def get_agent_file(
    agent_id: str,
    file_name: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_MEMBER_DEP,
) -> AgentFileContent:
    """Read the content of a single agent workspace file.

    Proxies ``agents.files.get`` to the connected gateway.
    AUTH_TOKEN values in TOOLS.md are redacted for security.
    """
    agent = await _require_agent(agent_id, session, ctx.organization.id)
    control_plane, gw_agent_id = await _build_control_plane(agent, session)

    try:
        payload = await control_plane.get_agent_file_payload(
            agent_id=gw_agent_id, name=file_name
        )
    except OpenClawGatewayError as exc:
        msg = str(exc).lower()
        if any(m in msg for m in ("not found", "no such file", "unknown file")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File '{file_name}' not found in agent workspace.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error reading file: {exc}",
        ) from exc

    raw_content = _extract_file_content(payload, file_name)
    # Redact auth tokens to avoid credential exposure in the UI
    safe_content = _redact_auth_token(raw_content)

    return AgentFileContent(
        agent_id=UUID(agent_id),
        gateway_agent_id=gw_agent_id,
        name=file_name,
        content=safe_content,
    )


def _redact_auth_token(content: str) -> str:
    """Replace AUTH_TOKEN= value in workspace files with a redacted placeholder."""
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("AUTH_TOKEN="):
            lines.append("AUTH_TOKEN=<redacted>")
        else:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2 – Write endpoints (org admin)
# ---------------------------------------------------------------------------


@router.put("/{agent_id}/files/{file_name:path}", response_model=AgentFileContent)
async def set_agent_file(
    agent_id: str,
    file_name: str,
    payload: AgentFileWrite,
    reset_session: bool = RESET_SESSION_QUERY,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> AgentFileContent:
    """Write content to an agent workspace file.

    Proxies ``agents.files.set`` to the connected gateway. Org-admin only.
    Pass ``?reset_session=true`` to trigger an agent session reset so it
    re-reads the workspace promptly.

    If the file is ``IDENTITY.md`` or ``SOUL.md`` the content is also stored
    as the per-agent template override on the ``Agent`` record so that future
    template syncs preserve the customisation.
    """
    agent = await _require_agent(agent_id, session, ctx.organization.id)
    control_plane, gw_agent_id = await _build_control_plane(agent, session)

    try:
        await control_plane.set_agent_file(
            agent_id=gw_agent_id, name=file_name, content=payload.content
        )
    except OpenClawGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error writing file: {exc}",
        ) from exc

    # Persist IDENTITY.md / SOUL.md edits as per-agent template overrides
    # so future template syncs preserve them.
    changed = False
    if file_name == "IDENTITY.md":
        agent.identity_template = payload.content
        changed = True
    elif file_name == "SOUL.md":
        agent.soul_template = payload.content
        changed = True

    if changed:
        from app.core.time import utcnow

        agent.updated_at = utcnow()
        session.add(agent)

    record_activity(
        session,
        event_type="agent.file.write",
        message=(
            f"Workspace file '{file_name}' updated for agent {agent.name} "
            f"(gateway agent id: {gw_agent_id})"
        ),
        agent_id=agent.id,
        board_id=agent.board_id,
    )
    await session.commit()

    if reset_session and agent.openclaw_session_id:
        try:
            await control_plane.reset_agent_session(agent.openclaw_session_id)
        except OpenClawGatewayError:
            logger.warning(
                "agent.file.write.session_reset_failed agent_id=%s", agent.id
            )

    return AgentFileContent(
        agent_id=UUID(agent_id),
        gateway_agent_id=gw_agent_id,
        name=file_name,
        content=payload.content,
    )


@router.delete("/{agent_id}/files/{file_name:path}", response_model=OkResponse)
async def delete_agent_file(
    agent_id: str,
    file_name: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete a file from an agent workspace.

    Proxies ``agents.files.delete`` to the connected gateway. Org-admin only.
    """
    agent = await _require_agent(agent_id, session, ctx.organization.id)
    control_plane, gw_agent_id = await _build_control_plane(agent, session)

    try:
        await control_plane.delete_agent_file(agent_id=gw_agent_id, name=file_name)
    except OpenClawGatewayError as exc:
        msg = str(exc).lower()
        if any(m in msg for m in ("not found", "no such file", "unknown file")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File '{file_name}' not found in agent workspace.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway error deleting file: {exc}",
        ) from exc

    record_activity(
        session,
        event_type="agent.file.delete",
        message=(
            f"Workspace file '{file_name}' deleted for agent {agent.name} "
            f"(gateway agent id: {gw_agent_id})"
        ),
        agent_id=agent.id,
        board_id=agent.board_id,
    )
    await session.commit()
    return OkResponse()
