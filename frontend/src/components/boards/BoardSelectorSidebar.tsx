"use client";

import { cn } from "@/lib/utils";

type Board = {
  id: string;
  name: string;
};

type Props = {
  boards: Board[];
  currentBoardId: string;
  onSelectBoard: (boardId: string) => void;
  loading?: boolean;
};

/**
 * Shared board-selector sidebar used by Boards, Planning, and Sprints.
 * Displays all boards in a fixed-width list; highlights the currently active
 * board with the global accent colour.
 */
export function BoardSelectorSidebar({
  boards,
  currentBoardId,
  onSelectBoard,
  loading = false,
}: Props) {
  return (
    <nav
      className="flex w-48 shrink-0 flex-col border-r border-slate-200 bg-white overflow-y-auto"
      aria-label="Board selector"
    >
      <div className="px-3 py-3 border-b border-slate-100">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Boards
        </p>
      </div>

      {loading ? (
        <div className="space-y-1 p-2">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-9 animate-pulse rounded-lg bg-slate-100"
            />
          ))}
        </div>
      ) : boards.length === 0 ? (
        <p className="px-4 py-4 text-xs text-slate-400">No boards.</p>
      ) : (
        <div className="py-1">
          {boards.map((board) => {
            const isActive = board.id === currentBoardId;
            return (
              <button
                key={board.id}
                type="button"
                onClick={() => onSelectBoard(board.id)}
                className={cn(
                  "w-full px-4 py-2.5 text-left text-sm transition",
                  isActive
                    ? "bg-[color:var(--accent-soft)] font-medium text-[color:var(--accent-strong)]"
                    : "text-slate-700 hover:bg-slate-50",
                )}
                aria-current={isActive ? "page" : undefined}
              >
                <span className="block truncate">{board.name}</span>
              </button>
            );
          })}
        </div>
      )}
    </nav>
  );
}
