"use client";

import { cn } from "@/lib/utils";
import type { SprintRead, SprintStatus } from "@/api/sprints";

type Props = {
  sprints: SprintRead[];
  selectedSprintId: string | null;
  onSelectSprint: (sprint: SprintRead) => void;
  onNewSprint: () => void;
  onSelectBacklog: () => void;
  showingBacklog: boolean;
  loading?: boolean;
};

const statusColor: Record<SprintStatus, string> = {
  draft: "bg-slate-200 text-slate-600",
  queued: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  completed: "bg-blue-100 text-blue-700",
  cancelled: "bg-red-100 text-red-700",
};

export function SprintList({
  sprints,
  selectedSprintId,
  onSelectSprint,
  onNewSprint,
  onSelectBacklog,
  showingBacklog,
  loading = false,
}: Props) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Sprints
        </span>
        <button
          onClick={onNewSprint}
          title="New sprint"
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-orange-500 hover:bg-orange-50 transition"
        >
          + New
        </button>
      </div>

      {/* Backlog row */}
      <button
        onClick={onSelectBacklog}
        className={cn(
          "w-full border-b border-slate-100 px-4 py-3 text-left text-sm font-medium transition",
          showingBacklog
            ? "bg-orange-50 text-orange-800"
            : "text-slate-700 hover:bg-slate-50",
        )}
      >
        📋 Backlog
      </button>

      {/* Sprint rows */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="px-4 py-6 text-center text-xs text-slate-400">Loading…</p>
        )}
        {!loading && sprints.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
            <p className="text-sm text-slate-500">No sprints yet.</p>
            <button
              onClick={onNewSprint}
              className="mt-1 rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 transition"
            >
              Create first sprint
            </button>
          </div>
        )}
        {sprints.map((sprint) => {
          const pct =
            sprint.ticket_count > 0
              ? Math.round(
                  (sprint.tickets_done_count / sprint.ticket_count) * 100,
                )
              : 0;
          const isSelected = sprint.id === selectedSprintId;
          return (
            <button
              key={sprint.id}
              onClick={() => onSelectSprint(sprint)}
              className={cn(
                "w-full border-b border-slate-100 px-4 py-3 text-left transition hover:bg-slate-50",
                isSelected && "bg-orange-50 hover:bg-orange-50",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span
                  className={cn(
                    "truncate text-sm font-medium leading-snug",
                    isSelected ? "text-orange-800" : "text-slate-700",
                  )}
                >
                  {sprint.name}
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                    statusColor[sprint.status],
                  )}
                >
                  {sprint.status}
                </span>
              </div>
              {sprint.ticket_count > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  <div className="flex justify-between text-[10px] text-slate-400">
                    <span>
                      {sprint.tickets_done_count}/{sprint.ticket_count}
                    </span>
                    <span>{pct}%</span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        sprint.status === "completed"
                          ? "bg-green-400"
                          : "bg-orange-400",
                      )}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )}
              {sprint.goal && (
                <p className="mt-1 truncate text-[10px] text-slate-400">
                  {sprint.goal}
                </p>
              )}
            </button>
          );
        })}

      </div>
    </div>
  );
}
