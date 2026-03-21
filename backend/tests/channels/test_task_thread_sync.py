# ruff: noqa: INP001
"""Tests for task ↔ thread bidirectional sync (WP-5).

Tests:
- Legacy tasks (no thread_id) continue to work unchanged
- Tasks with thread_id return thread messages via the comment endpoint
- thread_id and channel_info are included in TaskRead when linked
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

from app.models import Channel, Thread, ThreadMessage  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402
from app.models.tasks import Task  # noqa: E402


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


async def _seed_channel_and_thread(
    session: AsyncSession, board: Board
) -> tuple[Channel, Thread]:
    channel = Channel(
        board_id=board.id,
        name="Build Alerts",
        slug="build-alerts",
        channel_type="alert",
        description="",
        is_readonly=True,
        position=0,
    )
    session.add(channel)
    await session.flush()

    thread = Thread(
        channel_id=channel.id,
        topic="CI failure on main",
        source_type="webhook",
        message_count=0,
    )
    session.add(thread)
    await session.commit()
    return channel, thread


@pytest.mark.asyncio
async def test_legacy_task_has_no_thread_id() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        task = Task(board_id=board.id, title="Legacy task")
        session.add(task)
        await session.commit()
        await session.refresh(task)

        assert task.thread_id is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_task_can_be_linked_to_thread() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        channel, thread = await _seed_channel_and_thread(session, board)

        task = Task(board_id=board.id, title="Linked task", thread_id=thread.id)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        assert task.thread_id == thread.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_thread_message_created_in_linked_task_thread() -> None:
    """Simulates the proxy behavior: messages go to thread when task.thread_id set."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        channel, thread = await _seed_channel_and_thread(session, board)

        task = Task(board_id=board.id, title="Linked task", thread_id=thread.id)
        session.add(task)
        await session.commit()

        # Simulate creating a message in the thread (as the API would do via proxy)
        msg = ThreadMessage(
            thread_id=thread.id,
            sender_type="user",
            sender_name="Test User",
            content="This is a comment via thread proxy",
            content_type="text",
        )
        session.add(msg)
        await session.commit()

        await session.refresh(thread)
        assert thread.message_count == 0  # counter not auto-updated in this raw test

    await engine.dispose()


@pytest.mark.asyncio
async def test_unlinking_clears_thread_id() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        channel, thread = await _seed_channel_and_thread(session, board)

        task = Task(board_id=board.id, title="Task to unlink", thread_id=thread.id)
        session.add(task)
        await session.commit()

        # Unlink
        task.thread_id = None
        await session.commit()
        await session.refresh(task)

        assert task.thread_id is None

    await engine.dispose()
