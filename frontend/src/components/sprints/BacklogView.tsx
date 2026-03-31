"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Tag, X, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type TaskRead,
  type BacklogTaskCreate,
  type SprintRead,
  type TagRef,
  listBacklog,
  createBacklogTask,
  addSprintTickets,
  removeSprintTicket,
} from "@/api/sprints";
import { ApiError } from "@/api/mutator";
import { TaskCard } from "@/components/molecules/TaskCard";

type Props = {
  boardId: string;
  sprints: SprintRead[];
  orgTags: TagRef[];
  onSprintChange?: () => void;
};

const PRIORITY_OPTIONS = ["low", "medium", "high", "critical"] as const;

export function BacklogView({ boardId, sprints, orgTags, onSprintChange }: Props) {
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<BacklogTaskCreate>({
    title: "",
    description: "",
    priority: "medium",
    tag_ids: [],
    due_at: null,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignPopover, setAssignPopover] = useState<string | null>(null);
  const [assignBusy, setAssignBusy] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listBacklog(boardId, { unassigned: false });
      setTasks(res.data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [boardId]);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  const handleCreate = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!form.title.trim()) return;
      setSaving(true);
      setError(null);
      try {
        await createBacklogTask(boardId, form);
        setForm({ title: "", description: "", priority: "medium", tag_ids: [], due_at: null });
        setShowForm(false);
        await loadTasks();
      } catch (err) {
        setError(err instanceof ApiError ? (err.message ?? "Failed") : "Failed");
      } finally {
        setSaving(false);
      }
    },
    [boardId, form, loadTasks],
  );

  const handleAssignToSprint = useCallback(
    async (task: TaskRead, sprintId: string) => {
      setAssignBusy(task.id);
      setAssignPopover(null);
      try {
        await addSprintTickets(boardId, sprintId, [task.id]);
        await loadTasks();
        onSprintChange?.();
      } catch {
        // silent
      } finally {
        setAssignBusy(null);
      }
    },
    [boardId, loadTasks, onSprintChange],
  );

  const handleRemoveFromSprint = useCallback(
    async (task: TaskRead) => {
      if (!task.sprint_id) return;
      setAssignBusy(task.id);
      try {
        await removeSprintTicket(boardId, task.sprint_id, task.id);
        await loadTasks();
        onSprintChange?.();
      } catch {
        // silent
      } finally {
        setAssignBusy(null);
      }
    },
    [boardId, loadTasks, onSprintChange],
  );

  const toggleTag = (tagId: string) => {
    setForm((f) => {
      const current = f.tag_ids ?? [];
      return {
        ...f,
        tag_ids: current.includes(tagId)
          ? current.filter((id) => id !== tagId)
          : [...current, tagId],
      };
    });
  };

  const openSprints = sprints.filter(
    (s) => s.status === "draft" || s.status === "queued",
  );
  const sprintMap = Object.fromEntries(sprints.map((s) => [s.id, s]));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div>
          <h2 className="text-base font-semibold text-slate-800">Backlog</h2>
          {tasks.length > 0 && (
            <p className="text-xs text-slate-400">
              {tasks.length} ticket{tasks.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-lg bg-orange-500 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-orange-600 transition"
        >
          <Plus className="h-3.5 w-3.5" />
          {showForm ? "Cancel" : "Add ticket"}
        </button>
      </div>

      {/* ── Create form ── */}
      {showForm && (
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="border-b border-slate-200 bg-orange-50/60 px-6 py-4 space-y-3"
        >
          <input
            required
            autoFocus
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Ticket title"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
          />
          <textarea
            value={form.description ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, description: e.target.value }))
            }
            placeholder="Description (optional)"
            rows={2}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
          />
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Priority
              </label>
              <select
                value={form.priority ?? "medium"}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    priority: e.target.value as BacklogTaskCreate["priority"],
                  }))
                }
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-orange-400"
              >
                {PRIORITY_OPTIONS.map((p) => (
                  <option key={p} value={p}>
                    {p.charAt(0).toUpperCase() + p.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Due
              </label>
              <input
                type="date"
                value={form.due_at ? form.due_at.substring(0, 10) : ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    due_at: e.target.value ? `${e.target.value}T00:00:00Z` : null,
                  }))
                }
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-orange-400"
              />
            </div>
          </div>

          {orgTags.length > 0 && (
            <div className="space-y-1.5">
              <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                <Tag className="h-3 w-3" />
                Tags
              </p>
              <div className="flex flex-wrap gap-1.5">
                {orgTags.map((tag) => {
                  const selected = (form.tag_ids ?? []).includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => toggleTag(tag.id)}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition",
                        selected
                          ? "border-orange-300 bg-orange-100 text-orange-800"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
                      )}
                    >
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: `#${tag.color}` }}
                      />
                      {tag.name}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {error && <p className="text-xs text-red-500">{error}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-orange-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50 transition"
            >
              {saving ? "Saving…" : "Add to backlog"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setForm({
                  title: "",
                  description: "",
                  priority: "medium",
                  tag_ids: [],
                  due_at: null,
                });
              }}
              className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* ── Ticket list ── */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <p className="py-12 text-center text-sm text-slate-400">
            Loading backlog…
          </p>
        )}
        {!loading && tasks.length === 0 && !showForm && (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
            <div className="rounded-full bg-slate-100 p-4">
              <Plus className="h-6 w-6 text-slate-400" />
            </div>
            <p className="text-sm font-medium text-slate-600">Backlog is empty</p>
            <p className="text-xs text-slate-400">
              Add tickets to plan your upcoming work.
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-1 rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 transition"
            >
              Add first ticket
            </button>
          </div>
        )}

        <div className="space-y-2">
          {tasks.map((task) => {
            const assignedSprint = task.sprint_id ? sprintMap[task.sprint_id] : null;
            const dueDate = task.due_at
              ? new Date(task.due_at).toLocaleDateString("en-GB", {
                  day: "numeric",
                  month: "short",
                })
              : undefined;
            const isOverdue = task.due_at
              ? new Date(task.due_at) < new Date()
              : false;

            return (
              <div key={task.id} className="group">
                <TaskCard
                  title={task.title}
                  status={
                    task.status as "inbox" | "in_progress" | "review" | "done"
                  }
                  priority={task.priority}
                  due={dueDate}
                  isOverdue={isOverdue}
                  tags={task.tags.map((t) => ({
                    id: t.id,
                    name: t.name,
                    color: t.color,
                  }))}
                  assignee={task.assigned_agent_id ? "Agent" : undefined}
                />
                {/* Sprint assignment footer */}
                <div className="mt-1 flex items-center gap-2 px-1 pb-1">
                  {assignedSprint ? (
                    <>
                      <span className="flex items-center gap-1 rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-medium text-orange-700">
                        <span className="h-1 w-1 rounded-full bg-orange-400" />
                        {assignedSprint.name}
                      </span>
                      <button
                        disabled={assignBusy === task.id}
                        onClick={() => void handleRemoveFromSprint(task)}
                        className="flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-red-50 hover:text-red-500 transition disabled:opacity-40"
                        title="Remove from sprint"
                      >
                        <X className="h-3 w-3" />
                        Remove
                      </button>
                    </>
                  ) : (
                    <div className="relative">
                      <button
                        disabled={
                          assignBusy === task.id || openSprints.length === 0
                        }
                        onClick={() =>
                          setAssignPopover((prev) =>
                            prev === task.id ? null : task.id,
                          )
                        }
                        className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-orange-50 hover:text-orange-600 transition disabled:pointer-events-none disabled:opacity-30"
                      >
                        {assignBusy === task.id
                          ? "Assigning…"
                          : openSprints.length === 0
                            ? "No open sprints"
                            : (
                                <>
                                  + Add to sprint
                                  <ChevronDown className="h-3 w-3" />
                                </>
                              )}
                      </button>
                      {assignPopover === task.id && (
                        <div className="absolute left-0 top-6 z-10 w-48 rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
                          {openSprints.map((s) => (
                            <button
                              key={s.id}
                              onClick={() =>
                                void handleAssignToSprint(task, s.id)
                              }
                              className="w-full px-3 py-2 text-left text-xs text-slate-700 hover:bg-orange-50 hover:text-orange-700 transition"
                            >
                              <span className="font-medium">{s.name}</span>
                              <span className="ml-1 text-[10px] text-slate-400">
                                ({s.status})
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
