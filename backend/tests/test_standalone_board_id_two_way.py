# ruff: noqa: S101
"""Tests for the two-way board_id enforcement on AgentCreate."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.agents import AgentCreate


def test_board_worker_without_board_id_rejected() -> None:
    with pytest.raises(ValidationError, match="must have a board_id"):
        AgentCreate(name="agent", agent_type="board_worker")


def test_board_lead_without_board_id_rejected() -> None:
    with pytest.raises(ValidationError, match="must have a board_id"):
        AgentCreate(name="agent", agent_type="board_lead")


def test_standalone_with_board_id_rejected() -> None:
    with pytest.raises(ValidationError, match="must not have a board_id"):
        AgentCreate(name="agent", agent_type="standalone", board_id=uuid4())


def test_gateway_main_with_board_id_rejected() -> None:
    with pytest.raises(ValidationError, match="must not have a board_id"):
        AgentCreate(name="agent", agent_type="gateway_main", board_id=uuid4())


def test_board_worker_with_board_id_accepted() -> None:
    agent = AgentCreate(name="agent", agent_type="board_worker", board_id=uuid4())
    assert agent.board_id is not None


def test_board_lead_with_board_id_accepted() -> None:
    agent = AgentCreate(name="agent", agent_type="board_lead", board_id=uuid4())
    assert agent.board_id is not None


def test_standalone_without_board_id_accepted() -> None:
    agent = AgentCreate(name="agent", agent_type="standalone")
    assert agent.board_id is None


def test_gateway_main_without_board_id_accepted() -> None:
    agent = AgentCreate(name="agent", agent_type="gateway_main")
    assert agent.board_id is None
