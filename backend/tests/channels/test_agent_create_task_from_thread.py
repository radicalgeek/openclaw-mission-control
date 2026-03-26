# ruff: noqa: INP001
"""Tests for agent-accessible create-task-from-thread endpoint.

Verifies that both users and agents can create tasks from threads.
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

from app.api import threads as threads_api  # noqa: E402
from app.api.deps import ActorContext  # noqa: E402
from app.models import Channel, Thread  # noqa: E402
from app.models.agents import Agent  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402


async def _make_session_maker() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_board_channel_thread_and_agent(
    session: AsyncSession,
) -> tuple[Board, Channel, Thread, Agent]:
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
    await session.flush()

    thread = Thread(
        channel_id=channel.id,
        topic="Bug: login page not loading",
        source_type="user",
        message_count=0,
    )
    session.add(thread)

    agent = Agent(
        id=uuid4(),
        board_id=board.id,
        gateway_id=gw.id,
        name="TestAgent",
        status="online",
        is_board_lead=False,
    )
    session.add(agent)

    await session.commit()
    return board, channel, thread, agent


@pytest.mark.asyncio
async def test_agent_creates_task_from_thread() -> None:
    """Agents can create tasks from threads using ACTOR_DEP."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        _board, _channel, thread, agent = await _seed_board_channel_thread_and_agent(session)

        # Agent creates task from thread
        result = await threads_api.create_task_from_thread(
            thread_id=thread.id,
            session=session,
            actor=ActorContext(actor_type="agent", agent=agent),
        )

        # Verify task was created and linked
        assert result.task_id is not None
        assert result.is_resolved is False
        assert result.topic == "Bug: login page not loading"

        # Verify the task was created in the database
        await session.refresh(thread)
        assert thread.task_id is not None
        assert thread.task_id == result.task_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_cannot_create_duplicate_task_from_thread() -> None:
    """Agents cannot create a second task if thread already has one."""
    from fastapi import HTTPException

    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        _board, _channel, thread, agent = await _seed_board_channel_thread_and_agent(session)

        # Create first task
        await threads_api.create_task_from_thread(
            thread_id=thread.id,
            session=session,
            actor=ActorContext(actor_type="agent", agent=agent),
        )

        # Attempt to create second task should fail
        with pytest.raises(HTTPException) as exc_info:
            await threads_api.create_task_from_thread(
                thread_id=thread.id,
                session=session,
                actor=ActorContext(actor_type="agent", agent=agent),
            )

        assert exc_info.value.status_code == 409
        assert "already has a linked task" in exc_info.value.detail

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_task_from_thread_leaves_created_by_user_id_none_for_agent() -> None:
    """When an agent creates a task from thread, created_by_user_id is None."""
    from app.models.tasks import Task

    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        _board, _channel, thread, agent = await _seed_board_channel_thread_and_agent(session)

        result = await threads_api.create_task_from_thread(
            thread_id=thread.id,
            session=session,
            actor=ActorContext(actor_type="agent", agent=agent),
        )

        # Verify created_by_user_id is None for agent-created task
        task = await session.get(Task, result.task_id)
        assert task is not None
        assert task.created_by_user_id is None
        assert task.title == thread.topic

    await engine.dispose()
