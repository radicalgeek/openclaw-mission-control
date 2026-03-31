"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  type TaskRead,
  type BacklogTaskCreate,
  listBacklog,
  createBacklogTask,
} from "@/api/sprints";
import { ApiError } from "@/api/mutator";

type Props = {
  boardId: string;
};

const priorityDot: Record<string, string> = {
  low: "bg-slate-300",
  medium: "bg-yellow-400",
  high: "bg-orange-500",
  critical: "bg-red-600",
};

export function BacklogView({ boardId }: Props) {
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<BacklogTaskCreate>({
    title: "",
    description: "",
    priority: "medium",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        setForm({ title: "", description: "", priority: "medium" });
        setShowForm(false);
        await loadTasks();
      } catch (err) {
        setError(
          err instanceof ApiError ? (err.message ?? "Failed") : "Failed",
        );
      } finally {
        setSaving(false);
      }
    },
    [boardId, form, loadTasks],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-slate-800">Backlog</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 transition"
        >
          {showForm ? "Cancel" : "+ Add ticket"}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="border-b border-slate-100 bg-orange-50 px-6 py-4 space-y-3"
        >
          <input
            required
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Ticket title"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
          />
          <textarea
            value={form.description ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, description: e.target.value }))
            }
            placeholder="Description (optional)"
            rows={2}
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
          />
          <div className="flex items-center gap-3">
            <select
              value={form.priority ?? "medium"}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  priority: e.target.value as BacklogTaskCreate["priority"],
                }))
              }
              className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50 transition"
            >
              {saving ? "Saving…" : "Add"}
            </button>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </form>
      )}

      {/* Task list */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading && (
          <p className="py-8 text-center text-sm text-slate-400">Loading backlog…</p>
        )}
        {!loading && tasks.length === 0 && !showForm && (
          <div className="flex flex-col items-center justify-center gap-2 py-12">
            <p className="text-sm text-slate-500">Backlog is empty.</p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-1 rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 transition"
            >
              Add first ticket
            </button>
          </div>
        )}
        <div className="space-y-2">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="flex items-start gap-3 rounded-xl border border-slate-100 bg-white p-3 shadow-sm"
            >
              <span
                className={cn(
                  "mt-1 h-2 w-2 shrink-0 rounded-full",
                  priorityDot[task.priority] ?? "bg-slate-300",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">
                  {task.title}
                </p>
                {task.description && (
                  <p className="mt-0.5 line-clamp-2 text-xs text-slate-400">
                    {task.description}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                  {task.priority}
                </span>
                {task.sprint_id && (
                  <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-medium text-blue-500">
                    in sprint
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
