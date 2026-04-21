# ruff: noqa: INP001
"""Tests for audit logging on channel and thread actions."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"
os.environ["CHANNELS_ENABLED"] = "true"

from app.api import thread_messages as thread_messages_api  # noqa: E402
from app.api import threads as threads_api  # noqa: E402
from app.api.deps import ActorContext  # noqa: E402
from app.models.agent_audit_log import AgentAuditLog  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.channel import Channel  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402
from app.models.thread import Thread  # noqa: E402
from app.models.users import User  # noqa: E402
from app.schemas.thread_messages import ThreadMessageCreate  # noqa: E402
from app.schemas.threads import ThreadCreate  # noqa: E402


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_channel_context(
    session: AsyncSession,
) -> tuple[Organization, Board, Channel, User]:
    org = Organization(id=uuid4(), name=f"org-{uuid4()}")
    session.add(org)
    gateway = Gateway(
        id=uuid4(),
        organization_id=org.id,
        name="gw",
        url="https://gw.test",
        workspace_root="/tmp",
    )
    session.add(gateway)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        gateway_id=gateway.id,
        name="Test Board",
        slug="test-board",
    )
    session.add(board)
    channel = Channel(
        board_id=board.id,
        name="Support",
        slug="support",
        channel_type="discussion",
        description="",
        is_readonly=False,
        position=0,
    )
    session.add(channel)
    user = User(
        id=uuid4(),
        clerk_user_id=f"clerk-{uuid4()}",
        email="user@example.com",
        name="Test User",
        active_organization_id=org.id,
    )
    session.add(user)
    await session.commit()
    return org, board, channel, user


@pytest.mark.asyncio
async def test_create_thread_writes_audit_row() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, board, channel, user = await _seed_channel_context(session)

        result = await threads_api.create_channel_thread(
            channel_id=channel.id,
            payload=ThreadCreate(topic="Audit me", content="First message"),
            session=session,
            actor=ActorContext(actor_type="user", user=user),
        )

        audit_rows = (
            await session.exec(
                select(AgentAuditLog).where(AgentAuditLog.event_action == "thread.created")
            )
        ).all()
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        assert audit.organization_id == org.id
        assert audit.board_id == board.id
        assert audit.thread_id == result.id
        assert audit.actor_id == user.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_thread_message_writes_audit_row() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, board, channel, user = await _seed_channel_context(session)
        thread = Thread(
            id=uuid4(),
            channel_id=channel.id,
            topic="Existing thread",
            source_type="user",
            message_count=0,
        )
        session.add(thread)
        await session.commit()

        result = await thread_messages_api.create_thread_message(
            thread_id=thread.id,
            payload=ThreadMessageCreate(content="Hello", content_type="text"),
            session=session,
            actor=ActorContext(actor_type="user", user=user),
        )

        audit_rows = (
            await session.exec(
                select(AgentAuditLog).where(AgentAuditLog.event_action == "thread.message.posted")
            )
        ).all()
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        assert audit.organization_id == org.id
        assert audit.board_id == board.id
        assert audit.thread_id == thread.id
        assert audit.actor_id == user.id
        assert audit.detail is not None
        assert audit.detail["message_id"] == str(result.id)

    await engine.dispose()
