# ruff: noqa: INP001
"""Tests for PlanningMessagingService routing based on Plan.decomposition_target.

Verifies that:
- ``decomposition_target == "org_planner"`` routes to the configured org planner
  agent's session when the agent exists and is online.
- Missing / invalid org planner config falls back to the board lead session.
- ``decomposition_target == "board_lead"`` always routes to the board lead.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.agents import AGENT_TYPE_BOARD_LEAD, AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.plans import Plan
from app.services.openclaw.gateway_rpc import GatewayConfig as GatewayClientConfig
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.internal.session_keys import board_lead_session_key
from app.services.openclaw.planning_service import PlanningMessagingService


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _seed(
    session: AsyncSession,
    *,
    decomposition_target: str = "board_lead",
    lead_session: str | None = "lead-session-key",
    org_planner_session: str | None = "org-planner-session-key",
) -> tuple[Board, Plan, Agent | None, Agent | None]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    session.add_all(
        [
            Organization(id=org_id, name=f"org-{org_id}"),
            Gateway(
                id=gw_id,
                organization_id=org_id,
                name="gw",
                url="https://gw.example",
                token="t",
                workspace_root="/tmp/ws",
            ),
            Board(
                id=board_id,
                organization_id=org_id,
                gateway_id=gw_id,
                name="b",
                slug=f"b-{uuid4()}",
            ),
        ],
    )
    lead: Agent | None = None
    if lead_session is not None:
        lead = Agent(
            id=uuid4(),
            board_id=board_id,
            gateway_id=gw_id,
            name="Board Lead",
            agent_type=AGENT_TYPE_BOARD_LEAD,
            is_board_lead=True,
            openclaw_session_id=lead_session,
        )
        session.add(lead)

    org_planner: Agent | None = None
    if org_planner_session is not None:
        # Default to an online agent with a recent heartbeat so the
        # wake-on-idle path doesn't fire for routing tests; the wake path
        # has its own dedicated test.
        org_planner = Agent(
            id=uuid4(),
            gateway_id=gw_id,
            name="Org Planner",
            agent_type=AGENT_TYPE_STANDALONE,
            openclaw_session_id=org_planner_session,
            status="online",
            last_seen_at=utcnow(),
        )
        session.add(org_planner)

    plan = Plan(
        id=uuid4(),
        board_id=board_id,
        title="Plan",
        slug=f"plan-{uuid4()}",
        content="content",
        decomposition_target=decomposition_target,
    )
    session.add(plan)
    await session.commit()
    board = await session.get(Board, board_id)
    assert board is not None
    return board, plan, lead, org_planner


def _capture_dispatches() -> tuple[list[dict[str, Any]], Any]:
    """Patch out gateway plumbing so we can observe what session a dispatch goes to."""
    captured: list[dict[str, Any]] = []

    async def _fake_dispatch_gateway_message(self: Any, **kwargs: Any) -> None:
        captured.append(kwargs)

    async def _fake_require_gateway_config(self: Any, board: Board) -> tuple[Gateway, Any]:
        gateway = await Gateway.objects.by_id(board.gateway_id).first(self.session)
        assert gateway is not None
        return gateway, GatewayClientConfig(url=gateway.url, token=gateway.token)

    return captured, (
        patch(
            "app.services.openclaw.planning_service.AbstractGatewayMessagingService."
            "_dispatch_gateway_message",
            _fake_dispatch_gateway_message,
        ),
        patch(
            "app.services.openclaw.gateway_dispatch.GatewayDispatchService."
            "require_gateway_config_for_board",
            _fake_require_gateway_config,
        ),
    )


def _expected_lead_session(board: Board) -> str:
    return board_lead_session_key(board.id)


@pytest.mark.asyncio
async def test_plan_start_ensures_board_lead_instead_of_gateway_fallback() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, _plan, _lead, _org = await _seed(session, lead_session=None)
            captured, (p1, p2) = _capture_dispatches()
            ensure_calls: list[UUID] = []

            async def _fake_ensure(self: Any, *, request: Any) -> tuple[Agent, bool]:
                ensure_calls.append(request.board.id)
                return (
                    Agent(
                        id=uuid4(),
                        board_id=request.board.id,
                        gateway_id=request.gateway.id,
                        name="Lead Agent",
                        agent_type=AGENT_TYPE_BOARD_LEAD,
                        is_board_lead=True,
                        openclaw_session_id="created-lead-session",
                    ),
                    True,
                )

            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.OpenClawProvisioningService."
                    "ensure_board_lead_agent",
                    _fake_ensure,
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_start(board=board, prompt="write a plan")

        assert returned == "created-lead-session"
        assert ensure_calls == [board.id]
        assert captured[0]["session_key"] == "created-lead-session"
        assert captured[0]["agent_name"] == "Lead Agent"
        assert captured[0]["agent_name"] != "Gateway Agent"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plan_message_uses_ensured_lead_not_plan_session_fallback() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, _lead, _org = await _seed(session, lead_session=None)
            plan.session_key = "gateway-main-session"
            session.add(plan)
            await session.commit()
            captured, (p1, p2) = _capture_dispatches()

            async def _fake_ensure(self: Any, *, request: Any) -> tuple[Agent, bool]:
                return (
                    Agent(
                        id=uuid4(),
                        board_id=request.board.id,
                        gateway_id=request.gateway.id,
                        name="Lead Agent",
                        agent_type=AGENT_TYPE_BOARD_LEAD,
                        is_board_lead=True,
                        openclaw_session_id="created-lead-session",
                    ),
                    True,
                )

            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.OpenClawProvisioningService."
                    "ensure_board_lead_agent",
                    _fake_ensure,
                ),
            ):
                svc = PlanningMessagingService(session)
                await svc.dispatch_plan_message(board=board, plan=plan, message="revise it")

        assert captured[0]["session_key"] == "created-lead-session"
        assert captured[0]["session_key"] != "gateway-main-session"
        assert captured[0]["agent_name"] == "Lead Agent"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plan_start_reregisters_lead_once_when_runtime_config_lost() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, _plan, lead, _org = await _seed(session)
            assert lead is not None
            captured: list[dict[str, Any]] = []
            lifecycle_calls: list[UUID] = []

            async def _fake_dispatch_gateway_message(self: Any, **kwargs: Any) -> None:
                captured.append(kwargs)
                if len(captured) == 1:
                    raise OpenClawGatewayError("agent no longer exists in configuration")

            async def _fake_require_gateway_config(self: Any, board: Board) -> tuple[Gateway, Any]:
                gateway = await Gateway.objects.by_id(board.gateway_id).first(self.session)
                assert gateway is not None
                return gateway, GatewayClientConfig(url=gateway.url, token=gateway.token)

            async def _fake_ensure(self: Any, *, request: Any) -> tuple[Agent, bool]:
                return lead, False

            async def _fake_run_lifecycle(self: Any, **kwargs: Any) -> Agent:
                lifecycle_calls.append(kwargs["agent_id"])
                assert kwargs["action"] == "update"
                assert kwargs["force_bootstrap"] is False
                assert kwargs["reset_session"] is False
                assert kwargs["deliver_wakeup"] is False
                return lead

            with (
                patch(
                    "app.services.openclaw.planning_service.AbstractGatewayMessagingService."
                    "_dispatch_gateway_message",
                    _fake_dispatch_gateway_message,
                ),
                patch(
                    "app.services.openclaw.gateway_dispatch.GatewayDispatchService."
                    "require_gateway_config_for_board",
                    _fake_require_gateway_config,
                ),
                patch(
                    "app.services.openclaw.planning_service.OpenClawProvisioningService."
                    "ensure_board_lead_agent",
                    _fake_ensure,
                ),
                patch(
                    "app.services.openclaw.planning_service.AgentLifecycleOrchestrator."
                    "run_lifecycle",
                    _fake_run_lifecycle,
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_start(board=board, prompt="write a plan")

        assert returned == "lead-session-key"
        assert lifecycle_calls == [lead.id]
        assert [item["session_key"] for item in captured] == [
            "lead-session-key",
            "lead-session-key",
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_routes_to_org_planner_when_configured_and_target_set() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, _lead, org_planner = await _seed(
                session,
                decomposition_target="org_planner",
            )
            assert org_planner is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    str(org_planner.id),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose this plan",
                )
        assert returned == "org-planner-session-key"
        assert len(captured) == 1
        assert captured[0]["session_key"] == "org-planner-session-key"
        assert captured[0]["agent_name"] == "Org Planner"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_falls_back_to_board_lead_when_org_planner_unset() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, _org = await _seed(
                session,
                decomposition_target="org_planner",
                org_planner_session=None,
            )
            assert lead is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    "",
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        assert returned == _expected_lead_session(board)
        assert captured[0]["session_key"] == _expected_lead_session(board)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_falls_back_when_org_planner_agent_id_does_not_exist() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, _org = await _seed(
                session,
                decomposition_target="org_planner",
                org_planner_session=None,
            )
            assert lead is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    str(uuid4()),  # valid UUID but no matching agent
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        assert returned == _expected_lead_session(board)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_falls_back_when_org_planner_setting_is_invalid_uuid() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, _org = await _seed(
                session,
                decomposition_target="org_planner",
            )
            assert lead is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    "not-a-uuid",
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        assert returned == _expected_lead_session(board)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_target_board_lead_routes_to_lead_even_with_org_planner_configured() -> (
    None
):
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, org_planner = await _seed(
                session,
                decomposition_target="board_lead",
            )
            assert lead is not None
            assert org_planner is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    str(org_planner.id),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        # Even though an org planner is configured, the plan's target was
        # board_lead — that wins.
        assert returned == _expected_lead_session(board)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_routes_to_org_triager_when_target_set() -> None:
    """``decomposition_target == "org_triager"`` routes to the configured
    triager agent's session. Per role templates, decomposition is the
    triager's job (not the planner's)."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, _lead, _planner = await _seed(
                session,
                decomposition_target="org_triager",
                org_planner_session=None,
            )
            triager = Agent(
                id=uuid4(),
                gateway_id=board.gateway_id,
                name="Org Triager",
                agent_type=AGENT_TYPE_STANDALONE,
                openclaw_session_id="triager-session-key",
                status="online",
                last_seen_at=utcnow(),
            )
            session.add(triager)
            await session.commit()

            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_triager_agent_id",
                    str(triager.id),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose this plan",
                )
        assert returned == "triager-session-key"
        assert len(captured) == 1
        assert captured[0]["session_key"] == "triager-session-key"
        assert captured[0]["agent_name"] == "Org Triager"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_routes_to_current_triager_by_role_template_when_env_id_stale() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, _lead, _planner = await _seed(
                session,
                decomposition_target="org_triager",
                org_planner_session=None,
            )
            triager = Agent(
                id=uuid4(),
                gateway_id=board.gateway_id,
                name="Current Triager",
                agent_type=AGENT_TYPE_STANDALONE,
                openclaw_session_id="current-triager-session",
                identity_profile={"role_template": "triager"},
                status="online",
                last_seen_at=utcnow(),
            )
            session.add(triager)
            await session.commit()

            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_triager_agent_id",
                    str(uuid4()),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose this plan",
                )
        assert returned == "current-triager-session"
        assert captured[0]["session_key"] == "current-triager-session"
        assert captured[0]["agent_name"] == "Current Triager"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_falls_back_to_lead_when_triager_unavailable() -> None:
    """If decomposition_target=org_triager but no triager is configured/found,
    fall back to the board lead — same contract as org_planner."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, _planner = await _seed(
                session,
                decomposition_target="org_triager",
                org_planner_session=None,
            )
            assert lead is not None

            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_triager_agent_id",
                    "",  # no triager configured
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        assert returned == _expected_lead_session(board)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_does_not_run_lifecycle_pass_on_dispatch() -> None:
    """The dispatch path must not trigger a run_lifecycle pass on the
    standalone agent. Doing so puts the agent into ``updating`` and
    resets its session, which is wasteful and observed to interfere
    with the agent settling and replying to the queued prompt. The
    heartbeat-driven model handles work pickup; dispatch only delivers.
    """
    from datetime import timedelta

    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, _lead, org_planner = await _seed(
                session,
                decomposition_target="org_planner",
            )
            assert org_planner is not None
            # Even when the agent has been idle for hours, the dispatcher
            # must not initiate a lifecycle pass.
            org_planner.last_seen_at = utcnow() - timedelta(hours=2)
            org_planner.status = "online"
            session.add(org_planner)
            await session.commit()

            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    str(org_planner.id),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose this plan",
                )

        assert returned == "org-planner-session-key"
        # Exactly one dispatch, straight to the planner's session.
        assert len(captured) == 1
        assert captured[0]["session_key"] == "org-planner-session-key"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_decompose_falls_back_when_org_planner_has_no_session_yet() -> None:
    """An org planner that hasn't checked in yet (no openclaw_session_id) is skipped."""
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            board, plan, lead, _org = await _seed(
                session,
                decomposition_target="org_planner",
                org_planner_session=None,  # _seed will create no org_planner
            )
            # Manually create the org planner WITHOUT a session_id.
            offline_planner = Agent(
                id=uuid4(),
                gateway_id=board.gateway_id,
                name="Offline Org Planner",
                agent_type=AGENT_TYPE_STANDALONE,
                openclaw_session_id=None,
            )
            session.add(offline_planner)
            await session.commit()

            assert lead is not None
            captured, (p1, p2) = _capture_dispatches()
            with (
                p1,
                p2,
                patch(
                    "app.services.openclaw.planning_service.settings.org_planner_agent_id",
                    str(offline_planner.id),
                ),
            ):
                svc = PlanningMessagingService(session)
                returned = await svc.dispatch_plan_decompose(
                    board=board,
                    plan=plan,
                    prompt="decompose",
                )
        # Org planner exists but is offline → must fall back to board lead.
        assert returned == _expected_lead_session(board)
    finally:
        await engine.dispose()
