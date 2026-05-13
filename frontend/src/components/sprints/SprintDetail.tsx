"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardCheck,
  Check,
  Pencil,
  Plus,
  X,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type SprintRead,
  type SprintReviewGateRead,
  type TaskRead,
  type TagRef,
  listSprintTickets,
  listSprintReviews,
  listBacklog,
  startSprint,
  completeSprint,
  runSprintReview,
  cancelSprint,
  deleteSprint,
  addSprintTickets,
  removeSprintTicket,
  updateSprint,
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
  reviewing: "bg-warning-soft text-warning border border-warning-border",
  completed: "bg-info-soft text-info border border-info-border",
  cancelled: "bg-danger-soft text-danger border border-danger-border",
};

export function SprintDetail({
  boardId,
  sprint,
  sprints: _sprints,
  orgTags: _orgTags,
  onRefresh,
}: Props) {
  const [tickets, setTickets] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewGate, setReviewGate] = useState<SprintReviewGateRead | null>(
    null,
  );
  const [reviewLoading, setReviewLoading] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState(sprint.name);
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

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

  useEffect(() => {
    setDraftName(sprint.name);
    setEditingName(false);
    setRenameError(null);
  }, [sprint.id, sprint.name]);

  useEffect(() => {
    if (sprint.status !== "reviewing" && sprint.status !== "completed") {
      setReviewGate(null);
      return;
    }
    setReviewLoading(true);
    void listSprintReviews(boardId, sprint.id)
      .then((res) => setReviewGate(res.data))
      .catch(() => setReviewGate(null))
      .finally(() => setReviewLoading(false));
  }, [boardId, sprint.id, sprint.status]);

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
    async (action: "start" | "review" | "complete" | "cancel" | "delete") => {
      setBusy(true);
      setActionError(null);
      try {
        if (action === "start") await startSprint(boardId, sprint.id);
        else if (action === "review") await runSprintReview(boardId, sprint.id);
        else if (action === "complete")
          await completeSprint(boardId, sprint.id);
        else if (action === "cancel") await cancelSprint(boardId, sprint.id);
        else if (action === "delete") await deleteSprint(boardId, sprint.id);
        onRefresh();
      } catch (err) {
        setActionError(
          err instanceof ApiError
            ? (err.message ?? "Action failed")
            : "Action failed",
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

  const handleRename = useCallback(async () => {
    const nextName = draftName.trim();
    if (!nextName || nextName === sprint.name || renameBusy) {
      if (!nextName) setRenameError("Sprint name is required.");
      else setEditingName(false);
      return;
    }
    setRenameBusy(true);
    setRenameError(null);
    try {
      await updateSprint(boardId, sprint.id, { name: nextName });
      setEditingName(false);
      onRefresh();
    } catch (err) {
      setRenameError(
        err instanceof ApiError
          ? (err.message ?? "Rename failed")
          : "Rename failed",
      );
    } finally {
      setRenameBusy(false);
    }
  }, [boardId, draftName, onRefresh, renameBusy, sprint.id, sprint.name]);

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
    sprint.status === "draft" ||
    sprint.status === "queued" ||
    sprint.status === "active";
  const reviewSummaryVisible =
    sprint.status === "reviewing" ||
    sprint.status === "completed" ||
    reviewGate !== null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Sprint header ── */}
      <div className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {editingName ? (
                <form
                  className="flex min-w-0 flex-1 items-center gap-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void handleRename();
                  }}
                >
                  <input
                    autoFocus
                    value={draftName}
                    onChange={(event) => setDraftName(event.target.value)}
                    className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-lg font-semibold text-slate-800 outline-none focus:border-[color:var(--accent)] focus:ring-1 focus:ring-[color:var(--accent-soft)]"
                  />
                  <button
                    type="submit"
                    disabled={renameBusy}
                    title="Save sprint name"
                    className="rounded-md p-1.5 text-success transition hover:bg-success-soft disabled:opacity-50"
                  >
                    <Check className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="Cancel rename"
                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                    onClick={() => {
                      setDraftName(sprint.name);
                      setEditingName(false);
                      setRenameError(null);
                    }}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </form>
              ) : (
                <>
                  <h2 className="truncate text-lg font-semibold text-slate-800">
                    {sprint.name}
                  </h2>
                  {sprint.status !== "cancelled" && (
                    <button
                      type="button"
                      title="Rename sprint"
                      className="rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                      onClick={() => {
                        setDraftName(sprint.name);
                        setEditingName(true);
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                </>
              )}
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
            {renameError && (
              <p className="mt-1 text-xs text-danger">{renameError}</p>
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
                {sprint.ticket_count > 0 &&
                  sprint.tickets_done_count === sprint.ticket_count && (
                    <button
                      disabled={busy}
                      onClick={() => void handleAction("review")}
                      className="flex items-center gap-1.5 rounded-lg bg-warning px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50 transition shadow-sm"
                    >
                      <ClipboardCheck className="h-3.5 w-3.5" />
                      Run review
                    </button>
                  )}
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

        {reviewSummaryVisible && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {sprint.status === "completed" && reviewGate?.approved ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-success" />
                  <span className="font-semibold text-slate-700">
                    Sprint complete
                  </span>
                  <span className="rounded-full bg-success-soft px-2 py-0.5 font-semibold text-success">
                    Reviews passed
                  </span>
                </>
              ) : sprint.status === "reviewing" ? (
                <>
                  <ClipboardCheck className="h-4 w-4 text-warning" />
                  <span className="font-semibold text-slate-700">
                    Reviews in progress
                  </span>
                </>
              ) : (
                <>
                  <AlertCircle className="h-4 w-4 text-slate-400" />
                  <span className="font-semibold text-slate-700">
                    Review status unavailable
                  </span>
                </>
              )}
              {reviewLoading && (
                <span className="text-slate-400">Loading...</span>
              )}
            </div>
            {reviewGate && reviewGate.reviews.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {reviewGate.reviews.map((review) => (
                  <span
                    key={review.id}
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
                      review.status === "approved"
                        ? "border-success-border bg-success-soft text-success"
                        : review.status === "changes_requested"
                          ? "border-danger-border bg-danger-soft text-danger"
                          : "border-warning-border bg-warning-soft text-warning",
                    )}
                  >
                    {review.role}: {review.status.replace("_", " ")}
                  </span>
                ))}
              </div>
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
            const displayStatus =
              ticket.status === "archived" ? "done" : ticket.status;
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
                    displayStatus as "inbox" | "in_progress" | "review" | "done"
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
