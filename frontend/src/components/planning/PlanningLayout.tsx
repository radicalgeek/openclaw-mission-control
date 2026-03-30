"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/api/mutator";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { cn } from "@/lib/utils";
import {
  type PlanRead,
  type PlanStatus,
  listPlans,
  createPlan,
} from "@/api/plans";
import { PlanList } from "./PlanList";
import { PlanDetail } from "./PlanDetail";
import { NewPlanModal } from "./NewPlanModal";

type Props = {
  boardId: string;
};

export function PlanningLayout({ boardId }: Props) {
  const router = useRouter();

  // ── Boards ─────────────────────────────────────────────────────────────────
  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, { query: { refetchOnMount: false } });
  const allBoards =
    boardsQuery.data?.status === 200
      ? (boardsQuery.data.data.items ?? [])
      : [];

  // ── Plans ──────────────────────────────────────────────────────────────────
  const [plans, setPlans] = useState<PlanRead[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<PlanRead | null>(null);
  const [filterStatus, _setFilterStatus] = useState<PlanStatus | undefined>(
    undefined,
  );
  const [showNewModal, setShowNewModal] = useState(false);

  const loadPlans = useCallback(async () => {
    setPlansLoading(true);
    try {
      const result = await listPlans(boardId, filterStatus);
      if (result.status === 200) {
        setPlans(result.data.items ?? []);
      }
    } finally {
      setPlansLoading(false);
    }
  }, [boardId, filterStatus]);

  useEffect(() => {
    void loadPlans();
    setSelectedPlan(null);
  }, [boardId, loadPlans]);

  const handleSelectPlan = (plan: PlanRead) => {
    setSelectedPlan(plan);
  };

  const handlePlanUpdated = (updated: PlanRead) => {
    setPlans((prev) =>
      prev.map((p) => (p.id === updated.id ? updated : p)),
    );
    setSelectedPlan(updated);
  };

  const handlePlanDeleted = () => {
    if (selectedPlan) {
      setPlans((prev) => prev.filter((p) => p.id !== selectedPlan.id));
      setSelectedPlan(null);
    }
  };

  const handleCreatePlan = async (title: string, initialPrompt: string) => {
    const result = await createPlan(boardId, {
      title,
      initial_prompt: initialPrompt || undefined,
    });
    if (result.status === 201 || result.status === 200) {
      const newPlan = result.data;
      setPlans((prev) => [newPlan, ...prev]);
      setSelectedPlan(newPlan);
    }
  };

  const currentBoard = allBoards.find((b) => b.id === boardId);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Board selector sidebar */}
      <nav className="flex w-48 shrink-0 flex-col border-r border-slate-200 bg-white overflow-y-auto">
        <div className="px-3 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Boards
          </p>
        </div>
        {allBoards.map((board) => (
          <button
            key={board.id}
            onClick={() => router.push(`/planning/${board.id}`)}
            className={cn(
              "w-full px-4 py-2.5 text-left text-sm transition",
              board.id === boardId
                ? "bg-blue-50 font-medium text-blue-800"
                : "text-slate-700 hover:bg-slate-50",
            )}
          >
            <span className="truncate block">{board.name}</span>
          </button>
        ))}
        {allBoards.length === 0 && (
          <p className="px-4 py-4 text-xs text-slate-400">No boards.</p>
        )}
      </nav>

      {/* Plan list */}
      <div className="flex w-64 shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white">
        <PlanList
          plans={plans}
          selectedPlanId={selectedPlan?.id ?? null}
          onSelectPlan={handleSelectPlan}
          onNewPlan={() => setShowNewModal(true)}
          loading={plansLoading}
        />
      </div>

      {/* Plan detail */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {selectedPlan ? (
          <PlanDetail
            key={selectedPlan.id}
            boardId={boardId}
            plan={selectedPlan}
            onPlanUpdated={handlePlanUpdated}
            onPlanDeleted={handlePlanDeleted}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-sm text-slate-400">
              {currentBoard
                ? `Select a plan from the list or create a new one for "${currentBoard.name}".`
                : "Select a plan."}
            </p>
            <button
              onClick={() => setShowNewModal(true)}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition"
            >
              New plan
            </button>
          </div>
        )}
      </div>

      {showNewModal && (
        <NewPlanModal
          onConfirm={handleCreatePlan}
          onClose={() => setShowNewModal(false)}
        />
      )}
    </div>
  );
}
