"""Channel lifecycle hooks — keep channel groups in sync with board CRUD.

All hooks are async and wrapped in try/except at call sites so channel errors
never block existing board operations.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from sqlmodel import col, delete, select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.models.user_channel_state import UserChannelState

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Default channel definitions
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _ChannelDef:
    name: str
    slug: str
    channel_type: str
    description: str
    is_readonly: bool
    webhook_source_filter: str | None
    position: int


def get_default_channel_definitions() -> list[_ChannelDef]:
    """Return the 9 default channels created for every new board."""
    return [
        # Alert channels (4)
        _ChannelDef(
            name="Build Alerts",
            slug="build-alerts",
            channel_type="alert",
            description="CI/CD build results and failures",
            is_readonly=True,
            webhook_source_filter="build",
            position=0,
        ),
        _ChannelDef(
            name="Deployment Alerts",
            slug="deployment-alerts",
            channel_type="alert",
            description="Deployment status and rollback notifications",
            is_readonly=True,
            webhook_source_filter="deployment",
            position=1,
        ),
        _ChannelDef(
            name="Test Run Alerts",
            slug="test-run-alerts",
            channel_type="alert",
            description="Test suite results and coverage changes",
            is_readonly=True,
            webhook_source_filter="test",
            position=2,
        ),
        _ChannelDef(
            name="Production Alerts",
            slug="production-alerts",
            channel_type="alert",
            description="Production incidents, errors, and health checks",
            is_readonly=True,
            webhook_source_filter="production",
            position=3,
        ),
        # Discussion channels (5)
        _ChannelDef(
            name="Development",
            slug="development",
            channel_type="discussion",
            description="Code discussions, feature planning, technical decisions",
            is_readonly=False,
            webhook_source_filter=None,
            position=4,
        ),
        _ChannelDef(
            name="DevOps",
            slug="devops",
            channel_type="discussion",
            description="Infrastructure, pipelines, and operational topics",
            is_readonly=False,
            webhook_source_filter=None,
            position=5,
        ),
        _ChannelDef(
            name="Testing",
            slug="testing",
            channel_type="discussion",
            description="Test strategy, QA discussions, bug triage",
            is_readonly=False,
            webhook_source_filter=None,
            position=6,
        ),
        _ChannelDef(
            name="Architecture",
            slug="architecture",
            channel_type="discussion",
            description="System design, ADRs, and architectural decisions",
            is_readonly=False,
            webhook_source_filter=None,
            position=7,
        ),
        _ChannelDef(
            name="General",
            slug="general",
            channel_type="discussion",
            description="Anything that doesn't fit elsewhere",
            is_readonly=False,
            webhook_source_filter=None,
            position=8,
        ),
    ]


_PLATFORM_SUPPORT_CHANNEL = _ChannelDef(
    name="Support",
    slug="support",
    channel_type="discussion",
    description="Cross-board support requests for the platform/infrastructure team",
    is_readonly=False,
    webhook_source_filter=None,
    position=9,
)


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


async def on_board_created(
    session: AsyncSession,
    board: Board,
    lead_agent_id: UUID | None = None,
) -> None:
    """Create the full default channel set for a newly created board.

    Called AFTER the board has been committed. Wrapped in try/except at call site.
    """
    if not settings.channels_enabled:
        return

    defs = get_default_channel_definitions()
    channels: list[Channel] = []
    for channel_def in defs:
        channel = Channel(
            board_id=board.id,
            name=channel_def.name,
            slug=channel_def.slug,
            channel_type=channel_def.channel_type,
            description=channel_def.description,
            is_readonly=channel_def.is_readonly,
            webhook_source_filter=channel_def.webhook_source_filter,
            position=channel_def.position,
        )
        session.add(channel)
        channels.append(channel)

    await session.flush()

    # Subscribe the board's lead agent to ALL channels
    if lead_agent_id is not None:
        for channel in channels:
            sub = ChannelSubscription(
                channel_id=channel.id,
                agent_id=lead_agent_id,
                notify_on="all",
            )
            session.add(sub)

    # If this is a platform board, create the Support channel
    if board.is_platform:
        support_channel = Channel(
            board_id=board.id,
            name=_PLATFORM_SUPPORT_CHANNEL.name,
            slug=_PLATFORM_SUPPORT_CHANNEL.slug,
            channel_type=_PLATFORM_SUPPORT_CHANNEL.channel_type,
            description=_PLATFORM_SUPPORT_CHANNEL.description,
            is_readonly=_PLATFORM_SUPPORT_CHANNEL.is_readonly,
            webhook_source_filter=_PLATFORM_SUPPORT_CHANNEL.webhook_source_filter,
            position=_PLATFORM_SUPPORT_CHANNEL.position,
        )
        session.add(support_channel)
        await session.flush()

        # Subscribe the lead to Support channel
        if lead_agent_id is not None:
            sub = ChannelSubscription(
                channel_id=support_channel.id,
                agent_id=lead_agent_id,
                notify_on="all",
            )
            session.add(sub)

    await session.commit()

    # Subscribe this board's lead to existing platform Support channel (if any)
    await sync_platform_support_subscribers(session, board.gateway_id)

    logger.info(
        "channel_lifecycle.board_created board_id=%s channels_created=%s is_platform=%s",
        board.id,
        len(channels),
        board.is_platform,
    )


async def on_channel_created(
    session: AsyncSession,
    channel: Channel,
) -> None:
    """Subscribe all existing agents on the channel's board to a newly created channel.

    Called after a custom channel is manually created via the API.
    Wrapped in try/except at the call site.
    """
    if not settings.channels_enabled:
        return

    agents = (
        await session.exec(
            select(Agent).where(
                col(Agent.board_id) == channel.board_id,
            )
        )
    ).all()

    for agent in agents:
        existing = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == channel.id,
                    col(ChannelSubscription.agent_id) == agent.id,
                )
            )
        ).first()
        if existing is None:
            session.add(
                ChannelSubscription(
                    channel_id=channel.id,
                    agent_id=agent.id,
                    notify_on="all",
                )
            )

    await session.commit()
    logger.info(
        "channel_lifecycle.channel_created channel_id=%s board_id=%s agents_subscribed=%s",
        channel.id,
        channel.board_id,
        len(agents),
    )


async def on_board_deleted(
    session: AsyncSession,
    board: Board,
    *,
    hard_delete: bool = False,
) -> None:
    """Archive (or hard-delete) all channels for a board being deleted.

    Called BEFORE the board itself is deleted. Wrapped in try/except at call site.
    """
    if not settings.channels_enabled:
        return

    channels = (
        await session.exec(select(Channel).where(col(Channel.board_id) == board.id))
    ).all()

    if not channels:
        return

    if hard_delete:
        channel_ids = [c.id for c in channels]

        # Collect thread IDs for this board's channels
        thread_ids_rows = (
            await session.exec(
                select(Thread.id).where(col(Thread.channel_id).in_(channel_ids))
            )
        ).all()
        thread_ids = list(thread_ids_rows)

        # Delete in FK-safe order: messages → threads → subscriptions → state → channels
        if thread_ids:
            await session.exec(delete(ThreadMessage).where(col(ThreadMessage.thread_id).in_(thread_ids)))  # type: ignore[call-overload]
            await session.exec(delete(Thread).where(col(Thread.id).in_(thread_ids)))  # type: ignore[call-overload]

        await session.exec(delete(ChannelSubscription).where(col(ChannelSubscription.channel_id).in_(channel_ids)))  # type: ignore[call-overload]
        await session.exec(delete(UserChannelState).where(col(UserChannelState.channel_id).in_(channel_ids)))  # type: ignore[call-overload]
        await session.exec(delete(Channel).where(col(Channel.id).in_(channel_ids)))  # type: ignore[call-overload]
    else:
        for channel in channels:
            channel.is_archived = True

    await session.commit()
    logger.info(
        "channel_lifecycle.board_deleted board_id=%s hard=%s channels=%s",
        board.id,
        hard_delete,
        len(channels),
    )


async def on_board_lead_changed(
    session: AsyncSession,
    board: Board,
    old_lead_id: UUID | None,
    new_lead_id: UUID,
) -> None:
    """Update channel subscriptions when the board lead changes."""
    if not settings.channels_enabled:
        return

    channels = (
        await session.exec(
            select(Channel).where(
                col(Channel.board_id) == board.id,
                col(Channel.is_archived).is_(False),
            )
        )
    ).all()

    for channel in channels:
        if old_lead_id is not None:
            old_sub = (
                await session.exec(
                    select(ChannelSubscription).where(
                        col(ChannelSubscription.channel_id) == channel.id,
                        col(ChannelSubscription.agent_id) == old_lead_id,
                    )
                )
            ).first()
            if old_sub is not None:
                await session.delete(old_sub)

        existing = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == channel.id,
                    col(ChannelSubscription.agent_id) == new_lead_id,
                )
            )
        ).first()
        if existing is None:
            session.add(
                ChannelSubscription(
                    channel_id=channel.id,
                    agent_id=new_lead_id,
                    notify_on="all",
                )
            )

    await session.commit()

    # Sync platform Support channel subscriptions for the new lead
    await sync_platform_support_subscribers(session, board.gateway_id)

    logger.info(
        "channel_lifecycle.lead_changed board_id=%s old=%s new=%s",
        board.id,
        old_lead_id,
        new_lead_id,
    )


async def on_agent_added_to_board(
    session: AsyncSession,
    board: Board,
    agent_id: UUID,
) -> None:
    """Subscribe a newly added agent to all channels on the board.

    Alert channels use notify_on="all" so agents react to every webhook event.
    Discussion channels use notify_on="all" so agents see every message.
    """
    if not settings.channels_enabled:
        return

    all_channels = (
        await session.exec(
            select(Channel).where(
                col(Channel.board_id) == board.id,
                col(Channel.is_archived).is_(False),
            )
        )
    ).all()

    for channel in all_channels:
        existing = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == channel.id,
                    col(ChannelSubscription.agent_id) == agent_id,
                )
            )
        ).first()
        if existing is None:
            session.add(
                ChannelSubscription(
                    channel_id=channel.id,
                    agent_id=agent_id,
                    notify_on="all",
                )
            )

    await session.commit()
    logger.info(
        "channel_lifecycle.agent_added board_id=%s agent_id=%s channels=%s",
        board.id,
        agent_id,
        len(all_channels),
    )


async def on_agent_removed_from_board(
    session: AsyncSession,
    board: Board,
    agent_id: UUID,
) -> None:
    """Remove all channel subscriptions for an agent leaving a board."""
    if not settings.channels_enabled:
        return

    channel_ids_rows = (
        await session.exec(select(Channel.id).where(col(Channel.board_id) == board.id))
    ).all()
    channel_ids = list(channel_ids_rows)

    if not channel_ids:
        return

    subs = (
        await session.exec(
            select(ChannelSubscription).where(
                col(ChannelSubscription.channel_id).in_(channel_ids),
                col(ChannelSubscription.agent_id) == agent_id,
            )
        )
    ).all()

    for sub in subs:
        await session.delete(sub)

    await session.commit()
    logger.info(
        "channel_lifecycle.agent_removed board_id=%s agent_id=%s subs_removed=%s",
        board.id,
        agent_id,
        len(subs),
    )


async def on_board_marked_platform(
    session: AsyncSession,
    board: Board,
) -> None:
    """Create Support channel and sync cross-board subscriptions when board becomes platform."""
    if not settings.channels_enabled:
        return

    # Check if Support channel already exists
    existing = (
        await session.exec(
            select(Channel).where(
                col(Channel.board_id) == board.id,
                col(Channel.slug) == "support",
            )
        )
    ).first()

    if existing is None:
        # Create Support channel
        support_channel = Channel(
            board_id=board.id,
            name=_PLATFORM_SUPPORT_CHANNEL.name,
            slug=_PLATFORM_SUPPORT_CHANNEL.slug,
            channel_type=_PLATFORM_SUPPORT_CHANNEL.channel_type,
            description=_PLATFORM_SUPPORT_CHANNEL.description,
            is_readonly=_PLATFORM_SUPPORT_CHANNEL.is_readonly,
            webhook_source_filter=_PLATFORM_SUPPORT_CHANNEL.webhook_source_filter,
            position=_PLATFORM_SUPPORT_CHANNEL.position,
        )
        session.add(support_channel)
        await session.flush()

        # Subscribe board's lead
        lead = (
            await session.exec(
                select(Agent).where(
                    col(Agent.board_id) == board.id,
                    col(Agent.is_board_lead).is_(True),
                )
            )
        ).first()
        if lead is not None:
            session.add(
                ChannelSubscription(
                    channel_id=support_channel.id,
                    agent_id=lead.id,
                    notify_on="all",
                )
            )

        await session.commit()
        logger.info(
            "channel_lifecycle.board_marked_platform board_id=%s support_channel_created=True",
            board.id,
        )

    # Sync all board leads to this Support channel
    await sync_platform_support_subscribers(session, board.gateway_id)


async def on_board_unmarked_platform(
    session: AsyncSession,
    board: Board,
) -> None:
    """Archive Support channel and remove cross-board subscriptions when board loses platform status."""
    if not settings.channels_enabled:
        return

    # Find and archive Support channel
    support_channel = (
        await session.exec(
            select(Channel).where(
                col(Channel.board_id) == board.id,
                col(Channel.slug) == "support",
            )
        )
    ).first()

    if support_channel is not None:
        support_channel.is_archived = True

        # Remove cross-board subscriptions (agents not on this board)
        board_agent_ids_rows = (
            await session.exec(
                select(Agent.id).where(col(Agent.board_id) == board.id)
            )
        ).all()
        board_agent_ids = set(board_agent_ids_rows)

        cross_board_subs = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support_channel.id,
                    col(ChannelSubscription.agent_id).notin_(board_agent_ids),
                )
            )
        ).all()

        for sub in cross_board_subs:
            await session.delete(sub)

        await session.commit()
        logger.info(
            "channel_lifecycle.board_unmarked_platform board_id=%s support_archived=True cross_board_subs_removed=%s",
            board.id,
            len(cross_board_subs),
        )


async def sync_platform_support_subscribers(
    session: AsyncSession,
    gateway_id: UUID,
) -> None:
    """Subscribe all board leads in gateway to platform Support channel.
    
    Called after board creation, lead changes, or platform status changes.
    """
    if not settings.channels_enabled:
        return

    # Find platform board for this gateway
    from app.models.boards import Board

    platform_board = (
        await session.exec(
            select(Board).where(
                col(Board.gateway_id) == gateway_id,
                col(Board.is_platform).is_(True),
            )
        )
    ).first()

    if platform_board is None:
        return

    # Find Support channel on platform board
    support_channel = (
        await session.exec(
            select(Channel).where(
                col(Channel.board_id) == platform_board.id,
                col(Channel.slug) == "support",
                col(Channel.is_archived).is_(False),
            )
        )
    ).first()

    if support_channel is None:
        return

    # Find all board leads in this gateway
    board_leads = (
        await session.exec(
            select(Agent)
            .join(Board, col(Agent.board_id) == col(Board.id))
            .where(
                col(Board.gateway_id) == gateway_id,
                col(Agent.is_board_lead).is_(True),
            )
        )
    ).all()

    subscribed_count = 0
    for lead in board_leads:
        # Check if already subscribed
        existing = (
            await session.exec(
                select(ChannelSubscription).where(
                    col(ChannelSubscription.channel_id) == support_channel.id,
                    col(ChannelSubscription.agent_id) == lead.id,
                )
            )
        ).first()

        if existing is None:
            session.add(
                ChannelSubscription(
                    channel_id=support_channel.id,
                    agent_id=lead.id,
                    notify_on="all",
                )
            )
            subscribed_count += 1

    if subscribed_count > 0:
        await session.commit()
        logger.info(
            "channel_lifecycle.sync_platform_support gateway_id=%s channel_id=%s leads_subscribed=%s",
            gateway_id,
            support_channel.id,
            subscribed_count,
        )
