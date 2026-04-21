"""Branding API endpoints — deployment defaults and per-org overrides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from app.api.deps import require_org_admin, require_org_member
from app.core.branding import BrandingConfig, get_branding
from app.db.session import get_session
from app.models.organizations import Organization
from app.schemas.branding import BrandingRead, BrandingUpdate
from app.services.organizations import OrganizationContext

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["branding"])

SESSION_DEP = Depends(get_session)


def _config_to_read(
    config: BrandingConfig, overrides: dict[str, Any] | None = None
) -> BrandingRead:
    """Merge deployment config with optional org overrides into a BrandingRead."""
    base = config.model_dump()
    if overrides:
        for key, value in overrides.items():
            if key in base and value is not None:
                base[key] = value
    return BrandingRead(**base)


@router.get(
    "/branding",
    response_model=BrandingRead,
    summary="Get deployment branding",
    description="Returns deployment-wide branding defaults. No authentication required.",
)
def get_deployment_branding() -> BrandingRead:
    """Return the deployment-wide branding config from branding.yaml."""
    return _config_to_read(get_branding())


@router.get(
    "/organizations/me/branding",
    response_model=BrandingRead,
    summary="Get organization branding",
    description="Returns the active organization's branding (deployment defaults merged with org overrides).",
)
async def get_org_branding(
    ctx: OrganizationContext = Depends(require_org_member),
    session: "AsyncSession" = SESSION_DEP,
) -> BrandingRead:
    """Return merged branding for the active organization."""
    org = await session.get(Organization, ctx.organization.id)
    overrides = org.branding_overrides if org else None
    return _config_to_read(get_branding(), overrides)


@router.patch(
    "/organizations/me/branding",
    response_model=BrandingRead,
    summary="Update organization branding",
    description="Update the active organization's branding overrides. Admin or owner role required.",
)
async def update_org_branding(
    payload: BrandingUpdate,
    ctx: OrganizationContext = Depends(require_org_admin),
    session: "AsyncSession" = SESSION_DEP,
) -> BrandingRead:
    """Persist org-level branding overrides."""
    from app.core.time import utcnow

    org = await session.get(Organization, ctx.organization.id)
    if org is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    current: dict[str, Any] = dict(org.branding_overrides or {})
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            # Explicitly setting a field to null clears that override
            current.pop(key, None)
        else:
            current[key] = value
    org.branding_overrides = current if current else None
    org.updated_at = utcnow()
    session.add(org)
    await session.commit()
    await session.refresh(org)

    return _config_to_read(get_branding(), org.branding_overrides)


@router.delete(
    "/organizations/me/branding",
    response_model=BrandingRead,
    summary="Reset organization branding",
    description="Clear all org-level branding overrides, reverting to deployment defaults.",
)
async def reset_org_branding(
    ctx: OrganizationContext = Depends(require_org_admin),
    session: "AsyncSession" = SESSION_DEP,
) -> BrandingRead:
    """Clear all org-level branding overrides."""
    from app.core.time import utcnow

    org = await session.get(Organization, ctx.organization.id)
    if org is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org.branding_overrides = None
    org.updated_at = utcnow()
    session.add(org)
    await session.commit()
    await session.refresh(org)

    return _config_to_read(get_branding())
