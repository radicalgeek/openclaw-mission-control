"""Visibility helpers for task comment streams."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, not_


def visible_task_comment_clause(message_column: Any) -> Any:
    """Exclude operational system wake notices from user-facing task chat."""

    return and_(
        not_(message_column.like("System wake sent to %")),
        not_(message_column.like("System wake failed for %")),
    )
