"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  type SprintRead,
  type TaskRead,
  listSprintTickets,
  startSprint,
  completeSprint,
  cancelSprint,
  deleteSprint,
} from "@/api/sprints";
import { ApiError } from "@/api/mutator";

type Props = {
  boardId: string;
  sprint: SprintRead;
  onRefresh: () => void;
};

const priorityDot: Record<string, string> = {
  low: "bg-slate-300",
  medium: "bg-yellow-400",
  high: "bg-orange-500",
  critical: "bg-red-600",
};

export function SprintDetail({ boardId, sprint, onRefresh }: Props) {
  const [tickets, setTickets] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadTickets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSprintTickets(boardId, sprint.id);
      setTickets(res.data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [boardId, sprint.id]);

  useEffect(() => {
    void loadTickets();
  }, [loadTickets]);

  const handleAction = useCallback(
    async (action: "start" | "complete" | "cancel" | "delete") => {
      setBusy(true);
      setActionError(null);
      try {
        if (action === "start") await startSprint(boardId, sprint.id);
        else if (action === "complete") await completeSprint(boardId, sprint.id);
        else if (action === "cancel") await cancelSprint(boardId, sprint.id);
        else if (action === "delete") await deleteSprint(boardId, sprint.id);
        onRefresh();
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? (err.message ?? "Action failed")
            : "Action failed";
        setActionError(msg);
      } finally {
        setBusy(false);
      }
    },
    [boardId, sprint.id, onRefresh],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Sprint header */}
      <div className="border-b border-slate-200 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-slate-800">
              {sprint.name}
            </h2>
            {sprint.goal && (
              <p className="mt-0.5 text-sm text-slate-500">{sprint.goal}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {sprint.status === "draft" || sprint.status === "queued" ? (
              <button
                disabled={busy}
                onClick={() => void handleAction("start")}
                className="rounded-md bg-green-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-600 disabled:opacity-50 transition"
              >
                Start
              </button>
            ) : null}
            {sprint.status === "active" ? (
              <>
                <button
                  disabled={busy}
                  onClick={() => void handleAction("complete")}
                  className="rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-50 transition"
                >
                  Complete
                </button>
                <button
                  disabled={busy}
                  onClick={() => void handleAction("cancel")}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 transition"
                >
                  Cancel
                </button>
              </>
            ) : null}
            {sprint.status === "draft" || sprint.status === "queued" ? (
              <button
                disabled={busy}
                onClick={() => void handleAction("delete")}
                className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-50 disabled:opacity-50 transition"
              >
                Delete
              </button>
            ) : null}
          </div>
        </div>
        {actionError && (
          <p className="mt-2 text-xs text-red-500">{actionError}</p>
        )}
        {/* Progress bar */}
        {sprint.ticket_count > 0 && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-[11px] text-slate-400">
              <span>{sprint.tickets_done_count} done</span>
              <span>{sprint.ticket_count} total</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-green-400 transition-all"
                style={{
                  width: `${Math.round(
                    (sprint.tickets_done_count / sprint.ticket_count) * 100,
                  )}%`,
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Ticket list */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <p className="py-8 text-center text-sm text-slate-400">Loading tickets…</p>
        )}
        {!loading && tickets.length === 0 && (
          <p className="py-8 text-center text-sm text-slate-400">
            No tickets in this sprint yet.
          </p>
        )}
        <div className="space-y-2">
          {tickets.map((ticket) => (
            <div
              key={ticket.id}
              className="flex items-start gap-3 rounded-xl border border-slate-100 bg-white p-3 shadow-sm"
            >
              <span
                className={cn(
                  "mt-1 h-2 w-2 shrink-0 rounded-full",
                  priorityDot[ticket.priority] ?? "bg-slate-300",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">
                  {ticket.title}
                </p>
                {ticket.description && (
                  <p className="mt-0.5 line-clamp-2 text-xs text-slate-400">
                    {ticket.description}
                  </p>
                )}
              </div>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium",
                  ticket.status === "done"
                    ? "bg-green-100 text-green-700"
                    : ticket.status === "in_progress"
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-slate-100 text-slate-500",
                )}
              >
                {ticket.status.replace("_", " ")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
