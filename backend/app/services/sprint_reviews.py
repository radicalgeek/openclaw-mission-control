"""Sprint review gate orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.sprints import SprintReview, SprintTicket
from app.models.tasks import Task
from app.schemas.sprint_reviews import SprintReviewGateRead, SprintReviewRead
from app.services.activity_log import record_activity

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board
    from app.models.sprints import Sprint

logger = get_logger(__name__)

REVIEW_ROLE_TEMPLATES: dict[str, str] = {
    "qa": "quality_reviewer",
    "security": "security_reviewer",
    "architecture": "architecture_reviewer",
}


@dataclass(frozen=True, slots=True)
class SprintReviewDispatchResult:
    """Reviewer dispatch summary."""

    sprint_id: UUID
    dispatched_reviewers: list[str]
    skipped_reviewers: list[dict[str, str]]


def _configured_agent_id_for_role(role: str) -> str:
    return {
        "qa": settings.org_qa_reviewer_agent_id,
        "security": settings.org_security_reviewer_agent_id,
        "architecture": settings.org_architecture_reviewer_agent_id,
    }.get(role, "")


def _role_intro(role: str) -> str:
    return {
        "qa": "QA REVIEW REQUEST: assess test coverage, acceptance criteria, regression risk.",
        "security": (
            "SECURITY REVIEW REQUEST: assess OWASP Top 10, secrets exposure, "
            "dependency vulnerabilities, IAM misconfigurations."
        ),
        "architecture": (
            "ARCHITECTURE REVIEW REQUEST: assess scalability, resilience, "
            "observability, cost, and fit with established patterns."
        ),
    }.get(role, f"{role.upper()} REVIEW REQUEST")


def _task_line(task: Task) -> str:
    description = (task.description or "").replace("\n", " ")[:220]
    return (
        f"- task_id={task.id} | status={task.status} | priority={task.priority} | "
        f"title={task.title} | description={description}"
    )


def _build_review_prompt(
    *,
    board: "Board",
    sprint: "Sprint",
    role: str,
    sprint_tasks: list[Task],
    backlog_tasks: list[Task],
    future_sprint_tasks: list[tuple["Sprint", Task]],
) -> str:
    lines = [
        _role_intro(role),
        f"Board: {board.name}",
        f"Board objective: {board.objective or '(not set)'}",
        f"Sprint: {sprint.name}",
        f"Sprint goal: {sprint.goal or '(none)'}",
        f"Sprint ID: {sprint.id}",
        "",
        "Reviewer instructions:",
        "- Review the sprint work against your specialist scope.",
        "- Consider backlog and future sprint tickets before creating new work.",
        "- If a gap is already planned, mention the existing ticket instead of duplicating it.",
        "- Treat newer task comments, done remediation tickets, and merged-fix evidence as "
        "superseding older blocker reports; do not block on a stale issue that later sprint "
        "evidence says was fixed.",
        "- If the only concern is that a completed remediation needs re-checking, perform that "
        "check from the available board/code evidence; do not request changes just to ask another "
        "agent to verify it.",
        "- Do not request changes for work that is already represented by a backlog or future "
        "sprint ticket; record it as planned follow-up and approve unless it is a new "
        "regression introduced by this sprint.",
        "- A gap is not unplanned just because this sprint touched adjacent deployment, runtime, "
        "or production-readiness code. If an existing backlog or future sprint ticket already "
        "covers the same or broader gap, cite that ticket as planned follow-up and do not block "
        "unless the exact completed sprint acceptance criteria promised and failed that fix.",
        "- Do not create a current-sprint remediation ticket for a gap that is already covered "
        "by a backlog or future sprint ticket.",
        "- Only block the sprint for a current-sprint acceptance failure, a new unplanned "
        "critical/high issue, or delivered work that is demonstrably broken.",
        "- For blocking gaps, create one remediation ticket per distinct blocking finding.",
        "- Do not bundle unrelated remediation work into a single catch-all ticket.",
        "- Put only tightly related acceptance criteria in the same remediation ticket.",
        "- Create remediation tickets in the board inbox with:",
        f"  POST /api/v1/agent/boards/{board.id}/tasks",
        "- Include the created remediation task ids in created_ticket_ids when submitting verdict.",
        "- For non-blocking follow-up, create backlog tickets with:",
        f"  POST /api/v1/agent/boards/{board.id}/backlog",
        "- Submit your verdict with:",
        f"  POST /api/v1/agent/boards/{board.id}/sprints/{sprint.id}/review-update",
        '  body {"verdict":"approve|changes_requested","summary":"...","findings":[]}',
        "- The review-update endpoint only accepts POST. Do not call it with GET; if a "
        "previous attempt received 405 Method Not Allowed, retry immediately with POST.",
        "- Only use verdict=approve when your role has no blocking concerns.",
        "",
        "Sprint tickets under review:",
    ]
    lines.extend(_task_line(task) for task in sprint_tasks)
    lines.append("")
    lines.append("Backlog tickets already planned:")
    if backlog_tasks:
        lines.extend(_task_line(task) for task in backlog_tasks[:30])
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("Future sprint tickets already planned:")
    if future_sprint_tasks:
        for future_sprint, task in future_sprint_tasks[:40]:
            lines.append(f"- sprint={future_sprint.name} | {_task_line(task)[2:]}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


async def _sprint_tasks(
    session: "AsyncSession",
    *,
    sprint_id: UUID,
) -> list[Task]:
    stmt = (
        select(Task)
        .join(SprintTicket, col(SprintTicket.task_id) == col(Task.id))
        .where(col(SprintTicket.sprint_id) == sprint_id)
        .order_by(col(SprintTicket.position).asc())
    )
    return list((await session.exec(stmt)).all())


async def _backlog_tasks(
    session: "AsyncSession",
    *,
    board_id: UUID,
) -> list[Task]:
    from sqlalchemy import or_  # noqa: PLC0415

    stmt = (
        select(Task)
        .where(col(Task.board_id) == board_id)
        .where(
            or_(
                col(Task.status).in_(["triage", "backlog", "inbox"]),
                col(Task.is_backlog).is_(True),
            )
        )
        .order_by(col(Task.priority_score).desc(), col(Task.created_at).asc())
        .limit(30)
    )
    return list((await session.exec(stmt)).all())


async def _future_sprint_tasks(
    session: "AsyncSession",
    *,
    board_id: UUID,
    current_sprint_id: UUID,
) -> list[tuple["Sprint", Task]]:
    from app.models.sprints import Sprint  # noqa: PLC0415

    rows = (
        await session.exec(
            select(Sprint, Task)
            .join(SprintTicket, col(SprintTicket.sprint_id) == col(Sprint.id))
            .join(Task, col(SprintTicket.task_id) == col(Task.id))
            .where(col(Sprint.board_id) == board_id)
            .where(col(Sprint.id) != current_sprint_id)
            .where(col(Sprint.status).in_(["draft", "queued"]))
            .order_by(col(Sprint.position).asc(), col(SprintTicket.position).asc())
            .limit(40)
        )
    ).all()
    return [(sprint, task) for sprint, task in rows]


async def _review_for_role(
    session: "AsyncSession",
    *,
    sprint: "Sprint",
    board: "Board",
    role: str,
) -> SprintReview:
    review = (
        await session.exec(
            select(SprintReview)
            .where(col(SprintReview.sprint_id) == sprint.id)
            .where(col(SprintReview.role) == role)
        )
    ).first()
    if review is not None:
        return review
    review = SprintReview(
        organization_id=board.organization_id,
        board_id=board.id,
        sprint_id=sprint.id,
        role=role,
        status="pending",
    )
    session.add(review)
    await session.flush()
    return review


def sprint_review_to_read(review: SprintReview) -> SprintReviewRead:
    """Convert a review row into a response payload."""
    return SprintReviewRead(
        id=review.id,
        board_id=review.board_id,
        sprint_id=review.sprint_id,
        role=review.role,
        status=review.status,
        agent_id=review.agent_id,
        summary=review.summary,
        findings=review.findings,
        created_ticket_ids=review.created_ticket_ids,
        dispatched_at=review.dispatched_at,
        resolved_at=review.resolved_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


async def sprint_review_gate(
    session: "AsyncSession",
    *,
    sprint: "Sprint",
) -> SprintReviewGateRead:
    """Return aggregate review status for a sprint."""
    reviews = list(
        (
            await session.exec(
                select(SprintReview)
                .where(col(SprintReview.sprint_id) == sprint.id)
                .order_by(col(SprintReview.role).asc())
            )
        ).all()
    )
    approved = len(reviews) == len(REVIEW_ROLE_TEMPLATES) and all(
        review.status == "approved" for review in reviews
    )
    return SprintReviewGateRead(
        sprint_id=sprint.id,
        status=sprint.status,
        approved=approved,
        reviews=[sprint_review_to_read(review) for review in reviews],
    )


async def begin_sprint_review(
    session: "AsyncSession",
    *,
    sprint: "Sprint",
    board: "Board",
) -> SprintReviewDispatchResult:
    """Move a completed active sprint into review and dispatch reviewer agents."""
    from app.services.openclaw.planning_service import (  # noqa: PLC0415
        PlanningMessagingService,
    )

    if sprint.status not in {"active", "reviewing"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot run review on sprint with status '{sprint.status}'",
        )

    sprint_tasks = await _sprint_tasks(session, sprint_id=sprint.id)
    if not sprint_tasks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sprint has no tickets to review.",
        )
    if any(task.status != "done" for task in sprint_tasks):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sprint review can only run after all sprint tickets are done.",
        )

    sprint.status = "reviewing"
    sprint.updated_at = utcnow()
    session.add(sprint)

    backlog_tasks = await _backlog_tasks(session, board_id=board.id)
    future_sprint_tasks = await _future_sprint_tasks(
        session,
        board_id=board.id,
        current_sprint_id=sprint.id,
    )

    dispatcher = PlanningMessagingService(session)
    dispatched: list[str] = []
    skipped: list[dict[str, str]] = []
    now = utcnow()
    for role, role_template in REVIEW_ROLE_TEMPLATES.items():
        review = await _review_for_role(session, sprint=sprint, board=board, role=role)
        if review.status == "approved":
            dispatched.append(role)
            continue
        review.status = "pending"
        review.agent_id = None
        review.summary = None
        review.findings = None
        review.created_ticket_ids = None
        review.resolved_at = None
        review.dispatched_at = now
        review.updated_at = now
        session.add(review)
        prompt = _build_review_prompt(
            board=board,
            sprint=sprint,
            role=role,
            sprint_tasks=sprint_tasks,
            backlog_tasks=backlog_tasks,
            future_sprint_tasks=future_sprint_tasks,
        )
        session_key = await dispatcher.dispatch_to_configured_org_agent(
            board=board,
            configured_agent_id=_configured_agent_id_for_role(role),
            role_template=role_template,
            prompt=prompt,
            log_prefix=f"sprint.review.{role}",
            correlation_id=f"sprint.review.{role}:{sprint.id}",
        )
        if session_key is None:
            review.status = "skipped"
            review.summary = "Reviewer unavailable at dispatch time."
            review.resolved_at = now
            review.updated_at = now
            session.add(review)
            skipped.append({"role": role, "reason": "agent_offline_or_missing"})
        else:
            dispatched.append(role)

    record_activity(
        session,
        event_type="sprint_review_dispatched",
        message=f"Sprint review dispatched: {len(dispatched)} reviewers ({', '.join(dispatched)})",
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(sprint)
    return SprintReviewDispatchResult(
        sprint_id=sprint.id,
        dispatched_reviewers=dispatched,
        skipped_reviewers=skipped,
    )


async def record_sprint_review_verdict(
    session: "AsyncSession",
    *,
    sprint: "Sprint",
    board: "Board",
    role: str,
    agent_id: UUID,
    verdict: str,
    summary: str,
    findings: list[dict[str, object]] | None,
    created_ticket_ids: list[str] | None,
) -> SprintReviewGateRead:
    """Persist one review verdict and complete the sprint if all reviewers approve."""
    if role not in REVIEW_ROLE_TEMPLATES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent is not a sprint reviewer.",
        )
    if sprint.status != "reviewing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sprint is not awaiting review (current: {sprint.status}).",
        )

    review = await _review_for_role(session, sprint=sprint, board=board, role=role)
    now = utcnow()
    review.status = "approved" if verdict == "approve" else "changes_requested"
    review.agent_id = agent_id
    review.summary = summary
    review.findings = findings
    review.created_ticket_ids = created_ticket_ids
    review.resolved_at = now
    review.updated_at = now
    session.add(review)

    record_activity(
        session,
        event_type="sprint_review_verdict",
        message=f"Sprint review {role}: {review.status}",
        agent_id=agent_id,
        board_id=board.id,
    )
    await session.commit()
    await session.refresh(sprint)

    gate = await sprint_review_gate(session, sprint=sprint)
    if gate.approved:
        from app.services.sprint_lifecycle import SprintService  # noqa: PLC0415

        await SprintService.complete_sprint(
            session,
            sprint=sprint,
            board=board,
            allow_reviewing=True,
        )
        await session.refresh(sprint)
        gate = await sprint_review_gate(session, sprint=sprint)
    return gate
