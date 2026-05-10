# ruff: noqa: INP001
"""Gateway dispatch wake helpers."""

from __future__ import annotations

import pytest

from app.services.openclaw import gateway_dispatch
from app.services.openclaw.gateway_rpc import GatewayConfig


@pytest.mark.asyncio
async def test_reset_stuck_session_leaves_processing_session(monkeypatch) -> None:
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

    assert reset is False
    assert calls == [("sessions.list", {})]


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
                        "state": "failed",
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
        ("sessions.abort", {"key": "agent:dev:main"}),
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


@pytest.mark.asyncio
async def test_wake_agent_session_does_not_reset_idle_session_when_requested(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def _openclaw_call(
        method: str,
        params: dict[str, object] | None = None,
        *,
        config: GatewayConfig,
    ) -> object:
        calls.append((method, params or {}))
        if method == "sessions.list":
            return {"sessions": [{"key": "agent:dev:main", "state": "idle"}]}
        return {}

    monkeypatch.setattr(gateway_dispatch, "openclaw_call", _openclaw_call)

    async def _ensure_session(
        session_key: str,
        *,
        config: GatewayConfig,
        label: str,
        model: str | None = None,
        clear_model_override: bool = False,
    ) -> object:
        calls.append(
            (
                "sessions.patch",
                {
                    "key": session_key,
                    "label": label,
                    "model": model,
                    "clear_model_override": clear_model_override,
                },
            )
        )
        return {}

    async def _send_session_message_nonblocking(
        message: str,
        *,
        session_key: str,
        config: GatewayConfig,
    ) -> object:
        calls.append(
            (
                "sessions.send",
                {
                    "key": session_key,
                    "message": message,
                    "timeoutMs": 0,
                },
            )
        )
        return {}

    monkeypatch.setattr(gateway_dispatch, "ensure_session", _ensure_session)
    monkeypatch.setattr(
        gateway_dispatch,
        "send_session_message_nonblocking",
        _send_session_message_nonblocking,
    )

    service = gateway_dispatch.GatewayDispatchService(session=object())
    await service.wake_agent_session(
        session_key="agent:dev:main",
        config=GatewayConfig(url="ws://gateway.example/ws"),
        agent_name="Developer Agent",
        message="wake up",
        model="azure-foundry/gpt-4.1",
        reset_stuck_session=True,
    )

    assert calls == [
        ("sessions.list", {}),
        (
            "sessions.patch",
            {
                "key": "agent:dev:main",
                "label": "Developer Agent",
                "model": "azure-foundry/gpt-4.1",
                "clear_model_override": False,
            },
        ),
        (
            "sessions.send",
            {
                "key": "agent:dev:main",
                "message": "wake up",
                "timeoutMs": 0,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_wake_agent_session_stops_when_failed_session_reset_is_unavailable(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def _openclaw_call(
        method: str,
        params: dict[str, object] | None = None,
        *,
        config: GatewayConfig,
    ) -> object:
        calls.append((method, params or {}))
        if method == "sessions.list":
            return {"sessions": [{"key": "agent:dev:main", "state": "failed"}]}
        if method == "sessions.reset":
            raise gateway_dispatch.OpenClawGatewayError(
                "Session agent:dev:main is still active; try again in a moment."
            )
        return {}

    async def _ensure_session(*args: object, **kwargs: object) -> object:
        calls.append(("sessions.patch", {}))
        return {}

    async def _send_session_message_nonblocking(*args: object, **kwargs: object) -> object:
        calls.append(("sessions.send", {}))
        return {}

    monkeypatch.setattr(gateway_dispatch, "openclaw_call", _openclaw_call)
    monkeypatch.setattr(gateway_dispatch, "ensure_session", _ensure_session)
    monkeypatch.setattr(
        gateway_dispatch,
        "send_session_message_nonblocking",
        _send_session_message_nonblocking,
    )

    service = gateway_dispatch.GatewayDispatchService(session=object())
    error = await service.try_wake_agent_session(
        session_key="agent:dev:main",
        config=GatewayConfig(url="ws://gateway.example/ws"),
        agent_name="Developer Agent",
        message="wake up",
        reset_stuck_session=True,
    )

    assert error is not None
    assert "still active" in str(error)
    assert calls == [
        ("sessions.list", {}),
        ("sessions.abort", {"key": "agent:dev:main"}),
        ("sessions.reset", {"key": "agent:dev:main"}),
    ]
