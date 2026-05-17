"""Channel thread hook — post-task-creation integration point (WP-4).

When the existing webhook handler creates a board task, this hook fires to:
1. Classify the webhook source
2. Find the matching alert channel
3. Create a Thread linked to the task
4. Create an initial ThreadMessage with the event data
5. Link task.thread_id back to the thread

This function MUST be fail-safe — if it raises, the board task must still succeed.
Always call within try/except at the call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.agents import Agent
from app.models.channel import Channel
from app.models.tasks import Task
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.webhooks.classifier import classify_webhook_event

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board
logger = get_logger(__name__)

_TASK_WORTHY_ALERT_SEVERITIES = {"error", "critical"}


def _priority_for_alert(severity: str) -> tuple[str, int]:
    if severity == "critical":
        return "critical", 95
    if severity == "error":
        return "high", 80
    if severity == "warning":
        return "medium", 50
    return "low", 20


def _triage_title(event_summary: str) -> str:
    return f"Triage alert: {event_summary}"


async def _board_lead_id(session: "AsyncSession", board: "Board") -> UUID | None:
    lead = (
        await session.exec(
            select(Agent).where(
                col(Agent.board_id) == board.id,
                col(Agent.is_board_lead).is_(True),
            )
        )
    ).first()
    return lead.id if lead is not None else None


async def _create_triage_task_for_alert(
    session: "AsyncSession",
    *,
    board: "Board",
    thread: Thread,
    event_summary: str,
    event_content: str,
    event_severity: str,
    event_url: str | None,
) -> Task:
    """Create visible triage work for an urgent alert thread.

    The board lead still owns triage. This only prevents failed builds and incidents
    from living solely as passive channel messages when the agent wake path is slow.
    """
    priority, priority_score = _priority_for_alert(event_severity)
    assigned_agent_id = await _board_lead_id(session, board)
    description = (
        "Lead triage required before assigning implementation work.\n\n"
        "Check whether this alert is a duplicate, part of an alert storm, or already "
        "covered by existing remediation work. If it is genuinely new, assign the "
        "right agent and keep this thread linked to the incident.\n\n"
        f"{event_content}"
    )
    if event_url:
        description = f"{description}\n\nSource: {event_url}"

    task = Task(
        board_id=board.id,
        title=_triage_title(event_summary),
        description=description,
        status="inbox",
        priority=priority,
        priority_score=priority_score,
        assigned_agent_id=assigned_agent_id,
        auto_created=True,
        auto_reason="webhook_alert_triage",
        thread_id=thread.id,
    )
    session.add(task)
    await session.flush()

    thread.task_id = task.id
    thread.is_resolved = False
    thread.updated_at = utcnow()

    system_msg = ThreadMessage(
        thread_id=thread.id,
        sender_type="system",
        sender_name="System",
        content=f"Created lead triage issue for this alert: #{task.id}",
        content_type="system_notification",
    )
    session.add(system_msg)
    thread.message_count = (thread.message_count or 0) + 1
    thread.last_message_at = system_msg.created_at

    return task


async def on_task_created_by_webhook(
    session: "AsyncSession",
    task: "Task | None",
    board: "Board",
    webhook_payload: dict[str, Any],
    webhook_headers: dict[str, Any],
) -> None:
    """Post-creation hook: create a linked thread in the matching alert channel.

    Called by the board webhook ingest handler AFTER a task has been created (or
    right after payload ingestion when no task exists yet). ``task`` may be None
    when called from the webhook ingest endpoint without a created task.

    Wrapped in try/except at the call site — channel failures must never block
    webhook task creation.
    """
    if not settings.channels_enabled:
        return

    try:
        # 1. Classify the webhook source
        event = classify_webhook_event(webhook_payload, webhook_headers)

        # 2. Find the matching alert channel on this board
        # IMPORTANT: Exclude direct channels - they use webhook_source_filter for agent UUIDs
        channel = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.webhook_source_filter) == event.source_category,
                    col(Channel.channel_type) != "direct",
                    col(Channel.is_archived).is_(False),
                )
            )
        ).first()

        if channel is None:
            logger.debug(
                "channel_thread_hook.no_channel board_id=%s category=%s",
                board.id,
                event.source_category,
            )
            return

        # 3. Deduplicate: check if a thread already exists for this source_ref
        existing_thread: Thread | None = None
        if event.source_ref:
            existing_thread = (
                await session.exec(
                    select(Thread).where(
                        col(Thread.channel_id) == channel.id,
                        col(Thread.source_type) == "webhook",
                        col(Thread.source_ref) == event.source_ref,
                    )
                )
            ).first()

        task_id = task.id if task is not None else None

        if existing_thread is not None:
            thread = existing_thread
            if thread.task_id is None and task_id is not None:
                thread.task_id = task_id
                thread.updated_at = utcnow()
        else:
            # 4. Create new thread
            thread = Thread(
                channel_id=channel.id,
                topic=event.topic,
                source_type="webhook",
                source_ref=event.source_ref,
                task_id=task_id,
                message_count=0,
            )
            session.add(thread)
            await session.flush()

        if (
            task is None
            and thread.task_id is None
            and event.severity in _TASK_WORTHY_ALERT_SEVERITIES
        ):
            task = await _create_triage_task_for_alert(
                session,
                board=board,
                thread=thread,
                event_summary=event.summary,
                event_content=event.content_markdown,
                event_severity=event.severity,
                event_url=event.url,
            )
            task_id = task.id

        # 5. Create the initial webhook event message
        msg = ThreadMessage(
            thread_id=thread.id,
            sender_type="webhook",
            sender_name=event.source,
            content=event.content_markdown,
            content_type="webhook_event",
            event_metadata={
                **{k: v for k, v in event.metadata.items() if k != "raw"},
                "source": event.source,
                "source_category": event.source_category,
                "event_type": event.event_type,
                "severity": event.severity,
                "summary": event.summary,
                "url": event.url,
                "raw": webhook_payload,
            },
        )
        session.add(msg)

        # Update thread counters
        thread.message_count = (thread.message_count or 0) + 1
        thread.last_message_at = msg.created_at
        thread.updated_at = utcnow()

        # 6. Link the task back to the thread (if task exists)
        if task is not None:
            task.thread_id = thread.id
            task.updated_at = utcnow()

        await session.commit()

        logger.info(
            "channel_thread_hook.linked task_id=%s thread_id=%s channel=%s",
            task_id,
            thread.id,
            channel.slug,
        )

        # 7. Notify subscribed agents if severity warrants it (non-blocking)
        if event.severity in ("error", "critical"):
            try:
                from app.services.channel_agent_routing import dispatch_channel_message_to_agents

                await dispatch_channel_message_to_agents(
                    session=session,
                    thread=thread,
                    message=msg,
                    channel=channel,
                )
            except Exception:
                logger.exception(
                    "channel_thread_hook.agent_dispatch_failed thread_id=%s",
                    thread.id,
                )

    except Exception:
        logger.exception(
            "channel_thread_hook.failed board_id=%s",
            board.id,
        )
        raise  # Re-raise so the outer try/except at the call site handles it


async def handle_direct_channel_webhook(
    session: "AsyncSession",
    channel: "Channel",
    payload: dict[str, Any],
    headers: dict[str, Any],
) -> object:
    """Handle a direct channel webhook (creates thread only, no task).

    Returns the thread ID or None on failure.
    """
    if not settings.channels_enabled:
        return None

    event = classify_webhook_event(payload, headers)

    # Deduplicate
    existing_thread: Thread | None = None
    if event.source_ref:
        existing_thread = (
            await session.exec(
                select(Thread).where(
                    col(Thread.channel_id) == channel.id,
                    col(Thread.source_type) == "webhook",
                    col(Thread.source_ref) == event.source_ref,
                )
            )
        ).first()

    if existing_thread is not None:
        thread = existing_thread
    else:
        thread = Thread(
            channel_id=channel.id,
            topic=event.topic,
            source_type="webhook",
            source_ref=event.source_ref,
            task_id=None,
            message_count=0,
        )
        session.add(thread)
        await session.flush()

    msg = ThreadMessage(
        thread_id=thread.id,
        sender_type="webhook",
        sender_name=event.source,
        content=event.content_markdown,
        content_type="webhook_event",
        event_metadata={
            "source": event.source,
            "source_category": event.source_category,
            "event_type": event.event_type,
            "severity": event.severity,
            "summary": event.summary,
            "url": event.url,
        },
    )
    session.add(msg)
    thread.message_count = (thread.message_count or 0) + 1
    thread.last_message_at = msg.created_at
    thread.updated_at = utcnow()

    await session.commit()
    return thread.id
