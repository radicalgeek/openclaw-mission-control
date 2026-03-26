"""Test platform Support channel lifecycle and cross-board subscriptions."""

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

from app.models.agents import Agent
from app.models.boards import Board
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.gateways import Gateway
from app.models.organizations import Organization
from app.services.channel_lifecycle import (
    on_board_created,
    on_board_marked_platform,
    on_board_unmarked_platform,
    sync_platform_support_subscribers,
)


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_gateway(session: AsyncSession) -> Gateway:
    org = Organization(id=uuid4(), name=f"org-{uuid4()}")
    session.add(org)
    gateway = Gateway(
        id=uuid4(),
        organization_id=org.id,
        slug="test-gateway",
        name="Test Gateway",
        url="ws://localhost:8080/ws",
        main_session_key="key",
        workspace_root="/tmp",
    )
    session.add(gateway)
    await session.commit()
    await session.refresh(gateway)
    return gateway


async def _seed_board(
    session: AsyncSession,
    gateway: Gateway,
    is_platform: bool = False,
) -> Board:
    board = Board(
        id=uuid4(),
        organization_id=gateway.organization_id,
        gateway_id=gateway.id,
        name="Test Board",
        slug=f"test-board-{uuid4().hex[:8]}",
        is_platform=is_platform,
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


async def _seed_lead(session: AsyncSession, board: Board) -> Agent:
    agent = Agent(
        id=uuid4(),
        organization_id=board.organization_id,
        board_id=board.id,
        gateway_id=board.gateway_id,
        name=f"Lead Agent {uuid4().hex[:4]}",
        slug=f"lead-{uuid4().hex[:8]}",
        is_board_lead=True,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_platform_board_creates_support_channel() -> None:
    """Platform board should have Support channel created with 10 total channels."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)
        platform_board = await _seed_board(session, gateway, is_platform=True)
        lead = await _seed_lead(session, platform_board)

        await on_board_created(session, platform_board, lead_agent_id=lead.id)

        channels = (
            await session.exec(
                select(Channel).where(col(Channel.board_id) == platform_board.id)
            )
        ).all()

        # 9 default + 1 Support channel
        assert len(channels) == 10
        support = next((c for c in channels if c.slug == "support"), None)
        assert support is not None
        assert support.name == "Support"
        assert support.channel_type == "discussion"
        assert support.position == 9

        # Lead should be subscribed to Support channel
        sub = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support.id,
                    col(ChannelSubscription.agent_id) == lead.id,
                )
            )
        ).first()
        assert sub is not None
        assert sub.notify_on == "all"

    await engine.dispose()


@pytest.mark.asyncio
async def test_non_platform_board_no_support_channel() -> None:
    """Non-platform board should not have Support channel."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)
        regular_board = await _seed_board(session, gateway, is_platform=False)
        lead = await _seed_lead(session, regular_board)

        await on_board_created(session, regular_board, lead_agent_id=lead.id)

        channels = (
            await session.exec(
                select(Channel).where(col(Channel.board_id) == regular_board.id)
            )
        ).all()

        # Only 9 default channels
        assert len(channels) == 9
        support = next((c for c in channels if c.slug == "support"), None)
        assert support is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_cross_board_subscription_on_platform_support() -> None:
    """All board leads in gateway should be subscribed to platform Support channel."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)

        # Create platform board with Support channel
        platform_board = await _seed_board(session, gateway, is_platform=True)
        platform_lead = await _seed_lead(session, platform_board)
        await on_board_created(session, platform_board, lead_agent_id=platform_lead.id)

        # Create two regular boards
        board1 = await _seed_board(session, gateway, is_platform=False)
        lead1 = await _seed_lead(session, board1)
        await on_board_created(session, board1, lead_agent_id=lead1.id)

        board2 = await _seed_board(session, gateway, is_platform=False)
        lead2 = await _seed_lead(session, board2)
        await on_board_created(session, board2, lead_agent_id=lead2.id)

        # Get Support channel
        support_channel = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == platform_board.id,
                    col(Channel.slug) == "support",
                )
            )
        ).first()
        assert support_channel is not None

        # All 3 leads should be subscribed to Support channel
        subs = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support_channel.id,
                )
            )
        ).all()

        subscribed_agent_ids = {sub.agent_id for sub in subs}
        assert platform_lead.id in subscribed_agent_ids
        assert lead1.id in subscribed_agent_ids
        assert lead2.id in subscribed_agent_ids
        assert len(subs) == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_marked_platform_creates_support() -> None:
    """Marking a board as platform should create Support channel."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)
        board = await _seed_board(session, gateway, is_platform=False)
        lead = await _seed_lead(session, board)
        await on_board_created(session, board, lead_agent_id=lead.id)

        # Initially no Support channel
        channels_before = (
            await session.exec(
                select(Channel).where(col(Channel.board_id) == board.id)
            )
        ).all()
        assert len(channels_before) == 9

        # Mark as platform
        board.is_platform = True
        await session.commit()
        await on_board_marked_platform(session, board)

        # Now should have Support channel
        support = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.slug) == "support",
                )
            )
        ).first()
        assert support is not None
        assert support.name == "Support"

        # Lead should be subscribed
        sub = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support.id,
                    col(ChannelSubscription.agent_id) == lead.id,
                )
            )
        ).first()
        assert sub is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_on_board_unmarked_platform_archives_support() -> None:
    """Unmarking a board as platform should archive Support channel."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)
        board = await _seed_board(session, gateway, is_platform=True)
        lead = await _seed_lead(session, board)
        await on_board_created(session, board, lead_agent_id=lead.id)

        # Support channel exists
        support = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.slug) == "support",
                )
            )
        ).first()
        assert support is not None
        assert not support.is_archived

        # Unmark as platform
        board.is_platform = False
        await session.commit()
        await on_board_unmarked_platform(session, board)

        # Support should be archived
        await session.refresh(support)
        assert support.is_archived

    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_removes_cross_board_subs_when_unmarked() -> None:
    """Unmarking platform should remove cross-board subscriptions."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        gateway = await _seed_gateway(session)

        # Create platform board
        platform_board = await _seed_board(session, gateway, is_platform=True)
        platform_lead = await _seed_lead(session, platform_board)
        await on_board_created(session, platform_board, lead_agent_id=platform_lead.id)

        # Create regular board
        board1 = await _seed_board(session, gateway, is_platform=False)
        lead1 = await _seed_lead(session, board1)
        await on_board_created(session, board1, lead_agent_id=lead1.id)

        support = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == platform_board.id,
                    col(Channel.slug) == "support",
                )
            )
        ).first()
        assert support is not None

        # Both leads subscribed
        subs_before = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support.id,
                )
            )
        ).all()
        assert len(subs_before) == 2

        # Unmark as platform
        platform_board.is_platform = False
        await session.commit()
        await on_board_unmarked_platform(session, platform_board)

        # Only platform_lead should remain subscribed (cross-board removed)
        subs_after = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support.id,
                )
            )
        ).all()
        assert len(subs_after) == 1
        assert subs_after[0].agent_id == platform_lead.id

    await engine.dispose()
