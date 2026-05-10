# ruff: noqa: INP001
"""Gateway dispatch wake helpers."""

from __future__ import annotations

import pytest

from app.services.openclaw import gateway_dispatch
from app.services.openclaw.gateway_rpc import GatewayConfig


@pytest.mark.asyncio
async def test_reset_stuck_session_resets_processing_session(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def _openclaw_call(
        method: str,
        params: dict[str, object] | None = None,
        *,
        config: GatewayConfig,
    ) -> object:
        calls.append((method, params or {}))
        if method == "sessions.list":
            return {"sessions": [{"key": "agent:dev:main", "state": "processing"}]}
        return {}

    monkeypatch.setattr(gateway_dispatch, "openclaw_call", _openclaw_call)

    reset = await gateway_dispatch.reset_stuck_session_if_needed(
        session_key="agent:dev:main",
        config=GatewayConfig(url="ws://gateway.example/ws"),
    )

    assert reset is True
    assert calls == [
        ("sessions.list", {}),
        ("sessions.reset", {"key": "agent:dev:main"}),
    ]


@pytest.mark.asyncio
async def test_reset_stuck_session_accepts_gateway_session_key_field(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def _openclaw_call(
        method: str,
        params: dict[str, object] | None = None,
        *,
        config: GatewayConfig,
    ) -> object:
        calls.append((method, params or {}))
        if method == "sessions.list":
            return {
                "sessions": [
                    {
                        "sessionKey": "agent:dev:main",
                        "state": "processing",
                    }
                ]
            }
        return {}

    monkeypatch.setattr(gateway_dispatch, "openclaw_call", _openclaw_call)

    reset = await gateway_dispatch.reset_stuck_session_if_needed(
        session_key="agent:dev:main",
        config=GatewayConfig(url="ws://gateway.example/ws"),
    )

    assert reset is True
    assert calls == [
        ("sessions.list", {}),
        ("sessions.reset", {"key": "agent:dev:main"}),
    ]


@pytest.mark.asyncio
async def test_reset_stuck_session_leaves_idle_session(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def _openclaw_call(
        method: str,
        params: dict[str, object] | None = None,
        *,
        config: GatewayConfig,
    ) -> object:
        calls.append((method, params or {}))
        return {"sessions": [{"key": "agent:dev:main", "state": "idle"}]}

    monkeypatch.setattr(gateway_dispatch, "openclaw_call", _openclaw_call)

    reset = await gateway_dispatch.reset_stuck_session_if_needed(
        session_key="agent:dev:main",
        config=GatewayConfig(url="ws://gateway.example/ws"),
    )

    assert reset is False
    assert calls == [("sessions.list", {})]
