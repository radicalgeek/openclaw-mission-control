# ruff: noqa: INP001
"""Unit tests for channel model and schema validation."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

os.environ["AUTH_MODE"] = "local"
os.environ["LOCAL_AUTH_TOKEN"] = "test-local-token-0123456789-0123456789-0123456789x"
os.environ["BASE_URL"] = "http://localhost:8000"


from app.models.channel import Channel  # noqa: E402
from app.models.thread import Thread  # noqa: E402
from app.models.thread_message import ThreadMessage  # noqa: E402
from app.models.channel_subscription import ChannelSubscription  # noqa: E402
from app.schemas.channels import ChannelCreate, ChannelRead, SubscriptionUpsert  # noqa: E402
from app.schemas.threads import ThreadCreate, ThreadRead, ThreadUpdate  # noqa: E402
from app.schemas.thread_messages import ThreadMessageCreate, ThreadMessageRead  # noqa: E402


def test_channel_model_defaults() -> None:
    channel = Channel(
        board_id=uuid4(),
        name="Test Channel",
        slug="test-channel",
    )
    assert channel.channel_type == "discussion"
    assert channel.is_archived is False
    assert channel.is_readonly is False
    assert channel.position == 0
    assert len(channel.webhook_secret) == 64  # 32 bytes hex


def test_channel_create_schema() -> None:
    payload = ChannelCreate(
        name="My Channel",
        description="Test description",
        channel_type="alert",
    )
    assert payload.channel_type == "alert"
    assert payload.webhook_source_filter is None


def test_channel_read_schema_from_model() -> None:
    channel = Channel(
        id=uuid4(),
        board_id=uuid4(),
        name="Build Alerts",
        slug="build-alerts",
        channel_type="alert",
        description="Builds",
        is_archived=False,
        is_readonly=True,
        position=0,
    )
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    channel.created_at = now
    channel.updated_at = now

    read = ChannelRead.model_validate(channel, from_attributes=True)
    assert read.name == "Build Alerts"
    assert read.channel_type == "alert"
    assert read.is_readonly is True
    assert read.unread_count == 0


def test_thread_create_schema() -> None:
    payload = ThreadCreate(topic="Build failed", content="Initial message")
    assert payload.topic == "Build failed"
    assert payload.content == "Initial message"


def test_thread_model_defaults() -> None:
    thread = Thread(
        channel_id=uuid4(),
        topic="Test thread",
    )
    assert thread.is_resolved is False
    assert thread.is_pinned is False
    assert thread.message_count == 0
    assert thread.source_type == "user"


def test_thread_message_create_schema() -> None:
    payload = ThreadMessageCreate(content="Hello from the thread")
    assert payload.content == "Hello from the thread"
    assert payload.content_type == "text"


def test_thread_message_model_defaults() -> None:
    msg = ThreadMessage(
        thread_id=uuid4(),
        sender_type="user",
        sender_name="User",
        content="test",
    )
    assert msg.is_edited is False
    assert msg.content_type == "text"
    assert msg.event_metadata is None


def test_subscription_upsert_defaults() -> None:
    payload = SubscriptionUpsert()
    assert payload.notify_on == "all"


def test_subscription_notify_on_values() -> None:
    for value in ("all", "mentions", "none"):
        s = SubscriptionUpsert(notify_on=value)
        assert s.notify_on == value


def test_thread_update_optional_fields() -> None:
    # All fields optional
    update = ThreadUpdate()
    assert update.topic is None
    assert update.is_resolved is None
    assert update.is_pinned is None

    update2 = ThreadUpdate(is_resolved=True, topic="Updated topic")
    assert update2.is_resolved is True
    assert update2.topic == "Updated topic"
