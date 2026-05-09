# ruff: noqa: S101
"""Token repair tests for agent lifecycle updates."""

from __future__ import annotations

from uuid import uuid4

import pytest

import app.services.openclaw.lifecycle_orchestrator as lifecycle
from app.core.agent_tokens import hash_agent_token, verify_agent_token
from app.models.agents import AGENT_TYPE_STANDALONE, Agent
from app.models.gateways import Gateway
from app.services.openclaw.gateway_rpc import OpenClawGatewayError


def _gateway() -> Gateway:
    return Gateway(
        id=uuid4(),
        organization_id=uuid4(),
        name="Primary",
        url="ws://gateway.example/ws",
        token="gateway-token",
        workspace_root="/state",
    )


def _agent(token: str) -> Agent:
    agent_id = uuid4()
    return Agent(
        id=agent_id,
        openclaw_session_id=f"agent:standalone-{agent_id}:main",
        gateway_id=uuid4(),
        name="Triager",
        agent_type=AGENT_TYPE_STANDALONE,
        agent_token_hash=hash_agent_token(token),
    )


@pytest.mark.asyncio
async def test_resolve_update_auth_token_reuses_matching_workspace_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent("current-token")
    captured: dict[str, object] = {}

    async def _fake_openclaw_call(method: str, params: object, **_kwargs: object) -> object:
        captured["method"] = method
        captured["params"] = params
        return {"content": "BASE_URL=https://example.test\nAUTH_TOKEN=current-token\n"}

    monkeypatch.setattr(lifecycle, "openclaw_call", _fake_openclaw_call)

    token = await lifecycle._resolve_update_auth_token(
        gateway=_gateway(),
        agent=agent,
        board=None,
    )

    assert token == "current-token"
    assert captured["method"] == "agents.files.get"
    assert captured["params"] == {
        "agentId": f"standalone-{agent.id}",
        "name": "TOOLS.md",
    }


@pytest.mark.asyncio
async def test_resolve_update_auth_token_rotates_stale_workspace_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent("current-token")

    async def _fake_openclaw_call(_method: str, _params: object, **_kwargs: object) -> object:
        return {"file": {"content": "AUTH_TOKEN=stale-token\n"}}

    monkeypatch.setattr(lifecycle, "openclaw_call", _fake_openclaw_call)

    token = await lifecycle._resolve_update_auth_token(
        gateway=_gateway(),
        agent=agent,
        board=None,
    )

    assert token
    assert token != "stale-token"
    assert verify_agent_token(token, agent.agent_token_hash or "")


@pytest.mark.asyncio
async def test_resolve_update_auth_token_preserves_when_workspace_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent("current-token")
    original_hash = agent.agent_token_hash

    async def _fake_openclaw_call(_method: str, _params: object, **_kwargs: object) -> object:
        raise OpenClawGatewayError("agent not found")

    monkeypatch.setattr(lifecycle, "openclaw_call", _fake_openclaw_call)

    token = await lifecycle._resolve_update_auth_token(
        gateway=_gateway(),
        agent=agent,
        board=None,
    )

    assert token is None
    assert agent.agent_token_hash == original_hash
