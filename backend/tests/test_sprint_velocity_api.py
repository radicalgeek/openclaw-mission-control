# ruff: noqa: INP001
"""Tests for sprint velocity API behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from app.api import sprints as sprints_api
from app.core.time import utcnow
from app.models.boards import Board
from app.models.sprints import Sprint


@dataclass
class _ExecResult:
    items: list[Any]

    def all(self) -> list[Any]:
        return self.items


class _FakeSession:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    async def exec(self, _query: Any) -> _ExecResult:
        return _ExecResult(self.items)


@pytest.mark.asyncio
async def test_board_velocity_uses_actor_read_board() -> None:
    board = Board(
        id=uuid4(),
        organization_id=uuid4(),
        gateway_id=uuid4(),
        name="Delivery Board",
        slug="delivery",
    )
    sprint = Sprint(
        organization_id=board.organization_id,
        board_id=board.id,
        name="Sprint 1",
        slug="sprint-1",
        status="completed",
        completed_minutes=300,
        actual_minutes=240,
        completed_at=utcnow(),
    )

    response = await sprints_api.board_velocity(
        board=board,
        session=_FakeSession([sprint]),  # type: ignore[arg-type]
        _actor=object(),
        window=5,
    )

    assert response.rolling_velocity_minutes == 300
    assert response.rolling_accuracy == 1.25
    assert response.sprints[0].completed_minutes == 300
    assert response.sprints[0].actual_minutes == 240
