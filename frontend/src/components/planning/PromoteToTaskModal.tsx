"use client";

import { useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PlanRead, PlanPromoteRequest } from "@/api/plans";

type Props = {
  plan: PlanRead;
  onConfirm: (payload: PlanPromoteRequest) => Promise<void>;
  onClose: () => void;
};

const PRIORITY_SCORE_LABELS: Record<number, string> = {
  15: "Low (15)",
  35: "Medium (35)",
  65: "High (65)",
  90: "Critical (90)",
};

export function PromoteToTaskModal({ plan, onConfirm, onClose }: Props) {
  const [taskTitle, setTaskTitle] = useState(plan.title);
  const [priority, setPriority] = useState("medium");
  const [priorityScore, setPriorityScore] = useState(35);
  const [estimateMinutes, setEstimateMinutes] = useState<number | null>(null);
  const [targetStatus, setTargetStatus] = useState<"triage" | "backlog" | "inbox">("inbox");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm({
        task_title: taskTitle.trim() || undefined,
        task_priority: priority,
        task_priority_score: priorityScore,
        estimate_minutes: estimateMinutes,
        target_status: targetStatus,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to promote plan");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">
            Promote to Task
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          This will create a task linked to this plan. The plan status will
          become <strong>Active</strong>.
        </p>

        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Task title
            </label>
            <input
              type="text"
              value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-[color:var(--accent)] focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
              placeholder="Task title"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Priority
            </label>
            <select
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
                const defaults: Record<string, number> = {
                  low: 15,
                  medium: 35,
                  high: 65,
                  critical: 90,
                };
                setPriorityScore(defaults[e.target.value] ?? 35);
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-[color:var(--accent)] focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Priority score:{" "}
              <span className="font-semibold text-slate-800">
                {PRIORITY_SCORE_LABELS[priorityScore] ?? priorityScore}
              </span>
            </label>
            <input
              type="range"
              min={1}
              max={100}
              value={priorityScore}
              onChange={(e) => setPriorityScore(Number(e.target.value))}
              className="w-full accent-[color:var(--accent)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Estimate (minutes)
            </label>
            <input
              type="number"
              min={0}
              step={15}
              value={estimateMinutes ?? ""}
              onChange={(e) =>
                setEstimateMinutes(e.target.value ? Number(e.target.value) : null)
              }
              placeholder="e.g. 90"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-[color:var(--accent)] focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Initial status
            </label>
            <select
              value={targetStatus}
              onChange={(e) =>
                setTargetStatus(e.target.value as "triage" | "backlog" | "inbox")
              }
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-[color:var(--accent)] focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
            >
              <option value="triage">Triage</option>
              <option value="backlog">Backlog</option>
              <option value="inbox">Inbox</option>
            </select>
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Promoting…" : "Promote to task"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
