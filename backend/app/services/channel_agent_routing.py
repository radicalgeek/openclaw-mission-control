"""Agent message routing for channel threads (WP-3).

When a user posts a message in a channel thread, this module determines
which agents to notify and dispatches the message to the Gateway.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.models.agents import Agent
from app.models.boards import Board
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.services.mentions import extract_mentions, matches_agent_mention
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
    board_id: UUID  # agent's own board — used for per-agent gateway config lookup



async def get_agents_to_notify(
    session: "AsyncSession",
    thread: "Thread",
    message: "ThreadMessage",
    channel: "Channel",
) -> list["_AgentNotification"]:
    """Determine which agents should receive this channel message.

    Routing rules:
    - The message sender (if an agent) is never dispatched back to themselves.
    - For direct channels: only the target agent is notified.
    - For regular channels: the board lead always responds; other subscribed
      agents only respond when @mentioned.
    - For the platform Support channel: the platform lead always responds;
      cross-board leads only receive dispatches for threads their board started
      (identified by thread.owner_board_id) or when @mentioned.
    """
    board = (await session.exec(select(Board).where(col(Board.id) == channel.board_id))).first()
    if board is None:
        return []

    sender_agent_id: UUID | None
    if message.sender_type == "agent" and message.sender_id is not None:
        try:
            sender_agent_id = UUID(str(message.sender_id))
        except (ValueError, AttributeError):
            sender_agent_id = None
    else:
        sender_agent_id = None

    # For direct channels, only notify the specific agent in webhook_source_filter
    if channel.channel_type == "direct" and channel.webhook_source_filter:
        try:
            target_agent_id = UUID(channel.webhook_source_filter)
            if sender_agent_id is not None and target_agent_id == sender_agent_id:
                # Don't dispatch back to the agent who just sent a message
                return []
            agent = (await session.exec(select(Agent).where(col(Agent.id) == target_agent_id))).first()
            if agent and agent.openclaw_session_id and agent.board_id is not None:
                _mentions = extract_mentions(message.content)
                return [
                    _AgentNotification(
                        agent_id=agent.id,
                        agent_name=agent.name,
                        is_lead=agent.is_board_lead,
                        is_mentioned=matches_agent_mention(agent, _mentions),
                        session_key=agent.openclaw_session_id,
                        board_id=agent.board_id,
                    )
                ]
        except (ValueError, AttributeError):
            logger.warning(
                "channel_routing.invalid_direct_channel channel_id=%s filter=%s",
                channel.id,
                channel.webhook_source_filter,
            )
        return []

    # Determine if this is the platform Support channel.
    # In Support: platform lead always responds; cross-board leads only receive
    # dispatches for threads their board owns OR when @mentioned.
    is_support_channel = (channel.slug == "support" and board.is_platform)

    # Get board lead agent (the channel's own board lead)
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

    sub_by_agent: dict[object, ChannelSubscription] = {s.agent_id: s for s in subscriptions}

    # Ensure the board lead is always considered even if not explicitly subscribed
    if lead_agent and lead_agent.id not in sub_by_agent:
        from uuid import uuid4
        from app.models.channel_subscription import ChannelSubscription as CS
        virtual = CS(
            id=uuid4(),
            channel_id=channel.id,
            agent_id=lead_agent.id,
            notify_on="all",
        )
        sub_by_agent[lead_agent.id] = virtual

    notifications: list[_AgentNotification] = []
    _mentions = extract_mentions(message.content)

    for agent_id, sub in sub_by_agent.items():
        agent = (await session.exec(select(Agent).where(col(Agent.id) == agent_id))).first()
        if agent is None or not agent.openclaw_session_id:
            continue

        # Never dispatch back to the agent who sent this message (prevents reply loops)
        if sender_agent_id is not None and agent.id == sender_agent_id:
            continue

        # Agent must have a valid board to resolve gateway config
        agent_board_id = agent.board_id
        if agent_board_id is None:
            continue

        is_mentioned = matches_agent_mention(agent, _mentions)
        is_platform_lead = agent.id == lead_agent_id
        is_cross_board_agent = agent_board_id != board.id
        should_notify = False

        if sub.notify_on == "none":
            # Explicitly opted out
            should_notify = False
        elif is_support_channel and is_cross_board_agent:
            # Cross-board subscriber in the platform Support channel:
            # only dispatch when the thread belongs to their board OR they're @mentioned.
            if is_mentioned:
                should_notify = True
            elif thread.owner_board_id is not None and thread.owner_board_id == agent_board_id:
                should_notify = True
        elif is_platform_lead:
            # The channel's own board lead always responds
            should_notify = True
        elif is_mentioned:
            # Non-lead agents only respond when explicitly @mentioned
            should_notify = True
        # Note: notify_on="all" for non-lead, non-mentioned agents is intentionally
        # ignored here — dispatch should only trigger responses, not broadcast to
        # every subscriber. Subscriptions track membership; routing controls responses.

        if should_notify:
            notifications.append(
                _AgentNotification(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    is_lead=is_platform_lead,
                    is_mentioned=is_mentioned,
                    session_key=agent.openclaw_session_id,
                    board_id=agent_board_id,
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

    notifications = await get_agents_to_notify(session, thread, message, channel)
    if not notifications:
        return

    dispatch = GatewayDispatchService(session)

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
        context_lines.append(f"[{m.sender_name}]: {m.content}")
    context_str = "\n".join(context_lines)

    # Cache gateway configs per board to avoid redundant DB lookups
    _config_cache: dict[UUID, object] = {}

    async def _get_config_for_board(b_id: UUID) -> object:
        if b_id in _config_cache:
            return _config_cache[b_id]
        agent_board = await session.get(Board, b_id)
        cfg = await dispatch.optional_gateway_config_for_board(agent_board) if agent_board else None
        _config_cache[b_id] = cfg
        return cfg

    for notification in notifications:
        # Use each agent's own board's gateway config — important for cross-board
        # subscriptions where agents may live on different gateway configurations.
        config = await _get_config_for_board(notification.board_id)
        if config is None:
            logger.debug(
                "channel_routing.no_gateway_config agent_id=%s board_id=%s",
                notification.agent_id,
                notification.board_id,
            )
            continue

        preamble = ""
        if not notification.is_lead and notification.is_mentioned:
            preamble = (
                f"You were mentioned in #{channel.name} > \"{thread.topic}\".\n\n"
            )

        reply_instructions = (
            f"\n\n---\n"
            f"To reply in this thread, make an HTTP POST request:\n"
            f"  URL: {settings.base_url}/api/v1/threads/{thread.id}/messages\n"
            f"  Header: X-Agent-Token: <your MC agent token from TOOLS.md>\n"
            f"  Header: Content-Type: application/json\n"
            f"  Body: {{\"content\": \"your reply here\"}}\n"
            f"\n"
            f"You MUST reply in the thread — do not just reply in this session."
        )

        gateway_message = (
            f"CHANNEL MESSAGE\n"
            f"Channel: #{channel.name}\n"
            f"Thread: {thread.topic}\n"
            f"Thread ID: {thread.id}\n"
            f"Channel ID: {channel.id}\n"
            f"From: {message.sender_name}\n\n"
            f"{preamble}"
            f"Message:\n{message.content}\n\n"
            f"Recent conversation:\n{context_str}"
            f"{reply_instructions}"
        )

        error = await dispatch.try_send_agent_message(
            session_key=notification.session_key,
            config=config,  # type: ignore[arg-type]
            agent_name=notification.agent_name,
            message=gateway_message,
            deliver=True,  # trigger the LLM so the agent actually generates a reply
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
