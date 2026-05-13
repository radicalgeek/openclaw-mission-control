# ruff: noqa: S101
"""Tests for board snapshot sprint-review reconciliation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api import boards as boards_api
from app.models.boards import Board


@pytest.mark.asyncio
async def test_board_snapshot_reconciles_review_ready_sprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = Board(id=uuid4(), organization_id=uuid4(), name="Board")
    calls: list[str] = []

    async def fake_check_sprint_completion(_session: object, *, board_id: object) -> None:
        calls.append(str(board_id))

    async def fake_build_board_snapshot(_session: object, _board: Board) -> object:
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.sprint_lifecycle.SprintService.check_sprint_completion",
        fake_check_sprint_completion,
    )
    monkeypatch.setattr(boards_api, "build_board_snapshot", fake_build_board_snapshot)

    result = await boards_api.get_board_snapshot(board=board, session=object())  # type: ignore[arg-type]

    assert result == {"ok": True}
    assert calls == [str(board.id)]
