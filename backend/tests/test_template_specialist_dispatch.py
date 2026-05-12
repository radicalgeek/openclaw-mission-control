# ruff: noqa: S101
"""Tests for specialist role_template dispatch in BOARD_HEARTBEAT.md.j2 and BOARD_AGENTS.md.j2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.schemas.agents import (
    BOARD_WORKER_ROLE_TEMPLATES,
    STANDALONE_ONLY_ROLE_TEMPLATES,
    STANDALONE_ROLE_TEMPLATES,
    VALID_ROLE_TEMPLATES,
)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

_BASE_CTX: dict[str, object] = {
    "base_url": "http://localhost:8000",
    "auth_token": "test-token",
    "board_id": "11111111-1111-1111-1111-111111111111",
    "agent_id": "22222222-2222-2222-2222-222222222222",
    "agent_name": "Test Agent",
    "is_main_agent": False,
    "is_board_lead": False,
    "is_platform_board": "false",
    "has_platform_board": "false",
    "platform_board_name": "",
    "board_rule_require_review_before_done": "false",
    "board_rule_require_approval_for_done": "false",
    "board_rule_comment_required_for_review": "false",
    "board_rule_block_status_changes_with_pending_approval": "false",
    "board_rule_only_lead_can_change_status": "false",
    "board_rule_max_agents": "10",
}


def _render(template_name: str, ctx: dict[str, object]) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    tpl = env.get_template(template_name)
    return tpl.render(**ctx)


def _ctx_with_role(role_tpl: str) -> dict[str, object]:
    return {**_BASE_CTX, "identity_role_template": role_tpl}


def _default_ctx() -> dict[str, object]:
    return {**_BASE_CTX, "identity_role_template": ""}


def test_default_worker_heartbeat_renders_without_role_template() -> None:
    result = _render("BOARD_HEARTBEAT.md.j2", _default_ctx())
    assert "Board Worker Loop" in result
    assert "Treat `merge_blocker` messages that mention you" in result
    assert "commit/push the fix" in result


def test_default_worker_agents_renders_without_role_template() -> None:
    result = _render("BOARD_AGENTS.md.j2", _default_ctx())
    assert "board agent" in result


def test_each_board_worker_role_template_renders_specialist_heartbeat() -> None:
    for role_tpl in BOARD_WORKER_ROLE_TEMPLATES:
        result = _render("BOARD_HEARTBEAT.md.j2", _ctx_with_role(role_tpl))
        # Specialist content should be included (not the default Board Worker Loop)
        assert (
            "Board Worker Loop" not in result
        ), f"role_template '{role_tpl}' fell through to default worker loop"
        assert len(result) > 500, f"role_template '{role_tpl}' rendered suspiciously short output"
        # Verify specialist-specific content was actually rendered
        assert (
            role_tpl.replace("_", " ") in result.lower() or role_tpl in result.lower()
        ), f"role_template '{role_tpl}' heartbeat does not mention its own role name"


def test_each_reviewer_role_template_renders_specialist_heartbeat() -> None:
    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        result = _render("BOARD_HEARTBEAT.md.j2", _ctx_with_role(role_tpl))
        assert (
            "Board Worker Loop" not in result
        ), f"role_template '{role_tpl}' fell through to default worker loop"
        assert len(result) > 500, f"role_template '{role_tpl}' rendered suspiciously short output"

    # Only the webhook-driven reviewers specifically mention webhook activation.
    for role_tpl in STANDALONE_ONLY_ROLE_TEMPLATES:
        result = _render("BOARD_HEARTBEAT.md.j2", _ctx_with_role(role_tpl))
        assert (
            "webhook" in result.lower()
        ), f"reviewer '{role_tpl}' heartbeat should mention webhook-driven activation"


def test_each_role_template_renders_specialist_agents() -> None:
    for role_tpl in VALID_ROLE_TEMPLATES:
        result = _render("BOARD_AGENTS.md.j2", _ctx_with_role(role_tpl))
        assert len(result) > 500, f"role_template '{role_tpl}' rendered suspiciously short output"


def test_merger_heartbeat_closes_tasks_after_mainline_merge() -> None:
    result = _render("BOARD_HEARTBEAT.md.j2", _ctx_with_role("merger"))

    assert "Check all tasks in `review` status" in result
    assert "Do not ignore a review task just because" in result
    assert "Treat conflict resolution as your primary job" in result
    assert "A Git conflict alone is not an escalation condition" in result
    assert '"status":"done"' in result
    assert "Move the task to `done` only after the code is in mainline" in result
    assert '"tags": ["chat", "merge_blocker"]' in result
    assert "Do not use `message`, `message.send`, or any channel-send tool" in result


def test_valid_role_templates_all_have_specialist_partials() -> None:
    """Every value in VALID_ROLE_TEMPLATES must have corresponding partial files."""
    for role_tpl in VALID_ROLE_TEMPLATES:
        heartbeat_path = TEMPLATES_DIR / "specialists" / f"_{role_tpl}_heartbeat.md.j2"
        agents_path = TEMPLATES_DIR / "specialists" / f"_{role_tpl}_agents.md.j2"
        assert heartbeat_path.exists(), f"Missing heartbeat partial for '{role_tpl}'"
        assert agents_path.exists(), f"Missing agents partial for '{role_tpl}'"


def test_standalone_reviewer_agents_says_standalone_not_board() -> None:
    """Standalone reviewers should see 'standalone agent', not 'board agent'."""
    for role_tpl in STANDALONE_ROLE_TEMPLATES:
        ctx = {**_ctx_with_role(role_tpl), "is_standalone": "true"}
        result = _render("BOARD_AGENTS.md.j2", ctx)
        assert (
            "standalone agent" in result.lower()
        ), f"reviewer '{role_tpl}' AGENTS.md should say 'standalone agent', not 'board agent'"
        assert (
            "board agent:" not in result.lower()
        ), f"reviewer '{role_tpl}' AGENTS.md still says 'board agent'"
