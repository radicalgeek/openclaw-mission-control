"""API endpoints for per-board and org-level Jinja2 template overrides (Phase 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from jinja2 import DebugUndefined, Environment, TemplateSyntaxError
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.api.deps import require_org_admin
from app.core.time import utcnow
from app.db.session import get_session
from app.models.agents import Agent
from app.models.board_templates import BoardTemplate
from app.models.boards import Board
from app.models.gateways import Gateway
from app.schemas.board_templates import (
    BoardTemplatePreviewRequest,
    BoardTemplatePreviewResponse,
    BoardTemplateRead,
    BoardTemplateUpsert,
)
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.openclaw.constants import DEFAULT_GATEWAY_FILES, LEAD_GATEWAY_FILES

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext

# Board-scoped routes: /boards/{board_id}/templates
router = APIRouter(prefix="/boards", tags=["boards"])
# Org-level routes: /org-templates
org_router = APIRouter(prefix="/org-templates", tags=["organizations"])
SESSION_DEP = Depends(get_session)
ORG_ADMIN_DEP = Depends(require_org_admin)

# All file names that can have templates
VALID_FILE_NAMES = DEFAULT_GATEWAY_FILES | LEAD_GATEWAY_FILES


def _to_read(bt: BoardTemplate, *, source: str = "board") -> BoardTemplateRead:
    return BoardTemplateRead(
        id=bt.id,
        organization_id=bt.organization_id,
        board_id=bt.board_id,
        file_name=bt.file_name,
        template_content=bt.template_content,
        description=bt.description,
        created_by=bt.created_by,
        created_at=bt.created_at,
        updated_at=bt.updated_at,
        source=source,
    )


async def _require_board(board_id: str, session: "AsyncSession", org_id: UUID) -> Board:
    board = await Board.objects.by_id(board_id).first(session)
    if board is None or board.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found.")
    return board


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/{board_id}/templates", response_model=list[BoardTemplateRead])
async def list_board_templates(
    board_id: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> list[BoardTemplateRead]:
    """List template overrides for this board, including org-wide fallbacks.

    Outer join logic: returns board-level overrides first; for any file_name not
    overridden at board level, returns the org-wide default if one exists.
    """
    board = await _require_board(board_id, session, ctx.organization.id)

    # Fetch board-level overrides
    board_results = await session.exec(
        select(BoardTemplate)
        .where(col(BoardTemplate.organization_id) == ctx.organization.id)
        .where(col(BoardTemplate.board_id) == board.id)
    )
    board_tmpl_by_file: dict[str, BoardTemplate] = {bt.file_name: bt for bt in board_results}

    # Fetch org-wide defaults (board_id IS NULL)
    org_results = await session.exec(
        select(BoardTemplate)
        .where(col(BoardTemplate.organization_id) == ctx.organization.id)
        .where(col(BoardTemplate.board_id).is_(None))
    )
    org_tmpl_by_file: dict[str, BoardTemplate] = {bt.file_name: bt for bt in org_results}

    merged: list[BoardTemplateRead] = []
    seen: set[str] = set()

    for file_name, bt in board_tmpl_by_file.items():
        merged.append(_to_read(bt, source="board"))
        seen.add(file_name)

    for file_name, bt in org_tmpl_by_file.items():
        if file_name not in seen:
            merged.append(_to_read(bt, source="org"))

    merged.sort(key=lambda t: t.file_name)
    return merged


@router.put("/{board_id}/templates/{file_name}", response_model=BoardTemplateRead)
async def upsert_board_template(
    board_id: str,
    file_name: str,
    payload: BoardTemplateUpsert,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplateRead:
    """Create or update a template override for a specific board.

    Validates Jinja2 syntax before saving. The file_name must be one of the
    known workspace file names (IDENTITY.md, SOUL.md, TOOLS.md, etc.).
    """
    board = await _require_board(board_id, session, ctx.organization.id)

    if file_name not in VALID_FILE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Invalid file_name '{file_name}'. Valid names: {sorted(VALID_FILE_NAMES)}"
            ),
        )

    _validate_jinja_syntax(payload.template_content)

    # Upsert: update existing or insert new
    existing = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id) == board.id)
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    now = utcnow()
    if existing is not None:
        existing.template_content = payload.template_content
        existing.description = payload.description
        existing.updated_at = now
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return _to_read(existing, source="board")

    bt = BoardTemplate(
        organization_id=ctx.organization.id,
        board_id=board.id,
        file_name=file_name,
        template_content=payload.template_content,
        description=payload.description,
        created_by=ctx.member.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(bt)
    try:
        await session.commit()
        await session.refresh(bt)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Template already exists."
        )
    return _to_read(bt, source="board")


@router.get("/{board_id}/templates/{file_name}", response_model=BoardTemplateRead)
async def get_board_template(
    board_id: str,
    file_name: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplateRead:
    """Get a single template override for a board (board-level or org-wide fallback)."""
    board = await _require_board(board_id, session, ctx.organization.id)

    bt = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id) == board.id)
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    if bt is not None:
        return _to_read(bt, source="board")

    # Check org-wide default
    org_bt = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id).is_(None))
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    if org_bt is not None:
        return _to_read(org_bt, source="org")

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No template override found for '{file_name}'.",
    )


@router.delete("/{board_id}/templates/{file_name}", response_model=BoardTemplateRead)
async def delete_board_template(
    board_id: str,
    file_name: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplateRead:
    """Delete the board-level template override for a file.

    After deletion the org-wide default (if any) or built-in template will be used.
    Returns the deleted template for reference.
    """
    board = await _require_board(board_id, session, ctx.organization.id)

    bt = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id) == board.id)
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    if bt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No board-level template override found for '{file_name}'.",
        )

    read = _to_read(bt, source="board")
    await session.delete(bt)
    await session.commit()
    return read


@router.post("/{board_id}/templates/{file_name}/preview", response_model=BoardTemplatePreviewResponse)
async def preview_board_template(
    board_id: str,
    file_name: str,
    payload: BoardTemplatePreviewRequest,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplatePreviewResponse:
    """Render a Jinja2 template and return the output without writing anything.

    If ``agent_id`` is provided the template is rendered with real board/agent context
    (auth_token replaced with a placeholder). Otherwise a stub context is used for
    syntax-only validation.
    """
    await _require_board(board_id, session, ctx.organization.id)

    _validate_jinja_syntax(payload.template_content)
    warnings: list[str] = []

    if payload.agent_id is not None:
        context, warn = await _build_preview_context(
            session=session,
            agent_id=payload.agent_id,
            organization_id=ctx.organization.id,
        )
        warnings.extend(warn)
    else:
        context = _stub_context()
        warnings.append(
            "No agent_id supplied — rendered with stub context. "
            "Pass agent_id for a real preview."
        )

    try:
        env = Environment(undefined=DebugUndefined, autoescape=False, keep_trailing_newline=True)
        rendered = env.from_string(payload.template_content).render(**context).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Template render error: {exc}",
        ) from exc

    return BoardTemplatePreviewResponse(rendered=rendered, warnings=warnings)


# ---------------------------------------------------------------------------
# Org-wide template management (no board scope)
# These live under /org-templates to avoid conflicting with /boards/{board_id}
# ---------------------------------------------------------------------------


@org_router.get("", response_model=list[BoardTemplateRead])
async def list_org_templates(
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> list[BoardTemplateRead]:
    """List org-wide template overrides (board_id IS NULL)."""
    results = await session.exec(
        select(BoardTemplate)
        .where(col(BoardTemplate.organization_id) == ctx.organization.id)
        .where(col(BoardTemplate.board_id).is_(None))
        .order_by(col(BoardTemplate.file_name))
    )
    return [_to_read(bt, source="org") for bt in results]


@org_router.put("/{file_name}", response_model=BoardTemplateRead)
async def upsert_org_template(
    file_name: str,
    payload: BoardTemplateUpsert,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplateRead:
    """Create or update an org-wide template override (applies to all boards)."""
    if file_name not in VALID_FILE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid file_name '{file_name}'. Valid names: {sorted(VALID_FILE_NAMES)}",
        )

    _validate_jinja_syntax(payload.template_content)

    existing = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id).is_(None))
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    now = utcnow()
    if existing is not None:
        existing.template_content = payload.template_content
        existing.description = payload.description
        existing.updated_at = now
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return _to_read(existing, source="org")

    bt = BoardTemplate(
        organization_id=ctx.organization.id,
        board_id=None,
        file_name=file_name,
        template_content=payload.template_content,
        description=payload.description,
        created_by=ctx.member.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(bt)
    await session.commit()
    await session.refresh(bt)
    return _to_read(bt, source="org")


@org_router.delete("/{file_name}", response_model=BoardTemplateRead)
async def delete_org_template(
    file_name: str,
    session: "AsyncSession" = SESSION_DEP,
    ctx: "OrganizationContext" = ORG_ADMIN_DEP,
) -> BoardTemplateRead:
    """Delete an org-wide template override."""
    bt = (
        await session.exec(
            select(BoardTemplate)
            .where(col(BoardTemplate.organization_id) == ctx.organization.id)
            .where(col(BoardTemplate.board_id).is_(None))
            .where(col(BoardTemplate.file_name) == file_name)
        )
    ).first()

    if bt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No org-wide template override found for '{file_name}'.",
        )

    read = _to_read(bt, source="org")
    await session.delete(bt)
    await session.commit()
    return read


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_jinja_syntax(content: str) -> None:
    """Raise HTTP 422 if the template content has a Jinja2 syntax error."""
    try:
        env = Environment(undefined=DebugUndefined, autoescape=False)
        env.parse(content)
    except TemplateSyntaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Jinja2 syntax error: {exc}",
        ) from exc


def _stub_context() -> dict[str, Any]:
    """Return a minimal stub render context for syntax-check previews."""
    return {
        "agent_name": "<agent_name>",
        "agent_id": "<agent_id>",
        "board_id": "<board_id>",
        "board_name": "<board_name>",
        "board_type": "<board_type>",
        "board_objective": "",
        "board_success_metrics": "{}",
        "board_target_date": "",
        "board_goal_confirmed": "false",
        "board_rule_require_approval_for_done": "false",
        "board_rule_require_review_before_done": "false",
        "board_rule_comment_required_for_review": "false",
        "board_rule_block_status_changes_with_pending_approval": "false",
        "board_rule_only_lead_can_change_status": "false",
        "board_rule_max_agents": "10",
        "is_board_lead": "false",
        "is_platform_board": "false",
        "is_main_agent": "false",
        "session_key": "<session_key>",
        "workspace_path": "<workspace_path>",
        "base_url": "<base_url>",
        "auth_token": "<auth_token>",
        "main_session_key": "<main_session_key>",
        "workspace_root": "<workspace_root>",
        "user_name": "<user_name>",
        "user_preferred_name": "<user_preferred_name>",
        "user_pronouns": "",
        "user_timezone": "",
        "user_notes": "",
        "user_context": "",
        "identity_role": "Generalist",
        "identity_communication_style": "direct",
        "identity_emoji": ":gear:",
        "identity_autonomy_level": "",
        "identity_verbosity": "",
        "identity_output_format": "",
        "identity_update_cadence": "",
        "identity_purpose": "",
        "identity_personality": "",
        "identity_custom_instructions": "",
        "directory_role_soul_markdown": "",
        "directory_role_soul_source_url": "",
        "has_platform_board": "false",
        "platform_board_name": "",
    }


async def _build_preview_context(
    *,
    session: "AsyncSession",
    agent_id: UUID,
    organization_id: UUID,
) -> tuple[dict[str, Any], list[str]]:
    """Build a real render context for an agent, redacting the auth token."""
    from app.services.openclaw.provisioning import _build_context, _build_main_context

    warnings: list[str] = []
    agent = await Agent.objects.by_id(str(agent_id)).first(session)
    if agent is None:
        warnings.append(f"Agent {agent_id} not found. Falling back to stub context.")
        return _stub_context(), warnings

    gateway = await session.get(Gateway, agent.gateway_id)
    if gateway is None or gateway.organization_id != organization_id:
        warnings.append("Agent gateway not found. Falling back to stub context.")
        return _stub_context(), warnings

    if agent.board_id is None:
        # Main agent — no board context
        context: dict[str, Any] = _build_main_context(
            agent=agent,
            gateway=gateway,
            auth_token="<auth_token>",
            user=None,
        )
        return context, warnings

    board = await Board.objects.by_id(str(agent.board_id)).first(session)
    if board is None:
        warnings.append("Agent board not found. Falling back to stub context.")
        return _stub_context(), warnings

    context = _build_context(
        agent=agent,
        board=board,
        gateway=gateway,
        auth_token="<auth_token>",
        user=None,
    )
    return context, warnings
