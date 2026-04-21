"""Tests for the branding API endpoints (deployment + org overrides)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.branding import router as branding_router
from app.api.deps import require_org_admin, require_org_member
from app.db.session import get_session
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.services.organizations import OrganizationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_app(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    org_ctx: OrganizationContext,
) -> FastAPI:
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(branding_router)
    app.include_router(api)

    async def _session_override():
        async with session_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[require_org_member] = lambda: org_ctx
    app.dependency_overrides[require_org_admin] = lambda: org_ctx
    return app


async def _seed_org(
    session: AsyncSession,
    *,
    branding_overrides: dict | None = None,
) -> Organization:
    org = Organization(
        id=uuid4(),
        name="test-org",
        branding_overrides=branding_overrides,
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_deployment_branding() -> None:
    """GET /api/v1/branding returns deployment defaults without auth."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    org = Organization(id=uuid4(), name="any")
    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/branding")
        assert resp.status_code == 200
        data = resp.json()
        assert "product_name" in data
        assert "company_name" in data
        assert "full_title" in data
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_org_branding_no_overrides() -> None:
    """GET /api/v1/organizations/me/branding returns deployment defaults if no overrides."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(s)

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="member")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/organizations/me/branding")
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_org_branding_with_overrides() -> None:
    """Org branding merges overrides over deployment defaults."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(s, branding_overrides={"product_name": "CustomProduct"})

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="member")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/organizations/me/branding")
        assert resp.status_code == 200
        assert resp.json()["product_name"] == "CustomProduct"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_org_branding() -> None:
    """PATCH /api/v1/organizations/me/branding stores overrides."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(s)

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/v1/organizations/me/branding",
                json={"product_name": "NewProduct", "accent_color": "#ff0000"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] == "NewProduct"
        assert data["accent_color"] == "#ff0000"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_null_clears_override() -> None:
    """PATCH with explicit null removes that key from overrides."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(s, branding_overrides={"product_name": "Old"})

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/v1/organizations/me/branding",
                json={"product_name": None},
            )
        assert resp.status_code == 200
        from app.core.branding import get_branding

        assert resp.json()["product_name"] == get_branding().product_name
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_resets_branding() -> None:
    """DELETE /api/v1/organizations/me/branding clears all overrides."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(
            s,
            branding_overrides={
                "product_name": "Override",
                "accent_color": "#123456",
            },
        )

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/v1/organizations/me/branding")
        assert resp.status_code == 200
        from app.core.branding import get_branding

        data = resp.json()
        assert data["product_name"] == get_branding().product_name
        assert data["accent_color"] == get_branding().accent_color
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patch_partial_preserves_other_overrides() -> None:
    """PATCH with only one field preserves other existing overrides."""
    engine = await _make_engine()
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as s:
        org = await _seed_org(
            s,
            branding_overrides={"product_name": "Keep", "accent_color": "#aaa"},
        )

    member = OrganizationMember(organization_id=org.id, user_id=uuid4(), role="admin")
    ctx = OrganizationContext(organization=org, member=member)
    app = _build_app(session_maker, org_ctx=ctx)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/v1/organizations/me/branding",
                json={"accent_color": "#bbb"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_name"] == "Keep"
        assert data["accent_color"] == "#bbb"
    finally:
        await engine.dispose()
