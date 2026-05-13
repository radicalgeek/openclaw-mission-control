# ruff: noqa: INP001
"""Tests for POST /boards/{id}/sprints/{id}/run-review."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    get_board_for_user_read,
    get_board_for_user_write,
    require_user_auth,
)
from app.api.sprints import router as sprints_router
from app.core.auth import AuthContext
from app.core.time import utcnow
from app.db.session import get_session
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.models.sprints import Sprint, SprintReview, SprintTicket
from app.models.tasks import Task
from app.services.openclaw.internal.session_keys import standalone_agent_session_key
from app.models.users import User


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_app(session_maker: async_sessionmaker[AsyncSession], *, user: User) -> FastAPI:
    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(sprints_router)
    app.include_router(api)

    async def _session_override():
        async with session_maker() as s:
            yield s

    async def _board_override(
        board_id: str,
        session: AsyncSession = Depends(get_session),
    ) -> Board:
        from fastapi import HTTPException
        from fastapi import status as http_status

        board = await Board.objects.by_id(UUID(board_id)).first(session)
        if board is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND)
        return board

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_board_for_user_read] = _board_override
    app.dependency_overrides[get_board_for_user_write] = _board_override
    app.dependency_overrides[require_user_auth] = lambda: AuthContext(actor_type="user", user=user)
    return app


async def _seed_with_sprint_and_reviewers(
    session: AsyncSession,
    *,
    sprint_status: str = "active",
    with_qa: bool = True,
    with_security: bool = True,
    with_architecture: bool = True,
) -> tuple[User, Board, Sprint, dict[str, Agent]]:
    org_id = uuid4()
    gw_id = uuid4()
    board_id = uuid4()
    sprint_id = uuid4()
    user = User(id=uuid4(), clerk_user_id=f"cu_{uuid4()}", email=f"u{uuid4()}@x.test")

    reviewers: dict[str, Agent] = {}

    def _make_reviewer(name: str, role_template: str) -> Agent:
        return Agent(
            id=uuid4(),
            gateway_id=gw_id,
            name=name,
            agent_type=AGENT_TYPE_STANDALONE,
            openclaw_session_id=f"{name.lower()}-session",
            identity_profile={"role_template": role_template},
        )

    objects: list[object] = [
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
        user,
    ]
    if with_qa:
        reviewers["qa"] = _make_reviewer("QA", "quality_reviewer")
        objects.append(reviewers["qa"])
    if with_security:
        reviewers["security"] = _make_reviewer("Security", "security_reviewer")
        objects.append(reviewers["security"])
    if with_architecture:
        reviewers["architecture"] = _make_reviewer("Architecture", "architecture_reviewer")
        objects.append(reviewers["architecture"])

    sprint = Sprint(
        id=sprint_id,
        organization_id=org_id,
        board_id=board_id,
        name="Sprint",
        slug=f"sprint-{uuid4()}",
        status=sprint_status,
        position=0,
    )
    objects.append(sprint)

    task_id = uuid4()
    task = Task(id=task_id, board_id=board_id, title="Done thing", status="done")
    objects.append(task)
    objects.append(SprintTicket(sprint_id=sprint_id, task_id=task_id, position=0))

    session.add_all(objects)
    await session.commit()
    board = await session.get(Board, board_id)
    fresh_sprint = await session.get(Sprint, sprint_id)
    assert board is not None
    assert fresh_sprint is not None
    return user, board, fresh_sprint, reviewers


def _capture() -> tuple[list[dict[str, Any]], Any, Any]:
    captured: list[dict[str, Any]] = []

    async def _fake_dispatch(self: Any, **kwargs: Any) -> None:
        captured.append(kwargs)

    async def _fake_config(self: Any, board: Board) -> tuple[Any, Any]:
        return object(), object()

    return (
        captured,
        patch(
            "app.services.openclaw.planning_service.AbstractGatewayMessagingService."
            "_dispatch_gateway_message",
            _fake_dispatch,
        ),
        patch(
            "app.services.openclaw.gateway_dispatch.GatewayDispatchService."
            "require_gateway_config_for_board",
            _fake_config,
        ),
    )


@pytest.mark.asyncio
async def test_run_review_dispatches_to_all_three_reviewers_when_configured() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(session)
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_qa_reviewer_agent_id", str(reviewers["qa"].id)),
                patch(
                    "app.api.sprints.settings.org_security_reviewer_agent_id",
                    str(reviewers["security"].id),
                ),
                patch(
                    "app.api.sprints.settings.org_architecture_reviewer_agent_id",
                    str(reviewers["architecture"].id),
                ),
            ):
                resp = await c.post(
                    f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
                )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(body["dispatched_reviewers"]) == ["architecture", "qa", "security"]
        assert body["skipped_reviewers"] == []
        # 3 dispatches, one per reviewer
        sessions_dispatched = [c["session_key"] for c in captured]
        assert sorted(sessions_dispatched) == sorted(
            [
                standalone_agent_session_key(reviewers["qa"].id),
                standalone_agent_session_key(reviewers["security"].id),
                standalone_agent_session_key(reviewers["architecture"].id),
            ]
        )
        async with sm() as session:
            refreshed = await session.get(Sprint, sprint.id)
            assert refreshed is not None
            assert refreshed.status == "reviewing"
            rows = (
                await session.exec(select(SprintReview).where(SprintReview.sprint_id == sprint.id))
            ).all()
            assert sorted(row.role for row in rows) == ["architecture", "qa", "security"]
            assert {row.status for row in rows} == {"pending"}
        prompts = [call["message"] for call in captured]
        assert all("Backlog tickets already planned:" in prompt for prompt in prompts)
        assert all("Future sprint tickets already planned:" in prompt for prompt in prompts)
        assert all(
            "Do not request changes for work that is already represented" in prompt
            for prompt in prompts
        )
        assert all(
            "Only block the sprint for a current-sprint acceptance failure" in prompt
            for prompt in prompts
        )
        assert all(
            "A gap is not unplanned just because this sprint touched adjacent" in prompt
            for prompt in prompts
        )
        assert all(
            "Do not create a current-sprint remediation ticket for a gap" in prompt
            for prompt in prompts
        )
        assert all("newer task comments, done remediation tickets" in prompt for prompt in prompts)
        assert all("do not block on a stale issue" in prompt for prompt in prompts)
        assert all(
            "one remediation ticket per distinct blocking finding" in prompt for prompt in prompts
        )
        assert all("Do not bundle unrelated remediation work" in prompt for prompt in prompts)
        assert all("/review-update" in prompt for prompt in prompts)
        assert all("only accepts POST" in prompt for prompt in prompts)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_review_repairs_stale_reviewer_session_key_before_dispatch() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                with_qa=False,
                with_architecture=False,
            )
            security = reviewers["security"]
            security.openclaw_session_id = f"agent:mc-gateway-{board.gateway_id}:main"
            session.add(security)
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_qa_reviewer_agent_id", ""),
                patch(
                    "app.api.sprints.settings.org_security_reviewer_agent_id",
                    str(reviewers["security"].id),
                ),
                patch("app.api.sprints.settings.org_architecture_reviewer_agent_id", ""),
            ):
                resp = await c.post(
                    f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
                )
        assert resp.status_code == 200, resp.text
        assert [call["session_key"] for call in captured] == [
            standalone_agent_session_key(reviewers["security"].id)
        ]
        async with sm() as session:
            repaired = await session.get(Agent, reviewers["security"].id)
            assert repaired is not None
            assert repaired.openclaw_session_id == standalone_agent_session_key(repaired.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_review_skips_unconfigured_reviewers() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                with_security=False,
                with_architecture=False,
            )
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch(
                    "app.api.sprints.settings.org_qa_reviewer_agent_id",
                    str(reviewers["qa"].id),
                ),
                patch("app.api.sprints.settings.org_security_reviewer_agent_id", ""),
                patch("app.api.sprints.settings.org_architecture_reviewer_agent_id", ""),
            ):
                resp = await c.post(
                    f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
                )
        body = resp.json()
        assert body["dispatched_reviewers"] == ["qa"]
        skipped_roles = [s["role"] for s in body["skipped_reviewers"]]
        assert sorted(skipped_roles) == ["architecture", "security"]
        assert all(s["reason"] == "agent_offline_or_missing" for s in body["skipped_reviewers"])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_review_marks_offline_reviewer_as_skipped() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(session)
            # Knock the QA reviewer offline (no session_id).
            qa = reviewers["qa"]
            qa.openclaw_session_id = None
            session.add(qa)
            await session.commit()
        app = _build_app(sm, user=user)
        captured, p1, p2 = _capture()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with (
                p1,
                p2,
                patch("app.api.sprints.settings.org_qa_reviewer_agent_id", str(reviewers["qa"].id)),
                patch(
                    "app.api.sprints.settings.org_security_reviewer_agent_id",
                    str(reviewers["security"].id),
                ),
                patch(
                    "app.api.sprints.settings.org_architecture_reviewer_agent_id",
                    str(reviewers["architecture"].id),
                ),
            ):
                resp = await c.post(
                    f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
                )
        body = resp.json()
        assert sorted(body["dispatched_reviewers"]) == ["architecture", "security"]
        skipped = body["skipped_reviewers"]
        assert any(s["role"] == "qa" and s["reason"] == "agent_offline_or_missing" for s in skipped)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_review_409_when_sprint_not_active_or_queued() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, _ = await _seed_with_sprint_and_reviewers(
                session, sprint_status="completed"
            )
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
            )
        assert resp.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_review_409_when_sprint_has_no_tickets() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            user, board, sprint, _ = await _seed_with_sprint_and_reviewers(session)
            # Remove the seeded SprintTicket
            from sqlmodel import select as _select

            link = (
                await session.exec(_select(SprintTicket).where(SprintTicket.sprint_id == sprint.id))
            ).first()
            assert link is not None
            await session.delete(link)
            await session.commit()
        app = _build_app(sm, user=user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/boards/{board.id}/sprints/{sprint.id}/run-review",
            )
        assert resp.status_code == 409
        assert "no tickets" in resp.json()["detail"].lower()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewer_consensus_completes_sprint_and_archives_done_tasks() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            _user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                sprint_status="reviewing",
            )
            remediation = (
                await session.exec(
                    select(Task)
                    .join(SprintTicket, SprintTicket.task_id == Task.id)
                    .where(SprintTicket.sprint_id == sprint.id)
                )
            ).one()
            remediation.updated_at = utcnow()
            remediation.done_at = utcnow()
            session.add(remediation)
            earlier = remediation.updated_at - timedelta(minutes=5)
            for role in ("qa", "security", "architecture"):
                session.add(
                    SprintReview(
                        organization_id=board.organization_id,
                        board_id=board.id,
                        sprint_id=sprint.id,
                        role=role,
                        status="pending",
                    )
                )
            await session.commit()

            from app.services.sprint_reviews import record_sprint_review_verdict

            for role, agent in reviewers.items():
                gate = await record_sprint_review_verdict(
                    session,
                    sprint=sprint,
                    board=board,
                    role=role,
                    agent_id=agent.id,
                    verdict="approve",
                    summary=f"{role} approved",
                    findings=[],
                    created_ticket_ids=[],
                )

            await session.refresh(sprint)
            assert sprint.status == "completed"
            assert gate.approved is True
            task = (
                await session.exec(
                    select(Task)
                    .join(SprintTicket, SprintTicket.task_id == Task.id)
                    .where(SprintTicket.sprint_id == sprint.id)
                )
            ).first()
            assert task is not None
            assert task.status == "archived"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewing_sprint_re_dispatches_after_change_requests_are_done() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            _user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                sprint_status="reviewing",
            )
            remediation = (
                await session.exec(
                    select(Task)
                    .join(SprintTicket, SprintTicket.task_id == Task.id)
                    .where(SprintTicket.sprint_id == sprint.id)
                )
            ).one()
            remediation.updated_at = utcnow()
            remediation.done_at = remediation.updated_at
            session.add(remediation)
            earlier = remediation.updated_at - timedelta(minutes=5)
            for role in ("qa", "security", "architecture"):
                session.add(
                    SprintReview(
                        organization_id=board.organization_id,
                        board_id=board.id,
                        sprint_id=sprint.id,
                        role=role,
                        status="changes_requested" if role == "security" else "approved",
                        agent_id=reviewers.get(role).id if role in reviewers else None,
                        summary="stale summary",
                        findings=[{"title": "stale finding"}],
                        created_ticket_ids=[str(remediation.id)] if role == "security" else [],
                        resolved_at=earlier,
                    )
                )
            await session.commit()

            from app.services.sprint_lifecycle import SprintService

            captured, p1, p2 = _capture()
            with (
                p1,
                p2,
                patch("app.services.sprint_reviews.settings.org_qa_reviewer_agent_id", ""),
                patch("app.services.sprint_reviews.settings.org_security_reviewer_agent_id", ""),
                patch(
                    "app.services.sprint_reviews.settings.org_architecture_reviewer_agent_id", ""
                ),
            ):
                await SprintService.check_sprint_completion(session, board_id=board.id)

            assert len(captured) == 1
            assert captured[0]["session_key"] == standalone_agent_session_key(
                reviewers["security"].id
            )
            review_rows = (
                await session.exec(select(SprintReview).where(SprintReview.sprint_id == sprint.id))
            ).all()
            statuses = {review.role: review.status for review in review_rows}
            assert statuses == {
                "architecture": "approved",
                "qa": "approved",
                "security": "pending",
            }
            security_review = next(review for review in review_rows if review.role == "security")
            assert security_review.agent_id is None
            assert security_review.summary is None
            assert security_review.findings is None
            assert security_review.created_ticket_ids is None
            assert security_review.resolved_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewing_sprint_re_dispatches_stale_pending_review() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            _user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                sprint_status="reviewing",
            )
            stale_dispatched_at = utcnow() - timedelta(minutes=45)
            for role in ("qa", "security", "architecture"):
                session.add(
                    SprintReview(
                        organization_id=board.organization_id,
                        board_id=board.id,
                        sprint_id=sprint.id,
                        role=role,
                        status="pending" if role == "qa" else "approved",
                        agent_id=None if role == "qa" else reviewers[role].id,
                        summary=None if role == "qa" else "approved",
                        findings=None if role == "qa" else [],
                        created_ticket_ids=None if role == "qa" else [],
                        resolved_at=None if role == "qa" else utcnow(),
                        dispatched_at=stale_dispatched_at,
                    )
                )
            await session.commit()

            from app.services.sprint_lifecycle import SprintService

            captured, p1, p2 = _capture()
            with (
                p1,
                p2,
                patch(
                    "app.services.sprint_lifecycle.settings."
                    "sprint_review_pending_retry_minutes",
                    20,
                ),
                patch("app.services.sprint_reviews.settings.org_qa_reviewer_agent_id", ""),
                patch("app.services.sprint_reviews.settings.org_security_reviewer_agent_id", ""),
                patch(
                    "app.services.sprint_reviews.settings.org_architecture_reviewer_agent_id", ""
                ),
            ):
                await SprintService.check_sprint_completion(session, board_id=board.id)

            assert len(captured) == 1
            assert captured[0]["session_key"] == standalone_agent_session_key(reviewers["qa"].id)
            qa_review = (
                await session.exec(
                    select(SprintReview)
                    .where(SprintReview.sprint_id == sprint.id)
                    .where(SprintReview.role == "qa")
                )
            ).one()
            assert qa_review.status == "pending"
            assert qa_review.dispatched_at is not None
            assert qa_review.dispatched_at > stale_dispatched_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewing_sprint_does_not_loop_change_request_without_new_remediation() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            _user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                sprint_status="reviewing",
            )
            remediation = (
                await session.exec(
                    select(Task)
                    .join(SprintTicket, SprintTicket.task_id == Task.id)
                    .where(SprintTicket.sprint_id == sprint.id)
                )
            ).one()
            remediation.updated_at = utcnow() - timedelta(minutes=10)
            remediation.done_at = remediation.updated_at
            session.add(remediation)
            session.add(
                SprintReview(
                    organization_id=board.organization_id,
                    board_id=board.id,
                    sprint_id=sprint.id,
                    role="qa",
                    status="changes_requested",
                    agent_id=reviewers["qa"].id,
                    summary="still blocked",
                    findings=[{"title": "fix not merged"}],
                    created_ticket_ids=[str(remediation.id)],
                    resolved_at=utcnow(),
                    dispatched_at=utcnow() - timedelta(minutes=20),
                )
            )
            for role in ("security", "architecture"):
                session.add(
                    SprintReview(
                        organization_id=board.organization_id,
                        board_id=board.id,
                        sprint_id=sprint.id,
                        role=role,
                        status="approved",
                        agent_id=reviewers[role].id,
                        summary="approved",
                        findings=[],
                        created_ticket_ids=[],
                        resolved_at=utcnow(),
                    )
                )
            await session.commit()

            from app.services.sprint_lifecycle import SprintService

            captured, p1, p2 = _capture()
            with p1, p2:
                await SprintService.check_sprint_completion(session, board_id=board.id)

            assert captured == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reviewer_created_remediation_is_attached_to_reviewing_sprint() -> None:
    engine = await _make_engine()
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sm() as session:
            _user, board, sprint, reviewers = await _seed_with_sprint_and_reviewers(
                session,
                sprint_status="reviewing",
            )
            remediation = Task(
                id=uuid4(),
                board_id=board.id,
                title="Fix release gate",
                status="inbox",
            )
            session.add(remediation)
            await session.flush()

            from app.api.agent import _attach_reviewer_remediation_to_reviewing_sprint

            await _attach_reviewer_remediation_to_reviewing_sprint(
                session,
                board=board,
                task=remediation,
                agent=reviewers["qa"],
            )
            await session.commit()

            await session.refresh(remediation)
            assert remediation.sprint_id == sprint.id
            links = (
                await session.exec(
                    select(SprintTicket).where(SprintTicket.task_id == remediation.id)
                )
            ).all()
            assert len(links) == 1
            assert links[0].sprint_id == sprint.id
    finally:
        await engine.dispose()
