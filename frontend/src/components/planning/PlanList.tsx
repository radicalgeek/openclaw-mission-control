"use client";

import { FileText, Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import type { PlanRead } from "@/api/plans";
import { PlanStatusBadge } from "./PlanStatusBadge";

type Props = {
  plans: PlanRead[];
  selectedPlanId: string | null;
  onSelectPlan: (plan: PlanRead) => void;
  onNewPlan: () => void;
  loading?: boolean;
  showArchived?: boolean;
  onToggleArchived?: () => void;
};

export function PlanList({
  plans,
  selectedPlanId,
  onSelectPlan,
  onNewPlan,
  loading = false,
  showArchived = false,
  onToggleArchived,
}: Props) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Plans
        </span>
        <div className="flex items-center gap-1">
          {onToggleArchived && (
            <button
              onClick={onToggleArchived}
              title={showArchived ? "Hide archived" : "Show archived"}
              className={cn(
                "rounded-md px-2 py-1 text-xs font-medium transition",
                showArchived
                  ? "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  : "text-slate-400 hover:bg-slate-100",
              )}
            >
              Archived
            </button>
          )}
          <button
            onClick={onNewPlan}
            title="New plan"
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[color:var(--accent)] hover:bg-[color:var(--accent-soft)] transition"
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </button>
        </div>
      </div>

      {/* Plan rows */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="px-4 py-6 text-center text-xs text-slate-400">Loading…</p>
        )}
        {!loading && plans.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
            <FileText className="h-8 w-8 text-slate-300" />
            <p className="text-sm text-slate-500">No plans yet.</p>
            <button
              onClick={onNewPlan}
              className="mt-1 rounded-md bg-[color:var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:bg-[color:var(--accent-strong)] transition"
            >
              Create your first plan
            </button>
          </div>
        )}
        {plans.map((plan) => (
          <button
            key={plan.id}
            onClick={() => onSelectPlan(plan)}
            className={cn(
              "w-full border-b border-[color:var(--border)] px-4 py-3 text-left transition hover:bg-[color:var(--surface-muted)]",
              plan.id === selectedPlanId && "bg-[color:var(--accent-soft)] hover:bg-[color:var(--accent-soft)]",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <span
                className={cn(
                  "truncate text-sm font-medium",
                  plan.id === selectedPlanId ? "text-[color:var(--accent-strong)]" : "text-[color:var(--text)]",
                )}
              >
                {plan.title}
              </span>
              <PlanStatusBadge status={plan.status} className="shrink-0" />
            </div>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {new Date(plan.updated_at).toLocaleDateString()}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
