# ruff: noqa: INP001
"""Tests for channel agent routing (WP-3).

Verifies routing rules for get_agents_to_notify:
- Board lead always gets dispatched for regular channels
- Non-lead agents only dispatched when @mentioned
- Agent who sent the message is excluded (no reply-to-self loops)
- Platform Support channel: platform lead dispatched for all threads
- Platform Support channel: cross-board lead dispatched only for their thread
- Platform Support channel: cross-board lead dispatched when @mentioned
- Direct channel routing
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"
os.environ["CHANNELS_ENABLED"] = "true"

from app.models.agents import Agent  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.channel import Channel  # noqa: E402
from app.models.channel_subscription import ChannelSubscription  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402
from app.models.thread import Thread  # noqa: E402
from app.models.thread_message import ThreadMessage  # noqa: E402
from app.services.channel_agent_routing import get_agents_to_notify  # noqa: E402


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_org_gateway(session: AsyncSession) -> tuple[Organization, Gateway]:
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
    await session.commit()
    await session.refresh(org)
    await session.refresh(gw)
    return org, gw


async def _seed_board(
    session: AsyncSession,
    org: Organization,
    gw: Gateway,
    *,
    is_platform: bool = False,
) -> Board:
    board = Board(
        id=uuid4(),
        organization_id=org.id,
        gateway_id=gw.id,
        name=f"Board-{uuid4().hex[:6]}",
        slug=f"board-{uuid4().hex[:8]}",
        is_platform=is_platform,
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


async def _seed_agent(
    session: AsyncSession,
    board: Board,
    *,
    is_lead: bool = False,
    session_key: str | None = None,
) -> Agent:
    agent = Agent(
        id=uuid4(),
        organization_id=board.organization_id,
        board_id=board.id,
        gateway_id=board.gateway_id,
        name=f"Agent-{uuid4().hex[:6]}",
        slug=f"agent-{uuid4().hex[:8]}",
        is_board_lead=is_lead,
        openclaw_session_id=session_key or f"sess-{uuid4().hex}",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


def _discussion_channel(board: Board, slug: str = "general") -> Channel:
    return Channel(
        id=uuid4(),
        board_id=board.id,
        name=slug.title(),
        slug=slug,
        channel_type="discussion",
    )


def _support_channel(platform_board: Board) -> Channel:
    return Channel(
        id=uuid4(),
        board_id=platform_board.id,
        name="Support",
        slug="support",
        channel_type="discussion",
    )


def _thread(channel: Channel, owner_board_id: object = None) -> Thread:
    return Thread(
        id=uuid4(),
        channel_id=channel.id,
        topic="Test thread",
        owner_board_id=owner_board_id,  # type: ignore[arg-type]
    )


def _message(
    thread: Thread,
    content: str = "Hello",
    sender_type: str = "user",
    sender_id: object = None,
    sender_name: str = "User",
) -> ThreadMessage:
    return ThreadMessage(
        id=uuid4(),
        thread_id=thread.id,
        sender_type=sender_type,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
    )


def _subscribe(channel: Channel, agent: Agent, notify_on: str = "all") -> ChannelSubscription:
    return ChannelSubscription(
        id=uuid4(),
        channel_id=channel.id,
        agent_id=agent.id,
        notify_on=notify_on,
    )


# ---------------------------------------------------------------------------
# Regular channel routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_always_notified_regular_channel() -> None:
    """Board lead is dispatched for every message in a regular channel."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        lead = await _seed_agent(session, board, is_lead=True)

        channel = _discussion_channel(board)
        session.add(channel)
        subscription = _subscribe(channel, lead)
        session.add(subscription)
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        msg = _message(thread, content="A user message")

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead.id in agent_ids, "Lead must always be notified"

    await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_not_notified_without_mention() -> None:
    """Non-lead subscribed agent is NOT dispatched unless @mentioned."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        lead = await _seed_agent(session, board, is_lead=True)
        worker = await _seed_agent(session, board, is_lead=False)

        channel = _discussion_channel(board)
        session.add(channel)
        session.add(_subscribe(channel, lead))
        session.add(_subscribe(channel, worker, notify_on="all"))  # even with notify_on="all"
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        # Message with no @mention for worker
        msg = _message(thread, content="Something generic")

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead.id in agent_ids, "Lead must be notified"
        assert worker.id not in agent_ids, "Non-lead must NOT be notified without @mention"

    await engine.dispose()


@pytest.mark.asyncio
async def test_non_lead_notified_when_mentioned() -> None:
    """Non-lead agent is dispatched when @mentioned in the message."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        lead = await _seed_agent(session, board, is_lead=True)
        worker = await _seed_agent(session, board, is_lead=False)

        channel = _discussion_channel(board)
        session.add(channel)
        session.add(_subscribe(channel, lead))
        session.add(_subscribe(channel, worker))
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        msg = _message(thread, content=f"Hey @{worker.name} can you help?")

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert worker.id in agent_ids, "Mentioned agent must be notified"

    await engine.dispose()


@pytest.mark.asyncio
async def test_notify_none_subscription_excludes_agent() -> None:
    """notify_on='none' prevents dispatch even for the board lead."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        lead = await _seed_agent(session, board, is_lead=True)
        bystander = await _seed_agent(session, board, is_lead=False)

        channel = _discussion_channel(board)
        session.add(channel)
        session.add(_subscribe(channel, lead))
        session.add(_subscribe(channel, bystander, notify_on="none"))
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        msg = _message(thread, content=f"@{bystander.name} ping")

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert bystander.id not in agent_ids, "notify_on=none must never be dispatched"

    await engine.dispose()


@pytest.mark.asyncio
async def test_sender_agent_excluded_from_dispatch() -> None:
    """The agent who sent the message is never dispatched back (prevents reply loops)."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        lead = await _seed_agent(session, board, is_lead=True)

        channel = _discussion_channel(board)
        session.add(channel)
        session.add(_subscribe(channel, lead))
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        # The lead is posting the message — should not be dispatched back to themselves
        msg = _message(
            thread,
            content="Lead is posting a reply",
            sender_type="agent",
            sender_id=lead.id,
            sender_name=lead.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead.id not in agent_ids, "Agent sender must not receive their own message back"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Platform Support channel routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_channel_platform_lead_always_notified() -> None:
    """Platform lead is dispatched for all Support channel threads."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        platform_board = await _seed_board(session, org, gw, is_platform=True)
        platform_lead = await _seed_agent(session, platform_board, is_lead=True)

        other_board = await _seed_board(session, org, gw)
        other_lead = await _seed_agent(session, other_board, is_lead=True)

        channel = _support_channel(platform_board)
        session.add(channel)
        # Both leads subscribed (cross-board subscription)
        session.add(_subscribe(channel, platform_lead))
        session.add(_subscribe(channel, other_lead))
        await session.commit()

        # Thread owned by the other board
        thread = _thread(channel, owner_board_id=other_board.id)
        session.add(thread)
        await session.commit()

        msg = _message(
            thread,
            content="I need help with deployment",
            sender_type="agent",
            sender_id=other_lead.id,
            sender_name=other_lead.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert platform_lead.id in agent_ids, "Platform lead must be notified for all Support threads"
        # other_lead is the SENDER, so must be excluded
        assert other_lead.id not in agent_ids, "Sender must not be in the notification list"

    await engine.dispose()


@pytest.mark.asyncio
async def test_support_channel_cross_board_lead_notified_for_own_thread() -> None:
    """Cross-board lead is dispatched when platform lead replies to their thread."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        platform_board = await _seed_board(session, org, gw, is_platform=True)
        platform_lead = await _seed_agent(session, platform_board, is_lead=True)

        board_a = await _seed_board(session, org, gw)
        lead_a = await _seed_agent(session, board_a, is_lead=True)

        channel = _support_channel(platform_board)
        session.add(channel)
        session.add(_subscribe(channel, platform_lead))
        session.add(_subscribe(channel, lead_a))
        await session.commit()

        # Thread owned by board_a
        thread = _thread(channel, owner_board_id=board_a.id)
        session.add(thread)
        await session.commit()

        # Platform lead is REPLYING — lead_a should be notified
        msg = _message(
            thread,
            content="Here is the fix for your deployment issue",
            sender_type="agent",
            sender_id=platform_lead.id,
            sender_name=platform_lead.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead_a.id in agent_ids, "Owner board lead must be notified of replies to their thread"
        assert platform_lead.id not in agent_ids, "Platform lead (sender) must not receive their own message"

    await engine.dispose()


@pytest.mark.asyncio
async def test_support_channel_cross_board_lead_not_notified_for_other_thread() -> None:
    """Cross-board lead is NOT dispatched for threads owned by different boards."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        platform_board = await _seed_board(session, org, gw, is_platform=True)
        platform_lead = await _seed_agent(session, platform_board, is_lead=True)

        board_a = await _seed_board(session, org, gw)
        lead_a = await _seed_agent(session, board_a, is_lead=True)

        board_b = await _seed_board(session, org, gw)
        lead_b = await _seed_agent(session, board_b, is_lead=True)

        channel = _support_channel(platform_board)
        session.add(channel)
        session.add(_subscribe(channel, platform_lead))
        session.add(_subscribe(channel, lead_a))
        session.add(_subscribe(channel, lead_b))
        await session.commit()

        # Thread owned by board_a — board_b lead should NOT be notified
        thread = _thread(channel, owner_board_id=board_a.id)
        session.add(thread)
        await session.commit()

        msg = _message(
            thread,
            content="Replying to board_a's support thread",
            sender_type="agent",
            sender_id=platform_lead.id,
            sender_name=platform_lead.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead_a.id in agent_ids, "board_a lead must be notified (owns thread)"
        assert lead_b.id not in agent_ids, "board_b lead must NOT be notified (different thread)"

    await engine.dispose()


@pytest.mark.asyncio
async def test_support_channel_cross_board_lead_notified_when_mentioned() -> None:
    """Cross-board lead is dispatched in Support channel when @mentioned, even for non-owned threads."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        platform_board = await _seed_board(session, org, gw, is_platform=True)
        platform_lead = await _seed_agent(session, platform_board, is_lead=True)

        board_a = await _seed_board(session, org, gw)
        lead_a = await _seed_agent(session, board_a, is_lead=True)

        board_b = await _seed_board(session, org, gw)
        lead_b = await _seed_agent(session, board_b, is_lead=True)

        channel = _support_channel(platform_board)
        session.add(channel)
        session.add(_subscribe(channel, platform_lead))
        session.add(_subscribe(channel, lead_a))
        session.add(_subscribe(channel, lead_b))
        await session.commit()

        # Thread owned by board_a
        thread = _thread(channel, owner_board_id=board_a.id)
        session.add(thread)
        await session.commit()

        # Explicitly @mention board_b lead
        msg = _message(
            thread,
            content=f"@{lead_b.name} could you also check this?",
            sender_type="agent",
            sender_id=platform_lead.id,
            sender_name=platform_lead.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert lead_b.id in agent_ids, "Mentioned cross-board lead must be notified"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Direct channel routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_channel_routes_to_target_agent() -> None:
    """Direct channel dispatches only to the specific agent in webhook_source_filter."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        target = await _seed_agent(session, board)
        other = await _seed_agent(session, board)

        channel = Channel(
            id=uuid4(),
            board_id=board.id,
            name="Direct",
            slug="direct-test",
            channel_type="direct",
            webhook_source_filter=str(target.id),
        )
        session.add(channel)
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        msg = _message(thread, content="Hello agent")

        result = await get_agents_to_notify(session, thread, msg, channel)
        agent_ids = {n.agent_id for n in result}

        assert target.id in agent_ids, "Target agent must be notified"
        assert other.id not in agent_ids, "Other agents must not be notified in direct channel"

    await engine.dispose()


@pytest.mark.asyncio
async def test_direct_channel_skips_sender() -> None:
    """Direct channel does not dispatch back to the target agent if they are the sender."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        org, gw = await _seed_org_gateway(session)
        board = await _seed_board(session, org, gw)
        target = await _seed_agent(session, board)

        channel = Channel(
            id=uuid4(),
            board_id=board.id,
            name="Direct",
            slug="direct-self",
            channel_type="direct",
            webhook_source_filter=str(target.id),
        )
        session.add(channel)
        await session.commit()

        thread = _thread(channel)
        session.add(thread)
        await session.commit()

        # Target is replying — should not be dispatched back
        msg = _message(
            thread,
            content="My reply",
            sender_type="agent",
            sender_id=target.id,
            sender_name=target.name,
        )

        result = await get_agents_to_notify(session, thread, msg, channel)
        assert result == [], "Direct channel sender must not receive their own message"

    await engine.dispose()
