# ruff: noqa: S101
"""Tests verifying that the agent_type field_validator rejects unknown types."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.agents import VALID_AGENT_TYPES, AgentCreate


def test_all_valid_agent_types_accepted() -> None:
    """Every value in VALID_AGENT_TYPES must be accepted."""
    board_id = uuid4()
    for agent_type in VALID_AGENT_TYPES:
        needs_board = agent_type in {"board_worker", "board_lead"}
        AgentCreate(
            name="agent",
            agent_type=agent_type,
            board_id=board_id if needs_board else None,
        )


def test_unknown_agent_type_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid agent_type"):
        AgentCreate(name="agent", agent_type="super_admin", board_id=uuid4())


def test_empty_agent_type_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid agent_type"):
        AgentCreate(name="agent", agent_type="", board_id=uuid4())
