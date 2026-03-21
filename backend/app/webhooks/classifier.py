"""Webhook event classifier — maps incoming payloads to channel categories.

Each classifier implements `can_classify()` and `classify()`. The registry
tries each in order; first match wins. The generic classifier always matches
as a fallback.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timezone


@dataclasses.dataclass
class ClassifiedEvent:
    """A webhook event parsed and categorised for channel routing."""

    source: str  # e.g. "github-actions", "argocd"
    source_category: str  # "build" | "deployment" | "test" | "production"
    event_type: str  # e.g. "build_failure", "deployment_started"
    topic: str  # Thread topic string
    source_ref: str  # Unique dedup key
    summary: str  # One-line human summary
    content_markdown: str  # Full Markdown message
    metadata: dict  # Raw payload + parsed fields
    severity: str  # "info" | "warning" | "error" | "critical"
    url: str | None = None


class BaseClassifier:
    """Base class for webhook classifiers."""

    def can_classify(self, headers: dict, payload: dict) -> bool:  # noqa: ARG002
        return False

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        raise NotImplementedError


class GitHubActionsClassifier(BaseClassifier):
    """Classifies GitHub Actions workflow_run / check_suite webhooks."""

    def can_classify(self, headers: dict, payload: dict) -> bool:
        event = headers.get("x-github-event", "")
        return event in ("workflow_run", "check_suite", "check_run")

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        event_type_header = headers.get("x-github-event", "")
        repo = payload.get("repository", {})
        repo_name = repo.get("full_name") or repo.get("name") or "unknown"

        if event_type_header == "workflow_run":
            wf = payload.get("workflow_run", {})
            run_id = wf.get("id", "")
            run_number = wf.get("run_number", "")
            name = wf.get("name") or wf.get("workflow") or "Workflow"
            branch = wf.get("head_branch", "")
            conclusion = wf.get("conclusion", "")
            status_str = wf.get("status", "")
            html_url = wf.get("html_url")

            if conclusion == "success":
                severity = "info"
                event_type = "build_success"
                icon = "✅"
            elif conclusion in ("failure", "timed_out"):
                severity = "error"
                event_type = "build_failure"
                icon = "❌"
            elif conclusion == "cancelled":
                severity = "warning"
                event_type = "build_cancelled"
                icon = "⚠️"
            else:
                severity = "info"
                event_type = "build_running"
                icon = "🔄"

            topic = f"{repo_name}/{branch} — {name} #{run_number}"
            summary = f"{icon} {name} #{run_number} {conclusion or status_str} on {branch}"
            source_ref = f"github:workflow_run:{run_id}"
            content = (
                f"## {summary}\n\n"
                f"- **Repository**: {repo_name}\n"
                f"- **Branch**: {branch}\n"
                f"- **Run**: #{run_number}\n"
                f"- **Status**: {conclusion or status_str}\n"
            )
            if html_url:
                content += f"\n[View on GitHub →]({html_url})"

        elif event_type_header in ("check_suite", "check_run"):
            cs = payload.get("check_suite") or payload.get("check_run") or {}
            suite_id = cs.get("id", "")
            head_branch = cs.get("head_branch", "")
            conclusion = cs.get("conclusion") or ""
            html_url = cs.get("details_url") or cs.get("html_url")

            if conclusion == "success":
                severity = "info"
                event_type = "build_success"
                icon = "✅"
            elif conclusion == "failure":
                severity = "error"
                event_type = "build_failure"
                icon = "❌"
            else:
                severity = "info"
                event_type = "build_pending"
                icon = "🔄"

            topic = f"{repo_name}/{head_branch} — Check #{suite_id}"
            summary = f"{icon} Check {conclusion or 'pending'} on {head_branch}"
            source_ref = f"github:{event_type_header}:{suite_id}"
            content = f"## {summary}\n\n- **Repository**: {repo_name}\n- **Branch**: {head_branch}\n"
            if html_url:
                content += f"\n[View →]({html_url})"
        else:
            return GenericClassifier().classify(headers, payload)

        return ClassifiedEvent(
            source="github-actions",
            source_category="build",
            event_type=event_type,
            topic=topic,
            source_ref=source_ref,
            summary=summary,
            content_markdown=content,
            metadata={"raw": payload, "repo": repo_name},
            severity=severity,
            url=html_url if "html_url" in dir() else None,
        )


class GitHubPRClassifier(BaseClassifier):
    """Classifies GitHub pull_request webhooks."""

    def can_classify(self, headers: dict, payload: dict) -> bool:
        return headers.get("x-github-event") == "pull_request"

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        repo_name = repo.get("full_name") or repo.get("name") or "unknown"
        action = payload.get("action", "")
        number = pr.get("number", "")
        title = pr.get("title", "")
        html_url = pr.get("html_url")
        author = (pr.get("user") or {}).get("login", "unknown")

        severity = "info"
        if action == "opened":
            icon = "🔀"
        elif action == "closed":
            merged = pr.get("merged", False)
            icon = "✅" if merged else "❌"
        elif action == "synchronize":
            icon = "🔄"
        else:
            icon = "📋"

        topic = f"{repo_name} — PR #{number}: {title}"
        summary = f"{icon} PR #{number} {action}: {title}"
        source_ref = f"github:pr:{repo_name}:{number}"
        content = (
            f"## {summary}\n\n"
            f"- **Repository**: {repo_name}\n"
            f"- **PR**: #{number} {title}\n"
            f"- **Author**: {author}\n"
            f"- **Action**: {action}\n"
        )
        if html_url:
            content += f"\n[View PR →]({html_url})"

        return ClassifiedEvent(
            source="github",
            source_category="build",
            event_type=f"pr_{action}",
            topic=topic,
            source_ref=source_ref,
            summary=summary,
            content_markdown=content,
            metadata={"raw": payload, "pr_number": number, "repo": repo_name},
            severity=severity,
            url=html_url,
        )


class DeploymentClassifier(BaseClassifier):
    """Classifies deployment-related webhooks."""

    def can_classify(self, headers: dict, payload: dict) -> bool:
        gh_event = headers.get("x-github-event", "")
        if gh_event in ("deployment", "deployment_status"):
            return True
        webhook_source = headers.get("x-webhook-source", "").lower()
        if any(tool in webhook_source for tool in ("argocd", "flux", "helm", "spinnaker")):
            return True
        keys = set(payload.keys())
        return bool(keys & {"deployment", "deploy", "environment"}) and "workflow_run" not in keys

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        gh_event = headers.get("x-github-event", "")
        repo = payload.get("repository", {})
        repo_name = repo.get("full_name") or repo.get("name") if isinstance(repo, dict) else "unknown"

        if gh_event == "deployment_status":
            dep = payload.get("deployment", {})
            dep_status = payload.get("deployment_status", {})
            env = dep.get("environment", "unknown")
            state = dep_status.get("state", "")
            service = repo_name or "service"
            deploy_id = dep.get("id", "")
            html_url = dep_status.get("target_url") or dep_status.get("url")

            if state == "success":
                severity = "info"
                icon = "✅"
            elif state in ("failure", "error"):
                severity = "error"
                icon = "❌"
            else:
                severity = "info"
                icon = "🚀"

            topic = f"{service} — {env} deployment"
            summary = f"{icon} {service} deployed to {env}: {state}"
            source_ref = f"deploy:{service}:{env}:{deploy_id}"

        elif gh_event == "deployment":
            dep = payload.get("deployment", {})
            env = dep.get("environment", "unknown")
            service = repo_name or "service"
            deploy_id = dep.get("id", "")
            html_url = None
            severity = "info"
            icon = "🚀"
            topic = f"{service} — {env} deployment started"
            summary = f"{icon} {service} deployment to {env} started"
            source_ref = f"deploy:{service}:{env}:{deploy_id}"
        else:
            env = payload.get("environment", "unknown")
            service = payload.get("service") or payload.get("app") or "service"
            deploy_id = payload.get("id") or payload.get("deployment_id", "")
            html_url = payload.get("url")
            severity = "info"
            icon = "🚀"
            topic = f"{service} — {env} deployment"
            summary = f"{icon} {service} deployment to {env}"
            source_ref = f"deploy:{service}:{env}:{deploy_id}"

        content = (
            f"## {summary}\n\n"
            f"- **Service**: {service}\n"
            f"- **Environment**: {env}\n"
        )
        if html_url:
            content += f"\n[View Deployment →]({html_url})"

        return ClassifiedEvent(
            source="deployment",
            source_category="deployment",
            event_type="deployment_event",
            topic=topic,
            source_ref=source_ref,
            summary=summary,
            content_markdown=content,
            metadata={"raw": payload},
            severity=severity,
            url=html_url,
        )


class TestResultsClassifier(BaseClassifier):
    """Classifies test result webhooks."""

    def can_classify(self, headers: dict, payload: dict) -> bool:
        gh_event = headers.get("x-github-event", "")
        if gh_event == "check_run":
            cr = payload.get("check_run", {})
            name = (cr.get("name") or "").lower()
            if any(kw in name for kw in ("test", "spec", "jest", "pytest", "coverage")):
                return True
        keys = set(str(k).lower() for k in payload.keys())
        return bool(keys & {"test_results", "test_suite", "coverage", "suites"})

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        gh_event = headers.get("x-github-event", "")
        now = datetime.now(timezone.utc).isoformat()

        if gh_event == "check_run":
            cr = payload.get("check_run", {})
            suite_name = cr.get("name", "Test Suite")
            conclusion = cr.get("conclusion", "")
            run_id = cr.get("id", "")
            html_url = cr.get("details_url") or cr.get("html_url")
            repo = payload.get("repository", {})
            repo_name = repo.get("full_name") or repo.get("name") or "unknown"
        else:
            suite_name = (
                payload.get("suite_name")
                or payload.get("name")
                or "Test Suite"
            )
            conclusion = payload.get("result") or payload.get("status") or "completed"
            run_id = payload.get("id") or payload.get("run_id", "")
            html_url = payload.get("url")
            repo_name = payload.get("repo") or payload.get("repository", "unknown")

        if "fail" in str(conclusion).lower():
            severity = "error"
            icon = "❌"
        elif "pass" in str(conclusion).lower() or conclusion == "success":
            severity = "info"
            icon = "✅"
        else:
            severity = "warning"
            icon = "⚠️"

        topic = f"{suite_name} — {now[:10]}"
        summary = f"{icon} {suite_name}: {conclusion}"
        source_ref = f"test:{suite_name}:{run_id or now[:16]}"

        content = (
            f"## {summary}\n\n"
            f"- **Suite**: {suite_name}\n"
            f"- **Result**: {conclusion}\n"
        )
        if html_url:
            content += f"\n[View Results →]({html_url})"

        return ClassifiedEvent(
            source="test-runner",
            source_category="test",
            event_type="test_results",
            topic=topic,
            source_ref=source_ref,
            summary=summary,
            content_markdown=content,
            metadata={"raw": payload, "suite_name": suite_name},
            severity=severity,
            url=html_url,
        )


class GenericClassifier(BaseClassifier):
    """Fallback classifier — always matches, routes to production channel."""

    def can_classify(self, headers: dict, payload: dict) -> bool:
        return True

    def classify(self, headers: dict, payload: dict) -> ClassifiedEvent:
        now = datetime.now(timezone.utc).isoformat()
        source = headers.get("x-webhook-source") or headers.get("user-agent") or "External"
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]

        topic = f"{source} — Alert {now[:16]}"
        summary = f"Incoming event from {source}"
        source_ref = f"generic:{payload_hash}"

        try:
            content = f"## {summary}\n\n```json\n{json.dumps(payload, indent=2, default=str)[:1000]}\n```"
        except Exception:
            content = f"## {summary}\n\nRaw event received."

        return ClassifiedEvent(
            source=str(source),
            source_category="production",
            event_type="generic_event",
            topic=topic,
            source_ref=source_ref,
            summary=summary,
            content_markdown=content,
            metadata={"raw": payload},
            severity="info",
            url=None,
        )


def classify_webhook_event(payload: dict, headers: dict) -> ClassifiedEvent:
    """Classify a webhook event using the first matching classifier."""
    classifiers: list[BaseClassifier] = [
        GitHubActionsClassifier(),
        GitHubPRClassifier(),
        DeploymentClassifier(),
        TestResultsClassifier(),
        GenericClassifier(),
    ]
    for classifier in classifiers:
        if classifier.can_classify(headers, payload):
            return classifier.classify(headers, payload)
    # Should never reach here because GenericClassifier always matches
    return GenericClassifier().classify(headers, payload)
