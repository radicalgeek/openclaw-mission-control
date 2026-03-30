"""Planning document service: content extraction, slug generation, and task promotion."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.plans import Plan

logger = get_logger(__name__)

_PLAN_BLOCK_RE = re.compile(r"```plan\s*\n(.*?)```", re.DOTALL)
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def generate_slug(title: str) -> str:
    """Generate a URL-friendly slug from a plan title."""
    lowered = title.lower().strip()
    slug = _SLUG_CLEAN_RE.sub("-", lowered).strip("-")
    # Append short UUID fragment to guarantee uniqueness within a board.
    unique_suffix = uuid.uuid4().hex[:8]
    return f"{slug}-{unique_suffix}" if slug else unique_suffix


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def extract_plan_content(agent_reply: str) -> str | None:
    """Extract updated plan markdown from an agent reply.

    Looks for a fenced code block tagged ``plan``::

        ```plan
        # My Plan
        ...
        ```

    Returns the extracted content stripped of surrounding whitespace, or
    ``None`` when the reply contains no such block (i.e. the agent is asking a
    question or discussing the plan without proposing an update).
    """
    match = _PLAN_BLOCK_RE.search(agent_reply)
    if match:
        return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


def build_plan_system_prompt(
    *,
    board_name: str,
    board_objective: str | None,
    current_content: str,
    base_url: str,
) -> str:
    """Build the gateway prompt for a planning session start."""
    objective_text = board_objective or "Not yet defined"
    content_section = current_content.strip() or "(Empty — let's start building!)"
    return (
        f'You are the lead agent for board "{board_name}".\n'
        "The user is collaborating with you to build a planning document.\n\n"
        f"Board objective: {objective_text}\n\n"
        "## Instructions\n"
        "- Help the user create a structured markdown planning document.\n"
        "- After each exchange where you update the plan, output the complete updated plan\n"
        "  wrapped in a ```plan``` fenced code block.\n"
        "- Be collaborative: ask clarifying questions, suggest structure,\n"
        "  identify gaps, and propose improvements.\n"
        "- If the user only asks a question or gives feedback without requesting a plan\n"
        "  update, reply conversationally without a plan block.\n"
        "- When you do output a plan block, it must contain the FULL plan (not just the\n"
        "  changed sections).\n\n"
        "## Current Plan\n"
        f"{content_section}\n\n"
        "Do NOT respond in OpenClaw chat.\n"
        "All planning responses MUST be sent to Mission Control via API.\n"
        f"Mission Control base URL: {base_url}\n"
        "Use the AUTH_TOKEN from USER.md or TOOLS.md and pass it as X-Agent-Token.\n"
        "Planning update endpoint: POST /api/v1/boards/<board_id>/plans/<plan_id>/agent-update\n"
    )


def build_plan_turn_prompt(
    *,
    user_message: str,
    current_content: str,
) -> str:
    """Build the per-turn prompt sent to the agent during a planning conversation."""
    content_section = current_content.strip() or "(Empty — not yet started)"
    return (
        f"## Current Plan State\n{content_section}\n\n"
        f"## User Message\n{user_message}"
    )
