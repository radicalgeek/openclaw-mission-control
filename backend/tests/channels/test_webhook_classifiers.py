# ruff: noqa: INP001
"""Tests for webhook event classifiers."""

from __future__ import annotations

import pytest

from app.webhooks.classifier import (
    DeploymentClassifier,
    GenericClassifier,
    GitHubActionsClassifier,
    GitHubPRClassifier,
    TestResultsClassifier,
    classify_webhook_event,
)


# ---------------------------------------------------------------------------
# GitHub Actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_actions_failure_classified() -> None:
    headers = {"x-github-event": "workflow_run"}
    payload = {
        "workflow_run": {
            "id": 123,
            "run_number": 42,
            "name": "CI",
            "head_branch": "main",
            "conclusion": "failure",
            "html_url": "https://github.com/example",
        },
        "repository": {"full_name": "org/api"},
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "build"
    assert event.event_type == "build_failure"
    assert event.severity == "error"
    assert "42" in event.topic
    assert "failure" in event.summary.lower() or "❌" in event.summary


@pytest.mark.asyncio
async def test_github_actions_success_classified() -> None:
    headers = {"x-github-event": "workflow_run"}
    payload = {
        "workflow_run": {
            "id": 456,
            "run_number": 99,
            "name": "CI",
            "head_branch": "main",
            "conclusion": "success",
        },
        "repository": {"full_name": "org/api"},
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "build"
    assert event.event_type == "build_success"
    assert event.severity == "info"


@pytest.mark.asyncio
async def test_github_actions_can_classify() -> None:
    classifier = GitHubActionsClassifier()
    assert classifier.can_classify({"x-github-event": "workflow_run"}, {})
    assert classifier.can_classify({"x-github-event": "check_suite"}, {})
    assert not classifier.can_classify({"x-github-event": "pull_request"}, {})


# ---------------------------------------------------------------------------
# GitHub PR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_pr_opened_classified() -> None:
    headers = {"x-github-event": "pull_request"}
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Fix bug",
            "html_url": "https://github.com/example/pull/42",
            "user": {"login": "dev"},
        },
        "repository": {"full_name": "org/api"},
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "build"
    assert event.event_type == "pr_opened"
    assert "42" in event.topic


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deployment_success_classified() -> None:
    headers = {"x-github-event": "deployment_status"}
    payload = {
        "deployment": {"id": 789, "environment": "production"},
        "deployment_status": {"state": "success", "target_url": "https://app.prod.example"},
        "repository": {"full_name": "org/api"},
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "deployment"
    assert event.severity == "info"
    assert "production" in event.topic.lower() or "production" in event.summary.lower()


@pytest.mark.asyncio
async def test_deployment_failure_classified() -> None:
    headers = {"x-github-event": "deployment_status"}
    payload = {
        "deployment": {"id": 789, "environment": "staging"},
        "deployment_status": {"state": "failure"},
        "repository": {"full_name": "org/api"},
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "deployment"
    assert event.severity == "error"


# ---------------------------------------------------------------------------
# Test Results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_results_classified() -> None:
    headers = {}
    payload = {
        "test_results": {"passed": 95, "failed": 5},
        "suite_name": "Integration Tests",
        "result": "failed",
    }
    event = classify_webhook_event(payload, headers)
    assert event.source_category == "test"
    assert event.severity == "error"
    assert "integration tests" in event.topic.lower() or "integration tests" in event.summary.lower()


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generic_always_classifies() -> None:
    classifier = GenericClassifier()
    event = classifier.classify({}, {"some": "data"})
    assert event.source_category == "production"
    assert event.event_type == "generic_event"


@pytest.mark.asyncio
async def test_classify_unknown_webhook_uses_generic() -> None:
    event = classify_webhook_event({"unknown": "payload"}, {})
    assert event.source_category == "production"


# ---------------------------------------------------------------------------
# Deduplication source_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_workflow_run_same_source_ref() -> None:
    headers = {"x-github-event": "workflow_run"}
    payload = {
        "workflow_run": {
            "id": 999,
            "run_number": 1,
            "name": "CI",
            "head_branch": "main",
            "conclusion": "failure",
        },
        "repository": {"full_name": "org/api"},
    }
    event1 = classify_webhook_event(payload, headers)
    event2 = classify_webhook_event(payload, headers)
    assert event1.source_ref == event2.source_ref
