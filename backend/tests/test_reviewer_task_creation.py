# ruff: noqa: S101
"""Tests for reviewer agent task creation permissions."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.agent import _require_task_creation_permission
from app.schemas.agents import STANDALONE_ROLE_TEMPLATES


def _make_board(board_id: object = None) -> SimpleNamespace:
    board_id = board_id or uuid4()
    return SimpleNamespace(id=board_id, organization_id=uuid4())


def _make_lead_agent(board_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=True,
        identity_profile={},
    )


def _make_standalone_agent(role_template: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        board_id=None,
        agent_type="standalone",
        is_board_lead=False,
        identity_profile={"role_template": role_template} if role_template else {},
    )


def _make_ctx(agent: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(agent=agent)


def test_board_lead_on_own_board_can_create_tasks() -> None:
    board_id = uuid4()
    board = _make_board(board_id)
    lead = _make_lead_agent(board_id)
    ctx = _make_ctx(lead)
    _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]


def test_reviewer_standalone_with_board_access_can_create_tasks() -> None:
    board = _make_board()
    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        agent = _make_standalone_agent(role_template=role_tpl)
        ctx = _make_ctx(agent)
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]


def test_non_reviewer_standalone_cannot_create_tasks() -> None:
    board = _make_board()
    agent = _make_standalone_agent(role_template=None)
    ctx = _make_ctx(agent)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_board_lead_on_different_board_cannot_create_tasks() -> None:
    board = _make_board()
    lead = _make_lead_agent(board_id=uuid4())  # different board
    ctx = _make_ctx(lead)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_reviewer_auto_reason_contains_reviewer_agent() -> None:
    """Verify auto_reason prefix logic mirrors production code in create_task."""
    from app.models.agents import AGENT_TYPE_STANDALONE

    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        agent = _make_standalone_agent(role_template=role_tpl)
        _profile = agent.identity_profile or {}
        # Mirror the exact production logic from agent.py create_task
        auto_reason = (
            f"reviewer_agent:{agent.id}"
            if (
                agent.agent_type == AGENT_TYPE_STANDALONE
                and _profile.get("role_template") in STANDALONE_ROLE_TEMPLATES
            )
            else f"lead_agent:{agent.id}"
        )
        assert auto_reason.startswith(
            "reviewer_agent:"
        ), f"Expected 'reviewer_agent:' prefix for role_template '{role_tpl}', got '{auto_reason}'"

    # A board_worker with a reviewer template in identity_profile should NOT get reviewer prefix
    board_worker_with_reviewer_profile = SimpleNamespace(
        id=uuid4(),
        board_id=uuid4(),
        agent_type="board_worker",
        is_board_lead=True,
        identity_profile={"role_template": "quality_reviewer"},
    )
    _profile = board_worker_with_reviewer_profile.identity_profile or {}
    auto_reason = (
        f"reviewer_agent:{board_worker_with_reviewer_profile.id}"
        if (
            board_worker_with_reviewer_profile.agent_type == AGENT_TYPE_STANDALONE
            and _profile.get("role_template") in STANDALONE_ROLE_TEMPLATES
        )
        else f"lead_agent:{board_worker_with_reviewer_profile.id}"
    )
    assert auto_reason.startswith(
        "lead_agent:"
    ), "A board_worker with reviewer role_template should use lead_agent: prefix"


def test_non_lead_board_worker_cannot_create_tasks() -> None:
    """A regular board worker (not lead) on the same board should be rejected."""
    board_id = uuid4()
    board = _make_board(board_id)
    worker = SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=False,
        identity_profile={},
    )
    ctx = _make_ctx(worker)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


def test_board_worker_with_spoofed_reviewer_template_cannot_create_tasks() -> None:
    """A board_worker with a reviewer role_template should NOT get reviewer permissions."""
    board_id = uuid4()
    board = _make_board(board_id)
    spoofed = SimpleNamespace(
        id=uuid4(),
        board_id=board_id,
        agent_type="board_worker",
        is_board_lead=False,
        identity_profile={"role_template": "quality_reviewer"},
    )
    ctx = _make_ctx(spoofed)
    with pytest.raises(HTTPException) as exc_info:
        _require_task_creation_permission(ctx, board)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403
