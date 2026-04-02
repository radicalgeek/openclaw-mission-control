"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  type listBoardsApiV1BoardsGetResponse,
  useListBoardsApiV1BoardsGet,
} from "@/api/generated/boards/boards";
import { ApiError } from "@/api/mutator";
import {
  type SprintRead,
  type SprintCreate,
  type TagRef,
  listSprints,
  createSprint,
  updateSprint,
  listOrgTags,
} from "@/api/sprints";
import { cn } from "@/lib/utils";
import { BoardSelectorSidebar } from "@/components/boards/BoardSelectorSidebar";
import { SprintList } from "./SprintList";
import { SprintDetail } from "./SprintDetail";
import { BacklogView } from "./BacklogView";

type Props = {
  boardId: string;
};

type View = { type: "backlog" } | { type: "sprint"; sprint: SprintRead };

export function SprintsLayout({ boardId }: Props) {
  const router = useRouter();

  // ── Boards ─────────────────────────────────────────────────────────────────
  const boardsQuery = useListBoardsApiV1BoardsGet<
    listBoardsApiV1BoardsGetResponse,
    ApiError
  >(undefined, { query: { refetchOnMount: false } });
  const allBoards =
    boardsQuery.data?.status === 200
      ? (boardsQuery.data.data.items ?? [])
      : [];
  const currentBoard = allBoards.find((b) => b.id === boardId);

  // ── Org tags ───────────────────────────────────────────────────────────────
  const [orgTags, setOrgTags] = useState<TagRef[]>([]);
  useEffect(() => {
    void listOrgTags().then((res) => {
      if (res.status === 200) setOrgTags(res.data.items ?? []);
    }).catch(() => undefined);
  }, []);

  // ── Sprints ────────────────────────────────────────────────────────────────
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
    setView({ type: "backlog" });
  }, [boardId, loadSprints]);

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

  const handleReorder = useCallback(
    async (orderedIds: string[]) => {
      // Optimistically reorder locally
      setSprints((prev) =>
        prev.map((s) => {
          const newIdx = orderedIds.indexOf(s.id);
          return newIdx === -1 ? s : { ...s, position: newIdx + 1 };
        }),
      );
      // Persist to backend
      await Promise.all(
        orderedIds.map((id, idx) =>
          updateSprint(boardId, id, { position: idx + 1 }).catch(() => undefined),
        ),
      );
    },
    [boardId],
  );

  const selectedSprintId =
    view.type === "sprint" ? view.sprint.id : null;

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* ── Board selector ── */}
      <BoardSelectorSidebar
        boards={allBoards}
        currentBoardId={boardId}
        onSelectBoard={(id) => router.push(`/sprints/${id}`)}
        loading={boardsQuery.isLoading && allBoards.length === 0}
        createBoardHref="/boards/new"
      />

      {/* ── Sprint list ── */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <SprintList
          sprints={sprints}
          selectedSprintId={selectedSprintId}
          onSelectSprint={(s) => setView({ type: "sprint", sprint: s })}
          onNewSprint={() => setShowNewForm(true)}
          onSelectBacklog={() => setView({ type: "backlog" })}
          showingBacklog={view.type === "backlog"}
          loading={loading}
          onReorder={(ids) => void handleReorder(ids)}
        />
      </aside>

      {/* ── Main content ── */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden bg-slate-50">
        {/* New sprint form (slide-in) */}
        {showNewForm && (
          <div className="border-b border-slate-200 bg-white px-6 py-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">New Sprint</h3>
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
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-[color:var(--accent)] focus:ring-1 focus:ring-[color:var(--accent-soft)]"
              />
              <input
                value={newGoal}
                onChange={(e) => setNewGoal(e.target.value)}
                placeholder="Goal (optional)"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-[color:var(--accent)] focus:ring-1 focus:ring-[color:var(--accent-soft)]"
              />
              {createError && (
                <p className="text-xs text-red-500">{createError}</p>
              )}
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="rounded-md bg-[color:var(--accent)] px-4 py-1.5 text-sm font-medium text-white hover:bg-[color:var(--accent-strong)] disabled:opacity-50 transition"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowNewForm(false);
                    setNewName("");
                    setNewGoal("");
                    setCreateError(null);
                  }}
                  className="rounded-md border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Board name breadcrumb */}
        {currentBoard && (
          <div className="flex items-center gap-2 border-b border-slate-100 bg-white px-6 py-2.5">
            <span className="text-xs text-slate-400">Board</span>
            <span className="text-xs text-slate-300">/</span>
            <span className="text-xs font-medium text-slate-700">
              {currentBoard.name}
            </span>
          </div>
        )}

        {view.type === "sprint" ? (
          <SprintDetail
            key={view.sprint.id}
            boardId={boardId}
            sprint={view.sprint}
            sprints={sprints}
            orgTags={orgTags}
            onRefresh={() => void loadSprints()}
          />
        ) : (
          <BacklogView
            boardId={boardId}
            sprints={sprints}
            orgTags={orgTags}
            onSprintChange={() => void loadSprints()}
          />
        )}
      </main>
    </div>
  );
}
