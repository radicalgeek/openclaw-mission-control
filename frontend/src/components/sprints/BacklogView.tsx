"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Calendar, Plus, Tag, X, ChevronDown, ArrowRight, Pencil, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type TaskRead,
  type BacklogTaskCreate,
  type BacklogTaskUpdate,
  type SprintRead,
  type TagRef,
  listBacklog,
  createBacklogTask,
  updateBacklogTask,
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

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-blue-100 text-blue-700",
  high: "bg-orange-100 text-orange-700",
  critical: "bg-red-100 text-red-700",
  urgent: "bg-red-100 text-red-700",
};

const STATUS_OPTIONS = ["inbox", "in_progress", "review", "done"] as const;
const STATUS_LABELS: Record<string, string> = {
  inbox: "Inbox",
  in_progress: "In Progress",
  review: "Review",
  done: "Done",
};

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
  const [formError, setFormError] = useState<string | null>(null);

  // Sprint assignment
  const [assignPopover, setAssignPopover] = useState<string | null>(null);
  const [assignBusy, setAssignBusy] = useState<string | null>(null);

  // Detail panel
  const [selectedTask, setSelectedTask] = useState<TaskRead | null>(null);
  const [editDraft, setEditDraft] = useState<BacklogTaskUpdate>({});
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

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

  // Keep selected task in sync after reload
  useEffect(() => {
    if (selectedTask) {
      const updated = tasks.find((t) => t.id === selectedTask.id);
      if (updated) setSelectedTask(updated);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks]);

  const handleCreate = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!form.title.trim()) return;
      setSaving(true);
      setFormError(null);
      try {
        await createBacklogTask(boardId, form);
        setForm({ title: "", description: "", priority: "medium", tag_ids: [], due_at: null });
        setShowForm(false);
        await loadTasks();
      } catch (err) {
        setFormError(err instanceof ApiError ? (err.message ?? "Failed") : "Failed");
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

  const handleSaveEdit = useCallback(async () => {
    if (!selectedTask || Object.keys(editDraft).length === 0) return;
    setEditBusy(true);
    setEditError(null);
    try {
      await updateBacklogTask(boardId, selectedTask.id, editDraft);
      setEditDraft({});
      setEditingTitle(false);
      await loadTasks();
    } catch (err) {
      setEditError(err instanceof ApiError ? (err.message ?? "Failed to save") : "Failed to save");
    } finally {
      setEditBusy(false);
    }
  }, [boardId, selectedTask, editDraft, loadTasks]);

  const openDetail = (task: TaskRead) => {
    setSelectedTask(task);
    setEditDraft({});
    setEditError(null);
    setEditingTitle(false);
    setAssignPopover(null);
  };

  const closeDetail = () => {
    setSelectedTask(null);
    setEditDraft({});
    setEditError(null);
    setEditingTitle(false);
  };

  const toggleFormTag = (tagId: string) => {
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

  const toggleDetailTag = (tagId: string) => {
    const currentIds =
      editDraft.tag_ids !== undefined
        ? (editDraft.tag_ids ?? [])
        : (selectedTask?.tags.map((t) => t.id) ?? []);
    setEditDraft((d) => ({
      ...d,
      tag_ids: currentIds.includes(tagId)
        ? currentIds.filter((id) => id !== tagId)
        : [...currentIds, tagId],
    }));
  };

  const hasDraftChanges = Object.keys(editDraft).length > 0;

  const openSprints = sprints.filter(
    (s) => s.status === "draft" || s.status === "queued",
  );
  const sprintMap = Object.fromEntries(sprints.map((s) => [s.id, s]));

  // Values shown in the detail panel (draft overrides persisted)
  const detailTitle =
    editDraft.title !== undefined ? editDraft.title : (selectedTask?.title ?? "");
  const detailDesc =
    editDraft.description !== undefined
      ? editDraft.description
      : (selectedTask?.description ?? "");
  const detailPriority =
    editDraft.priority !== undefined
      ? editDraft.priority
      : (selectedTask?.priority ?? "medium");
  const detailStatus =
    editDraft.status !== undefined
      ? editDraft.status
      : (selectedTask?.status ?? "inbox");
  const detailDue =
    editDraft.due_at !== undefined ? editDraft.due_at : (selectedTask?.due_at ?? null);
  const detailTagIds =
    editDraft.tag_ids !== undefined
      ? (editDraft.tag_ids ?? [])
      : (selectedTask?.tags.map((t) => t.id) ?? []);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Ticket list */}
      <div
        className={cn(
          "flex flex-col overflow-hidden border-r border-slate-200 transition-all duration-200",
          selectedTask ? "w-[360px] shrink-0" : "flex-1",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
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

        {/* Create form */}
        {showForm && (
          <form
            onSubmit={(e) => void handleCreate(e)}
            className="border-b border-slate-200 bg-orange-50/60 px-5 py-4 space-y-3"
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
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
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
                        onClick={() => toggleFormTag(tag.id)}
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
            {formError && <p className="text-xs text-red-500">{formError}</p>}
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
                  setForm({ title: "", description: "", priority: "medium", tag_ids: [], due_at: null });
                }}
                className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Ticket list */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <p className="py-12 text-center text-sm text-slate-400">Loading backlog…</p>
          )}
          {!loading && tasks.length === 0 && !showForm && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <div className="rounded-full bg-slate-100 p-4">
                <Plus className="h-6 w-6 text-slate-400" />
              </div>
              <p className="text-sm font-medium text-slate-600">Backlog is empty</p>
              <p className="text-xs text-slate-400">Add tickets to plan your upcoming work.</p>
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
              const isOverdue = task.due_at ? new Date(task.due_at) < new Date() : false;
              const isSelected = selectedTask?.id === task.id;

              return (
                <div
                  key={task.id}
                  className={cn(
                    "rounded-xl border transition-colors",
                    isSelected
                      ? "border-orange-300 shadow-sm"
                      : "border-slate-100 hover:border-slate-200",
                  )}
                >
                  {/* Card - clickable to open detail */}
                  <div
                    className="cursor-pointer overflow-hidden rounded-t-xl"
                    onClick={() => (isSelected ? closeDetail() : openDetail(task))}
                  >
                    <TaskCard
                      title={task.title}
                      status={task.status as "inbox" | "in_progress" | "review" | "done"}
                      priority={task.priority}
                      due={dueDate}
                      isOverdue={isOverdue}
                      tags={task.tags.map((t) => ({ id: t.id, name: t.name, color: t.color }))}
                      assignee={task.assigned_agent_id ? "Agent" : undefined}
                    />
                  </div>

                  {/* Sprint assignment bar - always visible */}
                  <div className="relative flex items-center gap-2 rounded-b-xl bg-slate-50 px-3 py-1.5 border-t border-slate-100">
                    {assignedSprint ? (
                      <>
                        <span className="flex items-center gap-1 rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-medium text-orange-700">
                          <span className="h-1.5 w-1.5 rounded-full bg-orange-400" />
                          {assignedSprint.name}
                        </span>
                        <button
                          disabled={assignBusy === task.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleRemoveFromSprint(task);
                          }}
                          className="ml-auto flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium text-slate-400 hover:bg-red-50 hover:text-red-500 transition disabled:opacity-40"
                        >
                          <X className="h-3 w-3" />
                          Remove
                        </button>
                      </>
                    ) : (
                      <div className="relative w-full">
                        <button
                          disabled={assignBusy === task.id || openSprints.length === 0}
                          onClick={(e) => {
                            e.stopPropagation();
                            setAssignPopover((prev) =>
                              prev === task.id ? null : task.id,
                            );
                          }}
                          className={cn(
                            "flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition",
                            openSprints.length === 0
                              ? "cursor-default text-slate-300"
                              : "text-orange-500 hover:bg-orange-50 hover:text-orange-700",
                          )}
                        >
                          {assignBusy === task.id ? (
                            "Assigning…"
                          ) : openSprints.length === 0 ? (
                            "No open sprints"
                          ) : (
                            <>
                              <ArrowRight className="h-3 w-3" />
                              Add to sprint
                              <ChevronDown className="h-3 w-3" />
                            </>
                          )}
                        </button>
                        {assignPopover === task.id && (
                          <div className="absolute left-0 top-7 z-20 w-52 rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
                            {openSprints.map((s) => (
                              <button
                                key={s.id}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void handleAssignToSprint(task, s.id);
                                }}
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

      {/* Detail panel */}
      {selectedTask && (
        <div className="flex flex-1 flex-col overflow-hidden bg-white">
          {/* Header */}
          <div className="flex shrink-0 items-center gap-3 border-b border-slate-200 px-6 py-3">
            <div className="flex-1 min-w-0">
              {editingTitle ? (
                <input
                  ref={titleRef}
                  autoFocus
                  value={detailTitle ?? ""}
                  onChange={(e) => setEditDraft((d) => ({ ...d, title: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleSaveEdit();
                    if (e.key === "Escape") {
                      setEditingTitle(false);
                      setEditDraft((d) => {
                        const { title: _t, ...rest } = d;
                        return rest;
                      });
                    }
                  }}
                  className="w-full rounded-lg border border-orange-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 outline-none focus:ring-1 focus:ring-orange-200"
                />
              ) : (
                <div className="flex items-center gap-2 group min-w-0">
                  <h2 className="truncate text-sm font-semibold text-slate-800">
                    {selectedTask.title}
                  </h2>
                  <button
                    onClick={() => {
                      setEditingTitle(true);
                      setEditDraft((d) => ({ ...d, title: selectedTask.title }));
                    }}
                    className="shrink-0 opacity-0 group-hover:opacity-100 transition text-slate-400 hover:text-slate-600"
                    title="Edit title"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {hasDraftChanges && (
                <button
                  onClick={() => void handleSaveEdit()}
                  disabled={editBusy}
                  className="flex items-center gap-1 rounded-lg bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50 transition"
                >
                  <Check className="h-3 w-3" />
                  {editBusy ? "Saving…" : "Save"}
                </button>
              )}
              <button
                onClick={closeDetail}
                className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
                title="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {editError && (
            <div className="shrink-0 bg-red-50 px-6 py-2 text-xs text-red-600">
              {editError}
            </div>
          )}

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            {/* Status + Priority */}
            <div className="flex flex-wrap gap-6">
              <div className="space-y-2">
                <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Status
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_OPTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => setEditDraft((d) => ({ ...d, status: s }))}
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition border",
                        detailStatus === s
                          ? "border-orange-300 bg-orange-100 text-orange-800"
                          : "border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50",
                      )}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Priority
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {PRIORITY_OPTIONS.map((p) => (
                    <button
                      key={p}
                      onClick={() => setEditDraft((d) => ({ ...d, priority: p }))}
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition border",
                        detailPriority === p
                          ? cn(PRIORITY_COLORS[p] ?? "bg-slate-100 text-slate-600", "border-transparent")
                          : "border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50",
                      )}
                    >
                      {p.charAt(0).toUpperCase() + p.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Description */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Description
              </label>
              <textarea
                value={detailDesc ?? ""}
                onChange={(e) =>
                  setEditDraft((d) => ({ ...d, description: e.target.value || null }))
                }
                placeholder="Add a description…"
                rows={4}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 outline-none focus:border-orange-300 focus:bg-white focus:ring-1 focus:ring-orange-100 transition"
              />
            </div>

            {/* Due date */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                <Calendar className="h-3 w-3" />
                Due date
              </label>
              <input
                type="date"
                value={detailDue ? detailDue.substring(0, 10) : ""}
                onChange={(e) =>
                  setEditDraft((d) => ({
                    ...d,
                    due_at: e.target.value ? `${e.target.value}T00:00:00Z` : null,
                  }))
                }
                className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm outline-none focus:border-orange-300 focus:bg-white transition"
              />
            </div>

            {/* Tags */}
            {orgTags.length > 0 && (
              <div className="space-y-2">
                <label className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  <Tag className="h-3 w-3" />
                  Tags
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {orgTags.map((tag) => {
                    const selected = detailTagIds.includes(tag.id);
                    return (
                      <button
                        key={tag.id}
                        type="button"
                        onClick={() => toggleDetailTag(tag.id)}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition",
                          selected
                            ? "border-orange-300 bg-orange-100 text-orange-800"
                            : "border-slate-200 bg-slate-50 text-slate-500 hover:border-slate-300",
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

            {/* Sprint assignment */}
            <div className="space-y-2">
              <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Sprint
              </label>
              {selectedTask.sprint_id && sprintMap[selectedTask.sprint_id] ? (
                <div className="flex items-center gap-3">
                  <span className="flex items-center gap-1.5 rounded-full bg-orange-100 px-3 py-1 text-xs font-medium text-orange-700">
                    <span className="h-1.5 w-1.5 rounded-full bg-orange-400" />
                    {sprintMap[selectedTask.sprint_id].name}
                  </span>
                  <button
                    disabled={assignBusy === selectedTask.id}
                    onClick={() => void handleRemoveFromSprint(selectedTask)}
                    className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-red-400 hover:bg-red-50 hover:text-red-600 transition disabled:opacity-40"
                  >
                    <X className="h-3.5 w-3.5" />
                    Remove from sprint
                  </button>
                </div>
              ) : openSprints.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {openSprints.map((s) => (
                    <button
                      key={s.id}
                      disabled={assignBusy === selectedTask.id}
                      onClick={() => void handleAssignToSprint(selectedTask, s.id)}
                      className="flex items-center gap-1.5 rounded-lg border border-orange-200 bg-orange-50 px-3 py-1.5 text-xs font-medium text-orange-600 hover:bg-orange-100 transition disabled:opacity-40"
                    >
                      <ArrowRight className="h-3 w-3" />
                      {s.name}
                      <span className="text-[10px] text-orange-400">({s.status})</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400">No open sprints available.</p>
              )}
            </div>

            {/* Metadata */}
            <div className="border-t border-slate-100 pt-4 space-y-1 text-[11px] text-slate-400">
              <p>
                Created{" "}
                {new Date(selectedTask.created_at).toLocaleString("en-GB", {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
              <p>
                Updated{" "}
                {new Date(selectedTask.updated_at).toLocaleString("en-GB", {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
