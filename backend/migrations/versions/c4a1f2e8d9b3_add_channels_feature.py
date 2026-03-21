"""add_channels_feature

Revision ID: c4a1f2e8d9b3
Revises: merge_all_heads_2026
Create Date: 2026-03-21 22:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision = "c4a1f2e8d9b3"
down_revision = "merge_all_heads_2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create channels, threads, thread_messages, channel_subscriptions, user_channel_states tables and add thread_id to tasks."""

    # ── channels ──────────────────────────────────────────────────────────────
    op.create_table(
        "channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("channel_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("is_readonly", sa.Boolean(), nullable=False),
        sa.Column("webhook_source_filter", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("webhook_secret", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_channels_board_id"), "channels", ["board_id"], unique=False)
    op.create_index(op.f("ix_channels_channel_type"), "channels", ["channel_type"], unique=False)
    op.create_index(op.f("ix_channels_is_archived"), "channels", ["is_archived"], unique=False)
    op.create_index(op.f("ix_channels_slug"), "channels", ["slug"], unique=False)
    op.create_index(
        op.f("ix_channels_webhook_source_filter"),
        "channels",
        ["webhook_source_filter"],
        unique=False,
    )

    # ── threads ───────────────────────────────────────────────────────────────
    op.create_table(
        "threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "source_type",
            "source_ref",
            name="uq_thread_channel_source_ref",
        ),
    )
    op.create_index(op.f("ix_threads_channel_id"), "threads", ["channel_id"], unique=False)
    op.create_index(op.f("ix_threads_task_id"), "threads", ["task_id"], unique=False)
    op.create_index(op.f("ix_threads_source_type"), "threads", ["source_type"], unique=False)
    op.create_index(op.f("ix_threads_source_ref"), "threads", ["source_ref"], unique=False)
    op.create_index(op.f("ix_threads_is_resolved"), "threads", ["is_resolved"], unique=False)

    # ── thread_messages ───────────────────────────────────────────────────────
    op.create_table(
        "thread_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("sender_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=True),
        sa.Column("sender_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("content_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("is_edited", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_thread_messages_thread_id"), "thread_messages", ["thread_id"], unique=False
    )
    op.create_index(
        op.f("ix_thread_messages_sender_type"),
        "thread_messages",
        ["sender_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_thread_messages_sender_id"), "thread_messages", ["sender_id"], unique=False
    )
    op.create_index(
        op.f("ix_thread_messages_created_at"), "thread_messages", ["created_at"], unique=False
    )

    # ── channel_subscriptions ─────────────────────────────────────────────────
    op.create_table(
        "channel_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("notify_on", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "agent_id", name="uq_channel_subscription_agent"),
    )
    op.create_index(
        op.f("ix_channel_subscriptions_channel_id"),
        "channel_subscriptions",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_channel_subscriptions_agent_id"),
        "channel_subscriptions",
        ["agent_id"],
        unique=False,
    )

    # ── user_channel_states ───────────────────────────────────────────────────
    op.create_table(
        "user_channel_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_message_id", sa.Uuid(), nullable=True),
        sa.Column("is_muted", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["last_read_message_id"], ["thread_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel_id", name="uq_user_channel_state"),
    )
    op.create_index(
        op.f("ix_user_channel_states_user_id"), "user_channel_states", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_channel_states_channel_id"),
        "user_channel_states",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_channel_states_last_read_message_id"),
        "user_channel_states",
        ["last_read_message_id"],
        unique=False,
    )

    # ── tasks.thread_id ───────────────────────────────────────────────────────
    op.add_column(
        "tasks",
        sa.Column("thread_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_thread_id",
        "tasks",
        "threads",
        ["thread_id"],
        ["id"],
    )
    op.create_index(op.f("ix_tasks_thread_id"), "tasks", ["thread_id"], unique=False)

    # ── Seed default channels for all existing boards ─────────────────────────
    import uuid as _uuid
    import secrets as _secrets
    from datetime import datetime as _dt

    _now = _dt.utcnow()
    _conn = op.get_bind()

    _default_channels = [
        # (name, slug, channel_type, description, is_readonly, webhook_source_filter, position)
        ("Build Alerts",       "build-alerts",       "alert",      "CI/CD build results and failures",             True,  "build",      0),
        ("Deployment Alerts",  "deployment-alerts",  "alert",      "Deployment status and rollback notifications", True,  "deployment", 1),
        ("Test Run Alerts",    "test-run-alerts",    "alert",      "Test suite results and coverage changes",      True,  "test",       2),
        ("Production Alerts",  "production-alerts",  "alert",      "Production incidents, errors, and health",     True,  "production", 3),
        ("Development",        "development",        "discussion", "Code discussions, feature planning",           False, None,         4),
        ("DevOps",             "devops",             "discussion", "Infrastructure, pipelines, operations",        False, None,         5),
        ("Testing",            "testing",            "discussion", "Test strategy, QA discussions, bug triage",    False, None,         6),
        ("Architecture",       "architecture",       "discussion", "System design, ADRs, architectural decisions", False, None,         7),
        ("General",            "general",            "discussion", "Anything that doesn't fit elsewhere",          False, None,         8),
    ]

    _board_ids = [row[0] for row in _conn.execute(
        sa.text("SELECT id FROM boards WHERE is_archived = false OR is_archived IS NULL")
    ).fetchall()]

    for _board_id in _board_ids:
        for (_name, _slug, _ctype, _desc, _readonly, _wsf, _pos) in _default_channels:
            _conn.execute(sa.text("""
                INSERT INTO channels
                    (id, board_id, name, slug, channel_type, description,
                     is_archived, is_readonly, webhook_source_filter, webhook_secret, position,
                     created_at, updated_at)
                VALUES
                    (:id, :board_id, :name, :slug, :channel_type, :description,
                     false, :is_readonly, :webhook_source_filter, :webhook_secret, :position,
                     :now, :now)
                ON CONFLICT DO NOTHING
            """), {
                "id": str(_uuid.uuid4()),
                "board_id": str(_board_id),
                "name": _name,
                "slug": _slug,
                "channel_type": _ctype,
                "description": _desc,
                "is_readonly": _readonly,
                "webhook_source_filter": _wsf,
                "webhook_secret": _secrets.token_urlsafe(32),
                "position": _pos,
                "now": _now,
            })


def downgrade() -> None:
    """Remove channels feature tables and task.thread_id column."""
    op.drop_index(op.f("ix_tasks_thread_id"), table_name="tasks")
    op.drop_constraint("fk_tasks_thread_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "thread_id")

    op.drop_index(
        op.f("ix_user_channel_states_last_read_message_id"), table_name="user_channel_states"
    )
    op.drop_index(
        op.f("ix_user_channel_states_channel_id"), table_name="user_channel_states"
    )
    op.drop_index(op.f("ix_user_channel_states_user_id"), table_name="user_channel_states")
    op.drop_table("user_channel_states")

    op.drop_index(
        op.f("ix_channel_subscriptions_agent_id"), table_name="channel_subscriptions"
    )
    op.drop_index(
        op.f("ix_channel_subscriptions_channel_id"), table_name="channel_subscriptions"
    )
    op.drop_table("channel_subscriptions")

    op.drop_index(op.f("ix_thread_messages_created_at"), table_name="thread_messages")
    op.drop_index(op.f("ix_thread_messages_sender_id"), table_name="thread_messages")
    op.drop_index(op.f("ix_thread_messages_sender_type"), table_name="thread_messages")
    op.drop_index(op.f("ix_thread_messages_thread_id"), table_name="thread_messages")
    op.drop_table("thread_messages")

    op.drop_index(op.f("ix_threads_is_resolved"), table_name="threads")
    op.drop_index(op.f("ix_threads_source_ref"), table_name="threads")
    op.drop_index(op.f("ix_threads_source_type"), table_name="threads")
    op.drop_index(op.f("ix_threads_task_id"), table_name="threads")
    op.drop_index(op.f("ix_threads_channel_id"), table_name="threads")
    op.drop_table("threads")

    op.drop_index(op.f("ix_channels_webhook_source_filter"), table_name="channels")
    op.drop_index(op.f("ix_channels_slug"), table_name="channels")
    op.drop_index(op.f("ix_channels_is_archived"), table_name="channels")
    op.drop_index(op.f("ix_channels_channel_type"), table_name="channels")
    op.drop_index(op.f("ix_channels_board_id"), table_name="channels")
    op.drop_table("channels")

# ── ALREADY APPENDED BY PATCH ─────────────────────────────────────────────────
# The block above only creates tables. This block seeds default channels
# for all EXISTING boards so they have channels on first deploy.
