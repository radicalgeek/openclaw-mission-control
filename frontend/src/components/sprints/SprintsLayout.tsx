"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type SprintRead,
  type SprintCreate,
  listSprints,
  createSprint,
} from "@/api/sprints";
import { SprintList } from "./SprintList";
import { SprintDetail } from "./SprintDetail";
import { BacklogView } from "./BacklogView";
import { ApiError } from "@/api/mutator";

type Props = {
  boardId: string;
};

type View = { type: "backlog" } | { type: "sprint"; sprint: SprintRead };

export function SprintsLayout({ boardId }: Props) {
  const [sprints, setSprints] = useState<SprintRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>({ type: "backlog" });
  const [showNewForm, setShowNewForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newGoal, setNewGoal] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadSprints = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSprints(boardId);
      setSprints(res.data);
      // Keep selected sprint in sync after refresh
      setView((prev) => {
        if (prev.type === "sprint") {
          const updated = res.data.find((s) => s.id === prev.sprint.id);
          return updated ? { type: "sprint", sprint: updated } : { type: "backlog" };
        }
        return prev;
      });
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [boardId]);

  useEffect(() => {
    void loadSprints();
  }, [loadSprints]);

  const handleCreateSprint = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!newName.trim()) return;
      setCreating(true);
      setCreateError(null);
      const payload: SprintCreate = { name: newName.trim() };
      if (newGoal.trim()) payload.goal = newGoal.trim();
      try {
        const res = await createSprint(boardId, payload);
        setNewName("");
        setNewGoal("");
        setShowNewForm(false);
        await loadSprints();
        setView({ type: "sprint", sprint: res.data });
      } catch (err) {
        setCreateError(
          err instanceof ApiError ? (err.message ?? "Failed") : "Failed",
        );
      } finally {
        setCreating(false);
      }
    },
    [boardId, newName, newGoal, loadSprints],
  );

  const selectedSprintId =
    view.type === "sprint" ? view.sprint.id : null;

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* Left sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <SprintList
          sprints={sprints}
          selectedSprintId={selectedSprintId}
          onSelectSprint={(s) => setView({ type: "sprint", sprint: s })}
          onNewSprint={() => setShowNewForm(true)}
          onSelectBacklog={() => setView({ type: "backlog" })}
          showingBacklog={view.type === "backlog"}
          loading={loading}
        />
      </aside>

      {/* Main content */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-slate-50">
        {/* New sprint modal (inline) */}
        {showNewForm && (
          <div className="border-b border-slate-200 bg-white px-6 py-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">
              New Sprint
            </h3>
            <form
              onSubmit={(e) => void handleCreateSprint(e)}
              className="space-y-3"
            >
              <input
                required
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Sprint name"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
              />
              <input
                value={newGoal}
                onChange={(e) => setNewGoal(e.target.value)}
                placeholder="Sprint goal (optional)"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-1 focus:ring-orange-200"
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="rounded-md bg-orange-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50 transition"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowNewForm(false)}
                  className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
              </div>
              {createError && (
                <p className="text-xs text-red-500">{createError}</p>
              )}
            </form>
          </div>
        )}

        {view.type === "backlog" ? (
          <BacklogView boardId={boardId} />
        ) : (
          <SprintDetail
            boardId={boardId}
            sprint={view.sprint}
            onRefresh={() => void loadSprints()}
          />
        )}
      </main>
    </div>
  );
}
