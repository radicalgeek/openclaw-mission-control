"""Add estimation/actuals fields, priority_score, and extended task statuses.

Adds:
- tasks.estimate_minutes (int, nullable)
- tasks.actual_minutes (int, nullable)
- tasks.done_at (datetime with timezone, nullable)
- tasks.priority_score (int, not null, default 50) — backfilled from priority string
- sprints.committed_minutes (int, nullable)
- sprints.completed_minutes (int, nullable)
- sprints.actual_minutes (int, nullable)

The task status enum is now:
  triage → backlog → inbox → in_progress → review → done → archived

Existing tasks keep their current status values (inbox/in_progress/review/done
are all valid in the new enum).

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a7
Create Date: 2026-04-04 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a7"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Add estimation, actuals, priority_score, and velocity columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ------------------------------------------------------------------ tasks
    task_cols = _column_names(inspector, "tasks")

    if "estimate_minutes" not in task_cols:
        op.add_column("tasks", sa.Column("estimate_minutes", sa.Integer(), nullable=True))

    if "actual_minutes" not in task_cols:
        op.add_column("tasks", sa.Column("actual_minutes", sa.Integer(), nullable=True))

    if "done_at" not in task_cols:
        op.add_column("tasks", sa.Column("done_at", sa.DateTime(timezone=True), nullable=True))

    if "priority_score" not in task_cols:
        op.add_column(
            "tasks",
            sa.Column("priority_score", sa.Integer(), nullable=True),
        )
        # Backfill existing rows from the string priority field
        op.execute(
            """
            UPDATE tasks SET priority_score = CASE
                WHEN priority = 'critical' THEN 90
                WHEN priority = 'high'     THEN 65
                WHEN priority = 'medium'   THEN 35
                WHEN priority = 'low'      THEN 15
                ELSE 35
            END
            """
        )
        op.alter_column("tasks", "priority_score", nullable=False, server_default="50")

    # Index on priority_score for backlog sorting
    task_indexes = _index_names(inspector, "tasks")
    if "ix_tasks_priority_score" not in task_indexes:
        op.create_index("ix_tasks_priority_score", "tasks", ["priority_score"])

    # --------------------------------------------------------------- sprints
    sprint_cols = _column_names(inspector, "sprints")

    if "committed_minutes" not in sprint_cols:
        op.add_column("sprints", sa.Column("committed_minutes", sa.Integer(), nullable=True))

    if "completed_minutes" not in sprint_cols:
        op.add_column("sprints", sa.Column("completed_minutes", sa.Integer(), nullable=True))

    if "actual_minutes" not in sprint_cols:
        op.add_column("sprints", sa.Column("actual_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove estimation, actuals, priority_score, and velocity columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    task_cols = _column_names(inspector, "tasks")
    task_indexes = _index_names(inspector, "tasks")

    if "ix_tasks_priority_score" in task_indexes:
        op.drop_index("ix_tasks_priority_score", table_name="tasks")

    for col in ("priority_score", "done_at", "actual_minutes", "estimate_minutes"):
        if col in task_cols:
            op.drop_column("tasks", col)

    sprint_cols = _column_names(inspector, "sprints")
    for col in ("actual_minutes", "completed_minutes", "committed_minutes"):
        if col in sprint_cols:
            op.drop_column("sprints", col)
