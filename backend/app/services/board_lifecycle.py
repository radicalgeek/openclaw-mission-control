"""Board lifecycle services.

This module contains DB-backed board workflows that may also interact with the
OpenClaw gateway. API routes should remain thin wrappers over these helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlmodel import col, select

from app.db import crud
from app.models.activity_events import ActivityEvent
from app.models.agent_board_access import AgentBoardAccess
from app.models.agent_audit_log import AgentAuditLog
from app.models.agent_webhooks import AgentWebhook, AgentWebhookPayload
from app.models.agents import Agent
from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.board_templates import BoardTemplate
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.board_webhooks import BoardWebhook
from app.models.channel import Channel
from app.models.channel_subscription import ChannelSubscription
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.plans import Plan
from app.models.sprint_webhooks import SprintWebhook
from app.models.sprints import Sprint, SprintReview, SprintTicket
from app.models.tag_assignments import TagAssignment
from app.models.task_custom_fields import BoardTaskCustomField, TaskCustomFieldValue
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.models.thread import Thread
from app.models.thread_message import ThreadMessage
from app.models.user_channel_state import UserChannelState
from app.schemas.common import OkResponse
from app.services.openclaw.gateway_resolver import (
    gateway_client_config,
    require_gateway_for_board,
)
from app.services.openclaw.gateway_rpc import OpenClawGatewayError
from app.services.openclaw.provisioning import OpenClawGatewayProvisioner

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.boards import Board


def _is_missing_gateway_agent_error(exc: OpenClawGatewayError) -> bool:
    message = str(exc).lower()
    if not message:
        return False
    if any(
        marker in message
        for marker in ("unknown agent", "no such agent", "agent does not exist")
    ):
        return True
    return "agent" in message and "not found" in message


async def delete_board(session: AsyncSession, *, board: Board) -> OkResponse:
    """Delete a board and all dependent records, cleaning gateway state when configured."""
    agents = await Agent.objects.filter_by(board_id=board.id).all(session)
    task_ids = list(
        await session.exec(select(Task.id).where(Task.board_id == board.id))
    )
    sprint_ids = list(
        await session.exec(select(Sprint.id).where(Sprint.board_id == board.id))
    )
    channel_ids = list(
        await session.exec(select(Channel.id).where(Channel.board_id == board.id))
    )
    thread_ids: list[object] = []
    if channel_ids:
        thread_ids.extend(
            list(
                await session.exec(
                    select(Thread.id).where(col(Thread.channel_id).in_(channel_ids))
                )
            )
        )
    thread_ids.extend(
        list(
            await session.exec(
                select(Thread.id).where(Thread.owner_board_id == board.id)
            )
        )
    )
    thread_ids = list(dict.fromkeys(thread_ids))

    if board.gateway_id:
        gateway = await require_gateway_for_board(
            session, board, require_workspace_root=True
        )
        # Ensure URL is present (required for gateway cleanup calls).
        gateway_client_config(gateway)
        for agent in agents:
            try:
                await OpenClawGatewayProvisioner().delete_agent_lifecycle(
                    agent=agent,
                    gateway=gateway,
                )
            except OpenClawGatewayError as exc:
                if _is_missing_gateway_agent_error(exc):
                    continue
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gateway cleanup failed: {exc}",
                ) from exc

    if task_ids:
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.task_id).in_(task_ids),
            commit=False,
        )
        await crud.delete_where(
            session,
            TagAssignment,
            col(TagAssignment.task_id).in_(task_ids),
            commit=False,
        )
        await crud.delete_where(
            session,
            TaskCustomFieldValue,
            col(TaskCustomFieldValue.task_id).in_(task_ids),
            commit=False,
        )
        await crud.update_where(
            session,
            Plan,
            col(Plan.task_id).in_(task_ids),
            updates={"task_id": None},
        )
        await crud.update_where(
            session,
            Task,
            col(Task.id).in_(task_ids),
            updates={"plan_id": None, "thread_id": None},
        )
    await crud.delete_where(
        session,
        ActivityEvent,
        col(ActivityEvent.board_id) == board.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        AgentAuditLog,
        col(AgentAuditLog.board_id) == board.id,
        commit=False,
    )
    await crud.delete_where(
        session,
        BoardTemplate,
        col(BoardTemplate.board_id) == board.id,
        commit=False,
    )
    # Keep teardown ordered around FK/reference chains so dependent rows are gone
    # before deleting their parent task/agent/board records.
    await crud.delete_where(
        session,
        TaskDependency,
        col(TaskDependency.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        TaskFingerprint,
        col(TaskFingerprint.board_id) == board.id,
    )

    # Approvals can reference tasks and agents, so delete before both.
    approval_ids = select(Approval.id).where(col(Approval.board_id) == board.id)
    await crud.delete_where(
        session,
        ApprovalTaskLink,
        col(ApprovalTaskLink.approval_id).in_(approval_ids),
        commit=False,
    )
    await crud.delete_where(session, Approval, col(Approval.board_id) == board.id)

    if sprint_ids:
        await crud.delete_where(
            session,
            SprintTicket,
            col(SprintTicket.sprint_id).in_(sprint_ids),
            commit=False,
        )
        await crud.delete_where(
            session,
            SprintReview,
            col(SprintReview.sprint_id).in_(sprint_ids),
            commit=False,
        )

    if channel_ids:
        await crud.delete_where(
            session,
            ChannelSubscription,
            col(ChannelSubscription.channel_id).in_(channel_ids),
            commit=False,
        )
        await crud.delete_where(
            session,
            UserChannelState,
            col(UserChannelState.channel_id).in_(channel_ids),
            commit=False,
        )
    if thread_ids:
        await crud.delete_where(
            session,
            ThreadMessage,
            col(ThreadMessage.thread_id).in_(thread_ids),
            commit=False,
        )

    await crud.delete_where(session, BoardMemory, col(BoardMemory.board_id) == board.id)
    await crud.delete_where(
        session,
        BoardWebhookPayload,
        col(BoardWebhookPayload.board_id) == board.id,
    )
    await crud.delete_where(
        session, BoardWebhook, col(BoardWebhook.board_id) == board.id
    )
    await crud.delete_where(
        session,
        BoardOnboardingSession,
        col(BoardOnboardingSession.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationBoardAccess,
        col(OrganizationBoardAccess.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        OrganizationInviteBoardAccess,
        col(OrganizationInviteBoardAccess.board_id) == board.id,
    )
    await crud.delete_where(
        session,
        BoardTaskCustomField,
        col(BoardTaskCustomField.board_id) == board.id,
    )

    # Sprint webhooks reference board_id (NOT NULL).
    await crud.delete_where(
        session, SprintWebhook, col(SprintWebhook.board_id) == board.id
    )

    # Tasks reference agents and have dependent records.
    # Delete tasks before agents.
    await crud.delete_where(session, Task, col(Task.board_id) == board.id)

    # Plans and sprints can both be linked from tasks, so remove them after tasks.
    await crud.delete_where(session, Plan, col(Plan.board_id) == board.id)
    await crud.delete_where(session, Sprint, col(Sprint.board_id) == board.id)

    if thread_ids:
        await crud.delete_where(
            session,
            Thread,
            col(Thread.id).in_(thread_ids),
            commit=False,
        )
    if channel_ids:
        await crud.delete_where(
            session,
            Channel,
            col(Channel.id).in_(channel_ids),
            commit=False,
        )

    # Agent board access grants reference both agents and boards — delete before both.
    await crud.delete_where(
        session, AgentBoardAccess, col(AgentBoardAccess.board_id) == board.id
    )

    if agents:
        agent_ids = [agent.id for agent in agents]
        await crud.delete_where(
            session,
            ActivityEvent,
            col(ActivityEvent.agent_id).in_(agent_ids),
            commit=False,
        )
        webhook_ids = list(
            await session.exec(
                select(AgentWebhook.id).where(col(AgentWebhook.agent_id).in_(agent_ids))
            )
        )
        if webhook_ids:
            await crud.delete_where(
                session,
                AgentWebhookPayload,
                col(AgentWebhookPayload.webhook_id).in_(webhook_ids),
                commit=False,
            )
        await crud.delete_where(
            session,
            AgentWebhook,
            col(AgentWebhook.agent_id).in_(agent_ids),
            commit=False,
        )
        await crud.delete_where(session, Agent, col(Agent.id).in_(agent_ids))

    await session.delete(board)
    await session.commit()
    return OkResponse()
