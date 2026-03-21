"""Agent message routing for channel threads (WP-3).

When a user posts a message in a channel thread, this module determines
which agents to notify and dispatches the message to the Gateway.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.boards import Board
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.services.openclaw.gateway_dispatch import GatewayDispatchService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.thread import Thread
    from app.models.thread_message import ThreadMessage

logger = get_logger(__name__)


@dataclasses.dataclass
class _AgentNotification:
    agent_id: object
    agent_name: str
    is_lead: bool
    is_mentioned: bool
    session_key: str


def _is_agent_mentioned(content: str, agent_name: str) -> bool:
    """Check if an agent is @mentioned in message content."""
    pattern = rf"@{re.escape(agent_name)}\b"
    return bool(re.search(pattern, content, re.IGNORECASE))


async def get_agents_to_notify(
    session: "AsyncSession",
    thread: "Thread",
    message: "ThreadMessage",
    channel: "Channel",
) -> list["_AgentNotification"]:
    """Determine which agents should receive this channel message."""
    board = (await session.exec(select(Board).where(col(Board.id) == channel.board_id))).first()
    if board is None:
        return []

    # Get board lead agent
    lead_agent = (
        await session.exec(
            select(Agent).where(
                col(Agent.board_id) == board.id,
                col(Agent.is_board_lead).is_(True),
            )
        )
    ).first()
    lead_agent_id = lead_agent.id if lead_agent else None

    # Get all subscriptions for this channel
    subscriptions = (
        await session.exec(
            select(ChannelSubscription).where(
                col(ChannelSubscription.channel_id) == channel.id
            )
        )
    ).all()

    sub_by_agent: dict = {s.agent_id: s for s in subscriptions}

    # Ensure board lead is always considered
    if lead_agent and lead_agent.id not in sub_by_agent:
        # Create a virtual "all" subscription for the board lead
        from app.models.channel_subscription import ChannelSubscription as CS
        import uuid
        virtual = CS(
            id=uuid.uuid4(),
            channel_id=channel.id,
            agent_id=lead_agent.id,
            notify_on="all",
        )
        sub_by_agent[lead_agent.id] = virtual

    notifications: list[_AgentNotification] = []

    for agent_id, sub in sub_by_agent.items():
        agent = (await session.exec(select(Agent).where(col(Agent.id) == agent_id))).first()
        if agent is None or not agent.openclaw_session_id:
            continue

        is_mentioned = _is_agent_mentioned(message.content, agent.name)
        should_notify = False

        if agent.id == lead_agent_id:
            should_notify = True
        elif sub.notify_on == "all":
            should_notify = True
        elif sub.notify_on == "mentions" and is_mentioned:
            should_notify = True

        if should_notify:
            notifications.append(
                _AgentNotification(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    is_lead=(agent.id == lead_agent_id),
                    is_mentioned=is_mentioned,
                    session_key=agent.openclaw_session_id,
                )
            )

    return notifications


async def dispatch_channel_message_to_agents(
    session: "AsyncSession",
    thread: "Thread",
    message: "ThreadMessage",
    channel: "Channel",
) -> None:
    """Dispatch a channel message to subscribed agents via the Gateway."""
    if not settings.channels_enabled:
        return

    board = (await session.exec(select(Board).where(col(Board.id) == channel.board_id))).first()
    if board is None:
        return

    notifications = await get_agents_to_notify(session, thread, message, channel)
    if not notifications:
        return

    dispatch = GatewayDispatchService(session)
    config = await dispatch.optional_gateway_config_for_board(board)
    if config is None:
        logger.debug(
            "channel_routing.no_gateway_config board_id=%s",
            board.id,
        )
        return

    # Build context: last 20 messages for context window
    from sqlmodel import asc
    from app.models.thread_message import ThreadMessage as TM
    recent_msgs = (
        await session.exec(
            select(TM)
            .where(col(TM.thread_id) == thread.id)
            .order_by(asc(col(TM.created_at)))
            .limit(20)
        )
    ).all()

    context_lines = []
    for m in recent_msgs:
        context_lines.append(f"[{m.sender_name}]: {m.content[:300]}")
    context_str = "\n".join(context_lines)

    for notification in notifications:
        preamble = ""
        if not notification.is_lead and notification.is_mentioned:
            preamble = (
                f"You were mentioned in #{channel.name} > \"{thread.topic}\".\n\n"
            )

        gateway_message = (
            f"CHANNEL MESSAGE\n"
            f"Channel: {channel.name}\n"
            f"Thread: {thread.topic}\n"
            f"Thread ID: {thread.id}\n"
            f"Channel ID: {channel.id}\n"
            f"From: {message.sender_name}\n\n"
            f"{preamble}"
            f"Message:\n{message.content}\n\n"
            f"Recent conversation:\n{context_str}"
        )

        error = await dispatch.try_send_agent_message(
            session_key=notification.session_key,
            config=config,
            agent_name=notification.agent_name,
            message=gateway_message,
            deliver=False,
        )
        if error is not None:
            logger.warning(
                "channel_routing.dispatch_failed agent_id=%s thread_id=%s error=%s",
                notification.agent_id,
                thread.id,
                error,
            )
        else:
            logger.debug(
                "channel_routing.dispatched agent_id=%s thread_id=%s",
                notification.agent_id,
                thread.id,
            )
