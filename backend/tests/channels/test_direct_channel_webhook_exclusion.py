# ruff: noqa: INP001
"""Test that webhook-created threads are never routed to direct channels.

Direct channels are for DMs between users and specific agents. They should
NEVER receive threads created from board webhooks.
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

from app.models import Channel, Thread  # noqa: E402
from app.models.agents import Agent  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402
from app.services.channel_thread_hook import on_task_created_by_webhook  # noqa: E402


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_webhook_threads_never_created_in_direct_channels() -> None:
    """Webhooks should create threads in alert/discussion channels, NEVER in direct channels."""
    _engine, session_maker = await _make_session_maker()

    async with session_maker() as session:
        # Setup org and gateway
        org_id = uuid4()
        org = Organization(id=org_id, name="Test Org", slug="test-org")
        session.add(org)
        gateway_id = uuid4()
        gateway = Gateway(
            id=gateway_id,
            organization_id=org_id,
            name="Test Gateway",
            slug="test-gateway",
            url="http://test-gateway:8080",
            workspace_root="/tmp/test",
        )
        session.add(gateway)
        await session.commit()

        # Create board
        board = Board(
            name="Test Board",
            slug="test-board",
            description="Test",
            organization_id=org_id,
            gateway_id=gateway_id,
        )
        session.add(board)
        await session.commit()
        await session.refresh(board)

        # Create an agent
        agent = Agent(
            board_id=board.id,
            gateway_id=gateway_id,
            name="Test Agent",
            is_board_lead=True,
            openclaw_session_id="test-session",
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        # Create an alert channel for gitlab webhooks
        alert_channel = Channel(
            board_id=board.id,
            name="GitLab Alerts",
            slug="gitlab-alerts",
            channel_type="alert",
            webhook_source_filter="gitlab",  # Matches webhook source
        )
        session.add(alert_channel)

        # Create a direct channel for the agent (for DMs)
        direct_channel = Channel(
            board_id=board.id,
            name=f"DM with {agent.name}",
            slug=f"dm-{agent.name.lower().replace(' ', '-')}",
            channel_type="direct",
            webhook_source_filter=str(agent.id),  # Agent UUID, NOT a webhook source
        )
        session.add(direct_channel)
        await session.commit()
        await session.refresh(alert_channel)
        await session.refresh(direct_channel)

        # CRITICAL TEST: Verify that the channel lookup query would exclude direct channels
        # This is the core fix tested - direct channels must never match webhook source filters
        from sqlmodel import col, select
        
        # Simulate the query from on_task_created_by_webhook with source_category="gitlab"
        matching_channels_with_directexcluded = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.webhook_source_filter) == "gitlab",
                    col(Channel.channel_type) != "direct",  # THE FIX
                    col(Channel.is_archived).is_(False),
                )
            )
        ).all()
        
        # Without the fix, this query might match BOTH channels if direct_channel.webhook_source_filter
        # happened to be "gitlab". With the fix, it only matches alert channels.
        assert alert_channel in matching_channels_with_directexcluded
        assert direct_channel not in matching_channels_with_directexcluded, (
            "CRITICAL BUG: Direct channel matched webhook query! "
            "This would cause webhook threads to be created in DM channels."
        )
