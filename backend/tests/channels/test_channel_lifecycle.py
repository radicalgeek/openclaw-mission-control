# ruff: noqa: INP001
"""Tests for board channel lifecycle hooks.

Tests that:
- New board created → all 9 default channels created
- Board deleted → channels are archived or hard-deleted
- Board lead changed → subscriptions updated
- Agent added/removed → subscriptions updated
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"
os.environ["CHANNELS_ENABLED"] = "true"

from app.models import (  # noqa: E402
    Channel,
    ChannelSubscription,
    Thread,
)
from app.models.agents import Agent
from app.models.boards import Board
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services.channel_lifecycle import (  # noqa: E402
    get_default_channel_definitions,
    on_agent_added_to_board,
    on_agent_removed_from_board,
    on_board_created,
    on_board_deleted,
    on_board_lead_changed,
)


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_board(session: AsyncSession) -> Board:
    org = Organization(id=uuid4(), name=f"org-{uuid4()}")
    session.add(org)
    gw = Gateway(
        id=uuid4(),
        organization_id=org.id,
        name="gw",
        url="https://gw.test",
        main_session_key="key",
        workspace_root="/tmp",
    )
    session.add(gw)
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        gateway_id=gw.id,
        name="Test Board",
        slug="test-board",
    )
    session.add(board)
    await session.commit()
    return board


async def _seed_agent(session: AsyncSession, *, board: Board, is_lead: bool = False) -> Agent:
    agent = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=board.gateway_id,
        name="test-agent",
        is_board_lead=is_lead,
    )
    session.add(agent)
    await session.commit()
    return agent


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_channel_count() -> None:
    defs = get_default_channel_definitions()
    assert len(defs) == 9
    alert_count = sum(1 for d in defs if d.channel_type == "alert")
    discussion_count = sum(1 for d in defs if d.channel_type == "discussion")
    assert alert_count == 4
    assert discussion_count == 5


@pytest.mark.asyncio
async def test_on_board_created_creates_channels() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        channels = (await session.exec(select(Channel).where(col(Channel.board_id) == board.id))).all()
        assert len(channels) == 9
        alert_names = {c.slug for c in channels if c.channel_type == "alert"}
        assert "build-alerts" in alert_names
        assert "deployment-alerts" in alert_names
        assert "test-run-alerts" in alert_names
        assert "production-alerts" in alert_names

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_created_with_lead_creates_subscriptions() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        agent = await _seed_agent(session, board=board, is_lead=True)
        await on_board_created(session, board, lead_agent_id=agent.id)

        subs = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == agent.id)
            )
        ).all()
        # Should have subscriptions to all 9 channels
        assert len(subs) == 9
        assert all(s.notify_on == "all" for s in subs)

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_deleted_archives_channels() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        # Soft delete
        await on_board_deleted(session, board, hard_delete=False)

        channels = (await session.exec(select(Channel).where(col(Channel.board_id) == board.id))).all()
        assert len(channels) == 9
        assert all(c.is_archived for c in channels)

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_deleted_hard_removes_channels() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        # Hard delete
        await on_board_deleted(session, board, hard_delete=True)

        channels = (await session.exec(select(Channel).where(col(Channel.board_id) == board.id))).all()
        assert len(channels) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_lead_changed_updates_subscriptions() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        old_lead = await _seed_agent(session, board=board, is_lead=True)
        new_lead = await _seed_agent(session, board=board)
        await on_board_created(session, board, lead_agent_id=old_lead.id)

        await on_board_lead_changed(session, board, old_lead.id, new_lead.id)

        old_subs = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == old_lead.id)
            )
        ).all()
        new_subs = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == new_lead.id)
            )
        ).all()

        assert len(old_subs) == 0
        assert len(new_subs) == 9

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_agent_added_subscribes_to_discussion_channels() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        agent = await _seed_agent(session, board=board)
        await on_agent_added_to_board(session, board, agent.id)

        subs = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == agent.id)
            )
        ).all()

        # Should only be subscribed to 5 discussion channels
        assert len(subs) == 5
        assert all(s.notify_on == "mentions" for s in subs)

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_agent_removed_removes_all_subscriptions() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        agent = await _seed_agent(session, board=board)
        await on_agent_added_to_board(session, board, agent.id)

        # Confirm subscribed
        subs_before = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == agent.id)
            )
        ).all()
        assert len(subs_before) == 5

        await on_agent_removed_from_board(session, board, agent.id)

        subs_after = (
            await session.exec(
                select(ChannelSubscription).where(col(ChannelSubscription.agent_id) == agent.id)
            )
        ).all()
        assert len(subs_after) == 0

    await engine.dispose()
