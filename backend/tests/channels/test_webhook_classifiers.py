# ruff: noqa: INP001
"""Tests for webhook event classifiers."""

from __future__ import annotations

import pytest

from app.webhooks.classifier import (
    GenericClassifier,
    GitHubActionsClassifier,
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
    assert event.source_category == "cicd"
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
    assert event.source_category == "cicd"
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
    assert event.source_category == "cicd"
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
    assert event.source_category == "cicd"
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
    assert event.source_category == "cicd"
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
    assert event.source_category == "cicd"
    assert event.severity == "error"
    assert (
        "integration tests" in event.topic.lower() or "integration tests" in event.summary.lower()
    )


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generic_always_classifies() -> None:
    classifier = GenericClassifier()
    event = classifier.classify({}, {"some": "data"})
    assert event.source_category == "observability"
    assert event.event_type == "generic_event"


@pytest.mark.asyncio
async def test_classify_unknown_webhook_uses_generic() -> None:
    event = classify_webhook_event({"unknown": "payload"}, {})
    assert event.source_category == "observability"


@pytest.mark.asyncio
async def test_azure_devops_pipeline_failure_classified_as_cicd() -> None:
    payload = {
        "pipeline_run_id": "224315",
        "status": "failed",
        "notify_job_status": "Succeeded",
        "commit_sha": "9739cb07d93a927bb4367a9667d40b71b41fbfc7",
        "branch": "main",
        "repo_url": "https://dev.azure.com/oagaviation/ai-catalyst/_git/runway-cargoflights-runway",
        "stage_results": {
            "LintTest": "failed",
            "Build": "unknown",
        },
        "details_url": "https://dev.azure.com/oagaviation/ai-catalyst/_build/results?buildId=224315",
    }

    event = classify_webhook_event(payload, {"user-agent": "curl/8.5.0"})

    assert event.source == "azure-devops"
    assert event.source_category == "cicd"
    assert event.event_type == "pipeline_failure"
    assert event.severity == "error"
    assert event.source_ref == "azure-devops:pipeline:224315"
    assert "CI/CD pipeline #224315 failed" in event.summary
    assert "runway-cargoflights-runway" in event.content_markdown


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
