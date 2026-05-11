import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PlanRead } from "@/api/plans";
import { PlanDetail } from "./PlanDetail";

const getPlanMock = vi.fn();
const chatWithPlanMock = vi.fn();
const updatePlanMock = vi.fn();
const deletePlanMock = vi.fn();
const decomposePlanMock = vi.fn();

vi.mock("@/api/plans", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/plans")>("@/api/plans");
  return {
    ...actual,
    getPlan: (...args: unknown[]) => getPlanMock(...args),
    chatWithPlan: (...args: unknown[]) => chatWithPlanMock(...args),
    updatePlan: (...args: unknown[]) => updatePlanMock(...args),
    deletePlan: (...args: unknown[]) => deletePlanMock(...args),
    decomposePlan: (...args: unknown[]) => decomposePlanMock(...args),
  };
});

function buildPlan(overrides: Partial<PlanRead> = {}): PlanRead {
  return {
    id: "plan-1",
    board_id: "board-1",
    title: "Plan",
    slug: "plan",
    content: "",
    status: "draft",
    created_by_user_id: "user-1",
    task_id: null,
    task_status: null,
    session_key: "session-1",
    messages: [],
    created_at: "2026-05-11T00:00:00Z",
    updated_at: "2026-05-11T00:00:00Z",
    ...overrides,
  };
}

describe("PlanDetail pending agent state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getPlanMock.mockReset();
    chatWithPlanMock.mockReset();
    updatePlanMock.mockReset();
    deletePlanMock.mockReset();
    decomposePlanMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not resume stale drafting state just because a loaded plan ends with a user message", async () => {
    const plan = buildPlan({
      messages: [
        {
          role: "user",
          content: "Create a plan for authentication",
          created_at: "2026-05-11T00:00:00Z",
        },
      ],
    });

    render(
      <PlanDetail
        boardId="board-1"
        plan={plan}
        onPlanUpdated={() => undefined}
        onPlanDeleted={() => undefined}
      />,
    );

    expect(
      screen.queryByText("Agent is drafting your plan…"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "No content yet. Chat with the agent or switch to Edit mode to start writing.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message the agent…")).toBeEnabled();

    await act(async () => {
      vi.advanceTimersByTime(2500);
      await Promise.resolve();
    });

    expect(getPlanMock).not.toHaveBeenCalled();
  });

  it("polls only when the plan was explicitly submitted in the current session", async () => {
    const plan = buildPlan({
      messages: [
        {
          role: "user",
          content: "Create a plan for authentication",
          created_at: "2026-05-11T00:00:00Z",
        },
      ],
    });
    getPlanMock.mockResolvedValue({
      status: 200,
      data: buildPlan({
        content: "## Authentication plan",
        messages: [
          ...(plan.messages ?? []),
          {
            role: "assistant",
            content: "Drafted the plan",
            created_at: "2026-05-11T00:00:02Z",
          },
        ],
      }),
    });

    render(
      <PlanDetail
        boardId="board-1"
        plan={plan}
        onPlanUpdated={() => undefined}
        onPlanDeleted={() => undefined}
        startAgentPolling
      />,
    );

    expect(
      screen.getByText("Agent is drafting your plan…"),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });

    expect(getPlanMock).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText("Agent is drafting your plan…"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Authentication plan")).toBeInTheDocument();
  });
});
