# ruff: noqa: INP001, S101
"""Tests for the programmatic onboarding seed endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.api import board_onboarding
from app.schemas.board_onboarding import (
    BoardOnboardingLeadAgentDraft,
    BoardOnboardingSeed,
    BoardOnboardingUserProfile,
)


@dataclass
class _FakeSession:
    """Minimal AsyncSession stand-in capturing model adds and commit calls."""

    added: list[object] = field(default_factory=list)
    committed: int = 0
    refreshed: list[object] = field(default_factory=list)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, value: object) -> None:
        self.refreshed.append(value)


def _make_board() -> Any:
    """Build a board namespace with all fields the seed endpoint touches."""
    return SimpleNamespace(
        id=uuid4(),
        name="CargoFlights Graduation",
        description="Graduate the CargoFlights prototype to production.",
        board_type="goal",
        objective=None,
        success_metrics=None,
        target_date=None,
        goal_confirmed=False,
        goal_source=None,
        require_approval_for_done=True,
    )


def _patch_gateway_and_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Patch GatewayDispatchService + OpenClawProvisioningService and return capture lists."""
    gateway_calls: list[Any] = []
    provisioning_calls: list[dict[str, Any]] = []

    class _FakeDispatch:
        def __init__(self, _session: object) -> None:
            self._session = _session

        async def require_gateway_config_for_board(self, board: object) -> tuple[Any, Any]:
            gateway_calls.append(board)
            return SimpleNamespace(name="gw"), SimpleNamespace(workspace_root="/tmp")

    class _FakeProvisioning:
        def __init__(self, _session: object) -> None:
            self._session = _session

        async def ensure_board_lead_agent(self, *, request: Any) -> tuple[Any, bool]:
            provisioning_calls.append(
                {
                    "board": request.board,
                    "options": request.options,
                    "user": request.user,
                },
            )
            return SimpleNamespace(id=uuid4(), is_board_lead=True), True

    monkeypatch.setattr(board_onboarding, "GatewayDispatchService", _FakeDispatch)
    monkeypatch.setattr(board_onboarding, "OpenClawProvisioningService", _FakeProvisioning)
    return gateway_calls, provisioning_calls


# ── Schema validation ──────────────────────────────────────────────────────


def test_seed_payload_requires_objective_and_metrics_for_goal_board() -> None:
    with pytest.raises(
        ValueError,
        match="Confirmed goal boards require objective and success_metrics",
    ):
        BoardOnboardingSeed(board_type="goal")


def test_seed_payload_allows_general_board_without_goal_fields() -> None:
    payload = BoardOnboardingSeed(board_type="general")
    assert payload.board_type == "general"
    assert payload.objective is None
    assert payload.lead_agent is None


def test_seed_payload_accepts_full_draft() -> None:
    payload = BoardOnboardingSeed(
        board_type="goal",
        objective="Ship CargoFlights to production",
        success_metrics={"reviewers_approve": True},
        target_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        user_profile=BoardOnboardingUserProfile(preferred_name="Mark"),
        lead_agent=BoardOnboardingLeadAgentDraft(
            name="CargoFlights PM",
            autonomy_level="autonomous",
        ),
    )
    assert payload.lead_agent is not None
    assert payload.lead_agent.name == "CargoFlights PM"
    assert payload.lead_agent.autonomy_level == "autonomous"


# ── Endpoint behaviour ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_persists_confirmed_session_and_provisions_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway_calls, provisioning_calls = _patch_gateway_and_provisioning(monkeypatch)

    board = _make_board()
    session: Any = _FakeSession()
    auth = SimpleNamespace(user=SimpleNamespace(id=uuid4()))

    payload = BoardOnboardingSeed(
        board_type="goal",
        objective="Graduate CargoFlights",
        success_metrics={"all_reviewers_approve": True},
        target_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lead_agent=BoardOnboardingLeadAgentDraft(
            name="CargoFlights PM",
            autonomy_level="balanced",
            verbosity="concise",
        ),
        user_profile=BoardOnboardingUserProfile(preferred_name="Mark"),
    )

    result = await board_onboarding.seed_onboarding(
        payload=payload,
        board=board,
        session=session,
        auth=auth,
    )

    assert result is board
    assert board.board_type == "goal"
    assert board.objective == "Graduate CargoFlights"
    assert board.success_metrics == {"all_reviewers_approve": True}
    assert board.target_date == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert board.goal_confirmed is True
    assert board.goal_source == "programmatic_seed"
    # Default autonomy ("balanced") still requires done-approval gate.
    assert board.require_approval_for_done is True

    # One onboarding session and the board were persisted.
    onboarding_added = [
        o for o in session.added if o.__class__.__name__ == "BoardOnboardingSession"
    ]
    assert len(onboarding_added) == 1
    onboarding = onboarding_added[0]
    assert onboarding.status == "confirmed"
    assert onboarding.board_id == board.id
    assert onboarding.draft_goal is not None
    assert onboarding.draft_goal["status"] == "complete"
    assert onboarding.draft_goal["board_type"] == "goal"
    assert onboarding.draft_goal["objective"] == "Graduate CargoFlights"
    assert onboarding.draft_goal["lead_agent"]["name"] == "CargoFlights PM"
    assert onboarding.draft_goal["user_profile"]["preferred_name"] == "Mark"

    assert session.committed == 1
    assert board in session.refreshed

    # Lead agent provisioning was invoked with the board and parsed options.
    assert len(gateway_calls) == 1
    assert gateway_calls[0] is board
    assert len(provisioning_calls) == 1
    call = provisioning_calls[0]
    assert call["board"] is board
    assert call["user"] is auth.user
    options = call["options"]
    assert options.agent_name == "CargoFlights PM"
    assert options.action == "provision"
    assert options.identity_profile is not None
    assert options.identity_profile.get("autonomy_level") == "balanced"
    assert options.identity_profile.get("verbosity") == "concise"


@pytest.mark.asyncio
async def test_seed_with_autonomous_lead_disables_done_approval_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gateway_and_provisioning(monkeypatch)

    board = _make_board()
    session: Any = _FakeSession()
    auth = SimpleNamespace(user=None)

    payload = BoardOnboardingSeed(
        board_type="goal",
        objective="Graduate CargoFlights",
        success_metrics={"all_reviewers_approve": True},
        lead_agent=BoardOnboardingLeadAgentDraft(autonomy_level="autonomous"),
    )

    await board_onboarding.seed_onboarding(
        payload=payload,
        board=board,
        session=session,
        auth=auth,
    )

    assert board.require_approval_for_done is False


@pytest.mark.asyncio
async def test_seed_without_lead_agent_still_provisions_default_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, provisioning_calls = _patch_gateway_and_provisioning(monkeypatch)

    board = _make_board()
    session: Any = _FakeSession()
    auth = SimpleNamespace(user=None)

    payload = BoardOnboardingSeed(
        board_type="goal",
        objective="Graduate CargoFlights",
        success_metrics={"all_reviewers_approve": True},
    )

    await board_onboarding.seed_onboarding(
        payload=payload,
        board=board,
        session=session,
        auth=auth,
    )

    assert len(provisioning_calls) == 1
    options = provisioning_calls[0]["options"]
    assert options.agent_name is None
    assert options.identity_profile is None
    assert options.action == "provision"


@pytest.mark.asyncio
async def test_seed_general_board_skips_optional_goal_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, provisioning_calls = _patch_gateway_and_provisioning(monkeypatch)

    board = _make_board()
    session: Any = _FakeSession()
    auth = SimpleNamespace(user=None)

    payload = BoardOnboardingSeed(board_type="general")

    await board_onboarding.seed_onboarding(
        payload=payload,
        board=board,
        session=session,
        auth=auth,
    )

    assert board.board_type == "general"
    assert board.objective is None
    assert board.success_metrics is None
    assert board.goal_confirmed is True

    onboarding = [o for o in session.added if o.__class__.__name__ == "BoardOnboardingSession"][0]
    assert "objective" not in onboarding.draft_goal
    assert "success_metrics" not in onboarding.draft_goal
    assert len(provisioning_calls) == 1
