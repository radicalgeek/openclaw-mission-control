"use client";

import Link from "next/link";
import { Plus } from "lucide-react";

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
  /** If provided, renders a '+ New board' link at the bottom of the list (admin only). */
  createBoardHref?: string;
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
  createBoardHref,
}: Props) {
  return (
    <nav
      className="flex w-48 shrink-0 flex-col border-r border-[color:var(--border)] bg-[color:var(--surface)] overflow-y-auto"
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
        <div className="flex-1 py-1 overflow-y-auto">
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

      {createBoardHref && (
        <div className="shrink-0 border-t border-slate-100 p-2">
          <Link
            href={createBoardHref}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-slate-500 hover:bg-slate-50 hover:text-[color:var(--accent-strong)] transition"
          >
            <Plus className="h-3.5 w-3.5" />
            New board
          </Link>
        </div>
      )}
    </nav>
  );
}
