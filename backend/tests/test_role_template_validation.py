# ruff: noqa: S101
"""Tests for role_template validation in AgentCreate schema."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.agents import (
    BOARD_WORKER_ROLE_TEMPLATES,
    STANDALONE_ROLE_TEMPLATES,
    VALID_ROLE_TEMPLATES,
    AgentCreate,
)


def _board_create(**kwargs: object) -> AgentCreate:
    return AgentCreate(name="agent", board_id=uuid4(), agent_type="board_worker", **kwargs)  # type: ignore[arg-type]


def _standalone_create(**kwargs: object) -> AgentCreate:
    return AgentCreate(name="agent", agent_type="standalone", gateway_id=uuid4(), **kwargs)  # type: ignore[arg-type]


def test_valid_role_templates_set_is_complete() -> None:
    expected = {
        "triager",
        "planner",
        "estimator",
        "test_agent",
        "merger",
        "ui_test",
        "visual_regression",
        "quality_reviewer",
        "security_reviewer",
        "architecture_reviewer",
    }
    assert VALID_ROLE_TEMPLATES == expected


def test_standalone_role_templates_subset() -> None:
    assert STANDALONE_ROLE_TEMPLATES.issubset(VALID_ROLE_TEMPLATES)


def test_board_worker_role_templates_disjoint_from_standalone() -> None:
    assert BOARD_WORKER_ROLE_TEMPLATES.isdisjoint(STANDALONE_ROLE_TEMPLATES)


def test_board_worker_role_template_accepted() -> None:
    for tpl in BOARD_WORKER_ROLE_TEMPLATES:
        agent = _board_create(identity_profile={"role_template": tpl})
        assert (agent.identity_profile or {}).get("role_template") == tpl


def test_standalone_role_template_accepted() -> None:
    for tpl in STANDALONE_ROLE_TEMPLATES:
        agent = _standalone_create(identity_profile={"role_template": tpl})
        assert (agent.identity_profile or {}).get("role_template") == tpl


def test_no_role_template_is_valid_for_board_worker() -> None:
    agent = _board_create()
    assert agent.identity_profile is None or "role_template" not in (agent.identity_profile or {})


def test_no_role_template_is_valid_for_standalone() -> None:
    agent = _standalone_create()
    assert agent.identity_profile is None or "role_template" not in (agent.identity_profile or {})


def test_unknown_role_template_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid role_template"):
        _board_create(identity_profile={"role_template": "not_a_real_role"})


def test_standalone_role_template_on_board_worker_rejected() -> None:
    for tpl in STANDALONE_ROLE_TEMPLATES:
        with pytest.raises(ValidationError, match="requires agent_type 'standalone'"):
            _board_create(identity_profile={"role_template": tpl})


def test_board_worker_role_template_on_standalone_rejected() -> None:
    for tpl in BOARD_WORKER_ROLE_TEMPLATES:
        with pytest.raises(ValidationError, match="requires agent_type 'board_worker'"):
            _standalone_create(identity_profile={"role_template": tpl})
