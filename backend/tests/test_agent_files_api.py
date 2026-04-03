"""Tests for the agent workspace file API endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api import agent_files as agent_files_api
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.schemas.agent_files import AgentFileWrite
from app.services.openclaw.gateway_rpc import OpenClawGatewayError


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeGateway:
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID = field(default_factory=uuid4)
    url: str = "ws://fake-gateway"
    token: str | None = None
    workspace_root: str | None = None


def _make_agent(
    gateway: _FakeGateway,
    *,
    name: str = "TestAgent",
    openclaw_session_id: str | None = "agent:test-session",
) -> Agent:
    return Agent(
        id=uuid4(),
        board_id=uuid4(),
        gateway_id=gateway.id,
        name=name,
        openclaw_session_id=openclaw_session_id,
        is_board_lead=False,
    )


@dataclass
class _FakeSession:
    agents: list[Agent] = field(default_factory=list)
    gateways: dict[UUID, _FakeGateway] = field(default_factory=dict)
    added: list[object] = field(default_factory=list)

    async def get(self, model_class: type, pk: UUID) -> object | None:
        if model_class is Gateway:
            return self.gateways.get(pk)  # type: ignore[return-value]
        return None

    async def exec(self, _query: object) -> "_FakeExecResult":
        return _FakeExecResult(items=self.agents)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass


@dataclass
class _FakeExecResult:
    items: list[Agent]

    async def first(self) -> Agent | None:  # type: ignore[override]
        return self.items[0] if self.items else None


# ---------------------------------------------------------------------------
# _redact_auth_token tests
# ---------------------------------------------------------------------------


def test_redact_auth_token_replaces_value() -> None:
    raw = "AUTH_TOKEN=supersecret123\nsome other content"
    result = agent_files_api._redact_auth_token(raw)
    assert "supersecret123" not in result
    assert "AUTH_TOKEN=<redacted>" in result
    assert "some other content" in result


def test_redact_auth_token_ignores_other_lines() -> None:
    raw = "# just a comment\nNAME=Alice"
    assert agent_files_api._redact_auth_token(raw) == raw


def test_redact_auth_token_handles_empty_string() -> None:
    assert agent_files_api._redact_auth_token("") == ""


# ---------------------------------------------------------------------------
# _extract_file_content tests
# ---------------------------------------------------------------------------


def test_extract_file_content_from_dict() -> None:
    payload = {"content": "hello world"}
    result = agent_files_api._extract_file_content(payload, "IDENTITY.md")
    assert result == "hello world"


def test_extract_file_content_from_nested_file_dict() -> None:
    payload = {"file": {"content": "nested content"}}
    result = agent_files_api._extract_file_content(payload, "IDENTITY.md")
    assert result == "nested content"


def test_extract_file_content_raises_on_unexpected() -> None:
    with pytest.raises(HTTPException) as exc:
        agent_files_api._extract_file_content({"unknown": "key"}, "IDENTITY.md")
    assert exc.value.status_code == 502


# ---------------------------------------------------------------------------
# _require_agent tests
# ---------------------------------------------------------------------------


class _QuerySet:
    """Minimal stub that makes Agent.objects.by_id(x).first(session) awaitable."""

    def __init__(self, agent: Agent | None):
        self._agent = agent

    async def first(self, _session: object) -> Agent | None:
        return self._agent


@pytest.mark.asyncio
async def test_require_agent_raises_404_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _FakeGateway()
    session = _FakeSession(agents=[], gateways={gateway.id: gateway})

    def _by_id(_self: object, _agent_id: object) -> _QuerySet:
        return _QuerySet(None)

    from app.db import query_manager
    monkeypatch.setattr(query_manager.ModelManager, "by_id", _by_id)

    with pytest.raises(HTTPException) as exc:
        await agent_files_api._require_agent("nonexistent-id", session, gateway.organization_id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_agent_raises_404_on_wrong_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _FakeGateway()
    agent = _make_agent(gateway)
    other_org = uuid4()
    session = _FakeSession(agents=[agent], gateways={gateway.id: gateway})

    def _by_id(_self: object, _agent_id: object) -> _QuerySet:
        return _QuerySet(agent)

    from app.db import query_manager
    monkeypatch.setattr(query_manager.ModelManager, "by_id", _by_id)

    with pytest.raises(HTTPException) as exc:
        await agent_files_api._require_agent(str(agent.id), session, other_org)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_agent_returns_agent_for_matching_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _FakeGateway()
    agent = _make_agent(gateway)
    session = _FakeSession(agents=[agent], gateways={gateway.id: gateway})

    def _by_id(_self: object, _agent_id: object) -> _QuerySet:
        return _QuerySet(agent)

    from app.db import query_manager
    monkeypatch.setattr(query_manager.ModelManager, "by_id", _by_id)
    result = await agent_files_api._require_agent(
        str(agent.id), session, gateway.organization_id  # type: ignore[arg-type]
    )
    assert result.id == agent.id
