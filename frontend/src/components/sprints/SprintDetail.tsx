"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, X, Zap, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type SprintRead,
  type TaskRead,
  type TagRef,
  listSprintTickets,
  listBacklog,
  startSprint,
  completeSprint,
  cancelSprint,
  deleteSprint,
  addSprintTickets,
  removeSprintTicket,
} from "@/api/sprints";
import { ApiError } from "@/api/mutator";
import { TaskCard } from "@/components/molecules/TaskCard";

type Props = {
  boardId: string;
  sprint: SprintRead;
  sprints: SprintRead[];
  orgTags: TagRef[];
  onRefresh: () => void;
};

// Brand-aware sprint status tones — semantic tokens via tailwind.config.cjs.
const statusColor: Record<string, string> = {
  draft: "bg-neutral-soft text-neutral border border-neutral-border",
  queued: "bg-warning-soft text-warning border border-warning-border",
  active: "bg-success-soft text-success border border-success-border",
  completed: "bg-info-soft text-info border border-info-border",
  cancelled: "bg-danger-soft text-danger border border-danger-border",
};

export function SprintDetail({ boardId, sprint, sprints: _sprints, orgTags: _orgTags, onRefresh }: Props) {
  const [tickets, setTickets] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Add-ticket picker state
  const [showPicker, setShowPicker] = useState(false);
  const [backlogItems, setBacklogItems] = useState<TaskRead[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addingBusy, setAddingBusy] = useState(false);

  // Remove ticket
  const [removingId, setRemovingId] = useState<string | null>(null);

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

  const loadBacklog = useCallback(async () => {
    setPickerLoading(true);
    try {
      const res = await listBacklog(boardId, { unassigned: true });
      // filter out tickets already in this sprint
      const sprintTaskIds = new Set(tickets.map((t) => t.id));
      setBacklogItems(res.data.filter((t) => !sprintTaskIds.has(t.id)));
    } catch {
      // ignore
    } finally {
      setPickerLoading(false);
    }
  }, [boardId, tickets]);

  const openPicker = useCallback(() => {
    setShowPicker(true);
    setSelected(new Set());
    void loadBacklog();
  }, [loadBacklog]);

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
        setActionError(
          err instanceof ApiError ? (err.message ?? "Action failed") : "Action failed",
        );
      } finally {
        setBusy(false);
      }
    },
    [boardId, sprint.id, onRefresh],
  );

  const handleAddTickets = useCallback(async () => {
    if (selected.size === 0) return;
    setAddingBusy(true);
    try {
      await addSprintTickets(boardId, sprint.id, Array.from(selected));
      setShowPicker(false);
      setSelected(new Set());
      await loadTickets();
      onRefresh();
    } catch {
      // ignore
    } finally {
      setAddingBusy(false);
    }
  }, [boardId, sprint.id, selected, loadTickets, onRefresh]);

  const handleRemoveTicket = useCallback(
    async (taskId: string) => {
      setRemovingId(taskId);
      try {
        await removeSprintTicket(boardId, sprint.id, taskId);
        await loadTickets();
        onRefresh();
      } catch {
        // ignore
      } finally {
        setRemovingId(null);
      }
    },
    [boardId, sprint.id, loadTickets, onRefresh],
  );

  const toggleSelected = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const donePct =
    sprint.ticket_count > 0
      ? Math.round((sprint.tickets_done_count / sprint.ticket_count) * 100)
      : 0;

  const canEdit =
    sprint.status === "draft" || sprint.status === "queued" || sprint.status === "active";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Sprint header ── */}
      <div className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-lg font-semibold text-slate-800">
                {sprint.name}
              </h2>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide shrink-0",
                  statusColor[sprint.status] ?? "bg-slate-100 text-slate-600",
                )}
              >
                {sprint.status}
              </span>
            </div>
            {sprint.goal && (
              <p className="mt-0.5 text-sm text-slate-500">{sprint.goal}</p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {(sprint.status === "draft" || sprint.status === "queued") && (
              <button
                disabled={busy}
                onClick={() => void handleAction("start")}
                className="flex items-center gap-1.5 rounded-lg bg-success px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50 transition shadow-sm"
              >
                <Zap className="h-3.5 w-3.5" />
                Start Sprint
              </button>
            )}
            {sprint.status === "active" && (
              <>
                <button
                  disabled={busy}
                  onClick={() => void handleAction("complete")}
                  className="flex items-center gap-1.5 rounded-lg bg-info px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50 transition shadow-sm"
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Complete
                </button>
                <button
                  disabled={busy}
                  onClick={() => void handleAction("cancel")}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 transition"
                >
                  Cancel
                </button>
              </>
            )}
            {(sprint.status === "draft" || sprint.status === "queued") && (
              <button
                disabled={busy}
                onClick={() => void handleAction("delete")}
                className="rounded-lg border border-danger-border px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger-soft disabled:opacity-50 transition"
              >
                Delete
              </button>
            )}
            {canEdit && (
              <button
                onClick={openPicker}
                className="flex items-center gap-1.5 rounded-lg border border-[color:var(--accent)]/30 px-3 py-1.5 text-xs font-medium text-[color:var(--accent)] hover:bg-[color:var(--accent-soft)] transition"
              >
                <Plus className="h-3.5 w-3.5" />
                Add tickets
              </button>
            )}
          </div>
        </div>

        {actionError && (
          <p className="mt-2 text-xs text-danger">{actionError}</p>
        )}

        {/* Progress bar */}
        {sprint.ticket_count > 0 && (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-[11px] text-slate-400">
              <span>
                {sprint.tickets_done_count} / {sprint.ticket_count} done
              </span>
              <span className="font-medium text-slate-500">{donePct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-[color:var(--accent)] transition-all"
                style={{ width: `${donePct}%` }}
              />
            </div>
          </div>
        )}

        {/* Time stats (committed / completed / actual) */}
        {(sprint.committed_minutes != null ||
          sprint.completed_minutes != null ||
          sprint.actual_minutes != null) && (
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
            {sprint.committed_minutes != null && (
              <span>
                <span className="font-semibold text-slate-700">
                  {sprint.committed_minutes}m
                </span>{" "}
                committed
              </span>
            )}
            {sprint.completed_minutes != null && (
              <span>
                <span className="font-semibold text-slate-700">
                  {sprint.completed_minutes}m
                </span>{" "}
                completed
              </span>
            )}
            {sprint.actual_minutes != null && (
              <span>
                <span className="font-semibold text-slate-700">
                  {sprint.actual_minutes}m
                </span>{" "}
                actual
              </span>
            )}
          </div>
        )}
      </div>

      {/* ── Add-ticket picker ── */}
      {showPicker && (
        <div className="border-b border-[color:var(--accent)]/30 bg-[color:var(--accent-soft)]/60 px-6 py-4">
          <div className="mb-3 flex items-center justify-between">
            <h4 className="text-sm font-semibold text-slate-700">
              Add from backlog
            </h4>
            <button
              onClick={() => setShowPicker(false)}
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 transition"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {pickerLoading && (
            <p className="py-4 text-center text-xs text-slate-400">
              Loading backlog…
            </p>
          )}
          {!pickerLoading && backlogItems.length === 0 && (
            <p className="py-4 text-center text-xs text-slate-500">
              No unassigned backlog tickets.
            </p>
          )}

          {backlogItems.length > 0 && (
            <div className="max-h-48 space-y-1 overflow-y-auto">
              {backlogItems.map((item) => (
                <label
                  key={item.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition",
                    selected.has(item.id)
                      ? "border-[color:var(--accent)]/30 bg-[color:var(--accent-soft)]"
                      : "border-slate-200 bg-white hover:border-slate-300",
                  )}
                >
                  <input
                    type="checkbox"
                    className="accent-[color:var(--accent)]"
                    checked={selected.has(item.id)}
                    onChange={() => toggleSelected(item.id)}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
                    {item.title}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                      item.priority === "high" || item.priority === "critical"
                        ? "bg-danger-soft text-danger border border-danger-border"
                        : item.priority === "medium"
                          ? "bg-warning-soft text-warning border border-warning-border"
                          : "bg-success-soft text-success border border-success-border",
                    )}
                  >
                    {item.priority}
                  </span>
                </label>
              ))}
            </div>
          )}

          {backlogItems.length > 0 && (
            <div className="mt-3 flex gap-2">
              <button
                disabled={selected.size === 0 || addingBusy}
                onClick={() => void handleAddTickets()}
                className="rounded-lg bg-[color:var(--accent)] px-4 py-1.5 text-xs font-medium text-[color:var(--accent-foreground)] hover:bg-[color:var(--accent-strong)] disabled:opacity-40 transition"
              >
                {addingBusy
                  ? "Adding…"
                  : `Add ${selected.size > 0 ? selected.size : ""} ticket${selected.size !== 1 ? "s" : ""}`}
              </button>
              <button
                onClick={() => setShowPicker(false)}
                className="rounded-lg border border-slate-200 px-4 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 transition"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Ticket list ── */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <p className="py-12 text-center text-sm text-slate-400">
            Loading tickets…
          </p>
        )}
        {!loading && tickets.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
            <div className="rounded-full bg-slate-100 p-4">
              <Plus className="h-6 w-6 text-slate-400" />
            </div>
            <p className="text-sm font-medium text-slate-600">
              No tickets in this sprint yet
            </p>
            {canEdit && (
              <button
                onClick={openPicker}
                className="mt-1 rounded-lg bg-[color:var(--accent)] px-4 py-2 text-sm font-medium text-[color:var(--accent-foreground)] hover:bg-[color:var(--accent-strong)] transition"
              >
                Add tickets from backlog
              </button>
            )}
          </div>
        )}

        <div className="space-y-2">
          {tickets.map((ticket) => {
            const dueDate = ticket.due_at
              ? new Date(ticket.due_at).toLocaleDateString("en-GB", {
                  day: "numeric",
                  month: "short",
                })
              : undefined;
            const isOverdue = ticket.due_at
              ? new Date(ticket.due_at) < new Date()
              : false;

            return (
              <div key={ticket.id} className="group relative">
                <TaskCard
                  title={ticket.title}
                  status={
                    ticket.status as "inbox" | "in_progress" | "review" | "done"
                  }
                  priority={ticket.priority}
                  due={dueDate}
                  isOverdue={isOverdue}
                  tags={ticket.tags.map((t) => ({
                    id: t.id,
                    name: t.name,
                    color: t.color,
                  }))}
                  assignee={ticket.assigned_agent_id ? "Agent" : undefined}
                />
                {/* Remove button (shown on hover, only for non-completed sprints) */}
                {canEdit && (
                  <button
                    disabled={removingId === ticket.id}
                    onClick={() => void handleRemoveTicket(ticket.id)}
                    title="Remove from sprint"
                    className="absolute right-2 top-2 hidden rounded-md p-1 text-slate-300 transition hover:bg-danger-soft hover:text-danger group-hover:flex disabled:opacity-40"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
