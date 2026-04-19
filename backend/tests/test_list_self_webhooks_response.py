# ruff: noqa: S101
"""Regression test: list_self_webhooks must return list[AgentWebhookRead], not paginated AgentRead."""

from __future__ import annotations

from app.api.agent import router
from app.schemas.agent_webhooks import AgentWebhookRead


def test_list_self_webhooks_response_model_is_not_paginated_agent_read() -> None:
    """list_self_webhooks must NOT declare response_model=DefaultLimitOffsetPage[AgentRead]."""
    for route in router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set())
        if path in ("/self/webhooks", "/agent/self/webhooks") and "GET" in methods:
            response_model = getattr(route, "response_model", None)
            origin = getattr(response_model, "__origin__", None)
            assert origin is list, (
                f"Expected list origin for /self/webhooks response_model, got {origin!r}."
            )
            args = getattr(response_model, "__args__", ())
            if args:
                assert args[0] is AgentWebhookRead, (
                    f"Expected list[AgentWebhookRead] but got list[{args[0]}]"
                )
            return
    raise AssertionError("Route /self/webhooks (or /agent/self/webhooks) not found in agent router")
