# ruff: noqa: S101
"""Tests for role_template validation at update time (AgentUpdate schema + service layer)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agents import AgentUpdate


def test_update_with_valid_role_template_accepted() -> None:
    """AgentUpdate should accept a known role_template value."""
    update = AgentUpdate(identity_profile={"role_template": "triager"})
    assert update.identity_profile is not None
    assert update.identity_profile["role_template"] == "triager"


def test_update_with_unknown_role_template_rejected() -> None:
    """AgentUpdate should reject an unknown role_template value."""
    with pytest.raises(ValidationError, match="Invalid role_template"):
        AgentUpdate(identity_profile={"role_template": "nonexistent_role"})


def test_update_without_role_template_accepted() -> None:
    """AgentUpdate with identity_profile but no role_template should pass."""
    update = AgentUpdate(identity_profile={"role": "Coordinator"})
    assert update.identity_profile is not None
    assert "role_template" not in update.identity_profile


def test_update_with_no_identity_profile_accepted() -> None:
    """AgentUpdate without identity_profile should pass."""
    update = AgentUpdate(name="New Name")
    assert update.identity_profile is None


def test_update_clearing_role_template_accepted() -> None:
    """Sending identity_profile without role_template (to clear it) should pass."""
    update = AgentUpdate(identity_profile={"role": "Generalist"})
    assert update.identity_profile is not None


def test_update_with_each_valid_role_template() -> None:
    """All valid role_template values should be accepted in AgentUpdate."""
    from app.schemas.agents import VALID_ROLE_TEMPLATES

    for role_tpl in VALID_ROLE_TEMPLATES:
        update = AgentUpdate(identity_profile={"role_template": role_tpl})
        assert update.identity_profile is not None
        assert update.identity_profile["role_template"] == role_tpl
