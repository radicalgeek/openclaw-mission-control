# ruff: noqa: INP001
"""Tests for the channel thread hook that fires after webhook task creation.

Tests that:
- Webhook payload → thread created in matching alert channel
- Duplicate source_ref → thread reused, not duplicated
- Hook failure is silent (does not propagate to caller)
- task.thread_id is set after the hook runs
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

from app.models import Channel, Thread, ThreadMessage  # noqa: E402
from app.models.boards import Board  # noqa: E402
from app.models.gateways import Gateway  # noqa: E402
from app.models.organizations import Organization  # noqa: E402
from app.models.tasks import Task  # noqa: E402
from app.services.channel_lifecycle import get_default_channel_definitions, on_board_created  # noqa: E402
from app.services.channel_thread_hook import on_task_created_by_webhook  # noqa: E402


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


async def _seed_task(session: AsyncSession, board: Board) -> Task:
    task = Task(
        board_id=board.id,
        title="Build failure task",
    )
    session.add(task)
    await session.commit()
    return task


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_creates_thread_for_build_failure() -> None:
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        task = await _seed_task(session, board)

        headers = {"x-github-event": "workflow_run"}
        payload = {
            "workflow_run": {
                "id": 123,
                "run_number": 1,
                "name": "CI",
                "head_branch": "main",
                "conclusion": "failure",
            },
            "repository": {"full_name": "org/api"},
        }

        await on_task_created_by_webhook(session, task, board, payload, headers)

        # Verify thread was created in build-alerts channel
        build_channel = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.slug) == "build-alerts",
                )
            )
        ).first()
        assert build_channel is not None

        threads = (
            await session.exec(
                select(Thread).where(col(Thread.channel_id) == build_channel.id)
            )
        ).all()
        assert len(threads) == 1
        assert threads[0].task_id == task.id
        assert threads[0].source_type == "webhook"

        # Verify message was created
        msg = (
            await session.exec(
                select(ThreadMessage).where(col(ThreadMessage.thread_id) == threads[0].id)
            )
        ).first()
        assert msg is not None
        assert msg.content_type == "webhook_event"

        # Verify task was linked
        await session.refresh(task)
        assert task.thread_id == threads[0].id

    await engine.dispose()


@pytest.mark.asyncio
async def test_hook_deduplicates_by_source_ref() -> None:
    """Same source_ref → same thread reused, not duplicated."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        task1 = await _seed_task(session, board)

        headers = {"x-github-event": "workflow_run"}
        payload = {
            "workflow_run": {
                "id": 999,  # Same run ID both times
                "run_number": 1,
                "name": "CI",
                "head_branch": "main",
                "conclusion": "failure",
            },
            "repository": {"full_name": "org/api"},
        }

        await on_task_created_by_webhook(session, task1, board, payload, headers)

        # Second call with same payload should not create a new thread
        task2 = await _seed_task(session, board)
        await on_task_created_by_webhook(session, task2, board, payload, headers)

        build_channel = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.slug) == "build-alerts",
                )
            )
        ).first()
        assert build_channel is not None

        threads = (
            await session.exec(
                select(Thread).where(col(Thread.channel_id) == build_channel.id)
            )
        ).all()
        assert len(threads) == 1  # Only one thread despite two calls

    await engine.dispose()


@pytest.mark.asyncio
async def test_hook_with_none_task_creates_thread_no_link() -> None:
    """When called without a task (from webhook ingest), thread is created but task_id is None."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        await on_board_created(session, board)

        headers = {"x-github-event": "deployment_status"}
        payload = {
            "deployment": {"id": 100, "environment": "production"},
            "deployment_status": {"state": "failure"},
            "repository": {"full_name": "org/api"},
        }

        await on_task_created_by_webhook(session, None, board, payload, headers)

        dep_channel = (
            await session.exec(
                select(Channel).where(
                    col(Channel.board_id) == board.id,
                    col(Channel.slug) == "deployment-alerts",
                )
            )
        ).first()
        assert dep_channel is not None

        threads = (
            await session.exec(
                select(Thread).where(col(Thread.channel_id) == dep_channel.id)
            )
        ).all()
        assert len(threads) == 1
        assert threads[0].task_id is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_hook_no_channels_returns_silently() -> None:
    """If no channels exist on the board, hook returns without error."""
    engine, session_maker = await _make_session_maker()
    async with session_maker() as session:
        board = await _seed_board(session)
        # No channels created

        task = await _seed_task(session, board)
        headers = {"x-github-event": "workflow_run"}
        payload = {
            "workflow_run": {
                "id": 1,
                "run_number": 1,
                "name": "CI",
                "head_branch": "main",
                "conclusion": "failure",
            },
            "repository": {"full_name": "org/api"},
        }

        # Should not raise even when no channels exist
        await on_task_created_by_webhook(session, task, board, payload, headers)

        await session.refresh(task)
        assert task.thread_id is None

    await engine.dispose()
