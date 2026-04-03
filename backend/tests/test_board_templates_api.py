"""Tests for the board/org template override API helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import board_templates as board_templates_api
from app.services.openclaw.provisioning_db import fetch_db_template_overrides
from app.models.board_templates import BoardTemplate
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# _validate_jinja_syntax
# ---------------------------------------------------------------------------


def test_validate_jinja_syntax_accepts_valid_template() -> None:
    """Normal Jinja2 template should not raise."""
    board_templates_api._validate_jinja_syntax(
        "Hello {{ agent_name }}! Board: {{ board_name }}."
    )


def test_validate_jinja_syntax_raises_on_invalid_template() -> None:
    """Broken Jinja2 syntax must raise HTTP 422."""
    with pytest.raises(HTTPException) as exc:
        board_templates_api._validate_jinja_syntax("{% for x in %}")
    assert exc.value.status_code == 422
    assert "Jinja2 syntax error" in exc.value.detail


def test_validate_jinja_syntax_accepts_debug_undefined() -> None:
    """Template referencing undefined variables should not raise (uses DebugUndefined)."""
    board_templates_api._validate_jinja_syntax(
        "Hello {{ undefined_var }}! Value: {{ another_undefined }}"
    )


# ---------------------------------------------------------------------------
# _stub_context
# ---------------------------------------------------------------------------


def test_stub_context_has_expected_keys() -> None:
    ctx = board_templates_api._stub_context()
    assert "agent_name" in ctx
    assert "board_name" in ctx
    assert "board_goal" in ctx or "board_objective" in ctx


# ---------------------------------------------------------------------------
# VALID_FILE_NAMES
# ---------------------------------------------------------------------------


def test_valid_file_names_contains_standard_files() -> None:
    assert "IDENTITY.md" in board_templates_api.VALID_FILE_NAMES
    assert "SOUL.md" in board_templates_api.VALID_FILE_NAMES
    assert "TOOLS.md" in board_templates_api.VALID_FILE_NAMES
    assert "USER.md" in board_templates_api.VALID_FILE_NAMES
    assert "BOOTSTRAP.md" in board_templates_api.VALID_FILE_NAMES


# ---------------------------------------------------------------------------
# fetch_db_template_overrides (provisioning_db)
# ---------------------------------------------------------------------------


class _FakeBoardTemplate:
    def __init__(
        self, *, file_name: str, template_content: str, board_id: UUID | None, org_id: UUID
    ):
        self.file_name = file_name
        self.template_content = template_content
        self.board_id = board_id
        self.organization_id = org_id


class _FakeExecResult:
    def __init__(self, rows: list[_FakeBoardTemplate]):
        self._rows = rows

    def all(self) -> list[_FakeBoardTemplate]:
        return self._rows


class _FakeSession:
    def __init__(
        self,
        org_rows: list[_FakeBoardTemplate],
        board_rows: list[_FakeBoardTemplate],
    ):
        self._org_rows = org_rows
        self._board_rows = board_rows
        self._call_count = 0

    async def exec(self, _query: object) -> _FakeExecResult:
        self._call_count += 1
        # First call → org-level, second → board-level
        if self._call_count == 1:
            return _FakeExecResult(self._org_rows)
        return _FakeExecResult(self._board_rows)


@pytest.mark.asyncio
async def test_fetch_db_template_overrides_org_only() -> None:
    """With no board_id only org-wide overrides are returned."""
    org_id = uuid4()
    org_rows = [_FakeBoardTemplate(file_name="SOUL.md", template_content="# org soul", board_id=None, org_id=org_id)]
    session = _FakeSession(org_rows=org_rows, board_rows=[])
    result = await fetch_db_template_overrides(
        session, board_id=None, organization_id=org_id  # type: ignore[arg-type]
    )
    assert result == {"SOUL.md": "# org soul"}


@pytest.mark.asyncio
async def test_fetch_db_template_overrides_board_overrides_org() -> None:
    """Board-level entry should override the matching org-level entry."""
    org_id = uuid4()
    board_id = uuid4()
    org_rows = [_FakeBoardTemplate(file_name="IDENTITY.md", template_content="# org identity", board_id=None, org_id=org_id)]
    board_rows = [_FakeBoardTemplate(file_name="IDENTITY.md", template_content="# board identity", board_id=board_id, org_id=org_id)]
    session = _FakeSession(org_rows=org_rows, board_rows=board_rows)
    result = await fetch_db_template_overrides(
        session, board_id=board_id, organization_id=org_id  # type: ignore[arg-type]
    )
    assert result == {"IDENTITY.md": "# board identity"}


@pytest.mark.asyncio
async def test_fetch_db_template_overrides_merges_distinct_keys() -> None:
    """Org entry for SOUL.md + board entry for IDENTITY.md should both appear."""
    org_id = uuid4()
    board_id = uuid4()
    org_rows = [_FakeBoardTemplate(file_name="SOUL.md", template_content="# org soul", board_id=None, org_id=org_id)]
    board_rows = [_FakeBoardTemplate(file_name="IDENTITY.md", template_content="# board identity", board_id=board_id, org_id=org_id)]
    session = _FakeSession(org_rows=org_rows, board_rows=board_rows)
    result = await fetch_db_template_overrides(
        session, board_id=board_id, organization_id=org_id  # type: ignore[arg-type]
    )
    assert result["SOUL.md"] == "# org soul"
    assert result["IDENTITY.md"] == "# board identity"


@pytest.mark.asyncio
async def test_fetch_db_template_overrides_empty() -> None:
    """No rows → empty dict returned."""
    session = _FakeSession(org_rows=[], board_rows=[])
    result = await fetch_db_template_overrides(
        session, board_id=uuid4(), organization_id=uuid4()  # type: ignore[arg-type]
    )
    assert result == {}
