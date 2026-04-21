# ruff: noqa: S101
"""Template size guardrails for injected heartbeat context."""

from __future__ import annotations

from pathlib import Path

HEARTBEAT_CONTEXT_LIMIT = 20_000
SPECIALIST_PARTIAL_LIMIT = 8_000
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def test_heartbeat_templates_fit_in_injected_context_limit() -> None:
    """Heartbeat templates must stay under gateway injected-context truncation limit."""
    targets = ("BOARD_HEARTBEAT.md.j2",)
    for name in targets:
        size = (TEMPLATES_DIR / name).stat().st_size
        assert (
            size <= HEARTBEAT_CONTEXT_LIMIT
        ), f"{name} is {size} chars (limit {HEARTBEAT_CONTEXT_LIMIT})"


def test_specialist_partials_fit_in_size_budget() -> None:
    """Specialist partials must stay under their individual size budget."""
    specialists_dir = TEMPLATES_DIR / "specialists"
    assert specialists_dir.exists(), "specialists/ directory is missing"
    partials = sorted(specialists_dir.glob("*.md.j2"))
    assert len(partials) >= 20, f"Expected at least 20 specialist partials, found {len(partials)}"
    for partial in partials:
        size = partial.stat().st_size
        assert (
            size <= SPECIALIST_PARTIAL_LIMIT
        ), f"{partial.name} is {size} chars (limit {SPECIALIST_PARTIAL_LIMIT})"
