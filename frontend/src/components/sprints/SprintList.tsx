"use client";

import { useState } from "react";
import { GripVertical, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SprintRead } from "@/api/sprints";

type Props = {
  sprints: SprintRead[];
  selectedSprintId: string | null;
  onSelectSprint: (sprint: SprintRead) => void;
  onNewSprint: () => void;
  onSelectBacklog: () => void;
  showingBacklog: boolean;
  loading?: boolean;
  onReorder?: (orderedIds: string[]) => void;
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-500",
  queued: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  completed: "bg-blue-100 text-blue-700",
  cancelled: "bg-red-100 text-red-500",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide",
        STATUS_COLORS[status] ?? "bg-slate-100 text-slate-500",
      )}
    >
      {status}
    </span>
  );
}

function SectionLabel({ label, color }: { label: string; color: string }) {
  return (
    <p className={cn("px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wider", color)}>
      {label}
    </p>
  );
}

export function SprintList({
  sprints,
  selectedSprintId,
  onSelectSprint,
  onNewSprint,
  onSelectBacklog,
  showingBacklog,
  loading = false,
  onReorder,
}: Props) {
  const [showDone, setShowDone] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropBeforeId, setDropBeforeId] = useState<string | null>(null);

  const active = sprints.filter((s) => s.status === "active");
  const upcoming = sprints
    .filter((s) => s.status === "draft" || s.status === "queued")
    .sort((a, b) => a.position - b.position);
  const done = sprints
    .filter((s) => s.status === "completed" || s.status === "cancelled")
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

  // ── Drag-and-drop for upcoming ──────────────────────────────────────────────
  const handleDragStart = (e: React.DragEvent, id: string) => {
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e: React.DragEvent, beforeId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDropBeforeId(beforeId);
  };

  const handleDragOverEnd = (e: React.DragEvent) => {
    e.preventDefault();
    setDropBeforeId("__end__");
  };

  const handleDrop = (e: React.DragEvent, beforeId: string | null) => {
    e.preventDefault();
    if (!dragId || !onReorder) {
      setDragId(null);
      setDropBeforeId(null);
      return;
    }
    const currentIds = upcoming.map((s) => s.id);
    const withoutDragged = currentIds.filter((id) => id !== dragId);

    let newOrder: string[];
    if (beforeId === null || beforeId === "__end__") {
      newOrder = [...withoutDragged, dragId];
    } else {
      const idx = withoutDragged.indexOf(beforeId);
      newOrder =
        idx === -1
          ? [...withoutDragged, dragId]
          : [...withoutDragged.slice(0, idx), dragId, ...withoutDragged.slice(idx)];
    }

    setDragId(null);
    setDropBeforeId(null);
    onReorder(newOrder);
  };

  const handleDragEnd = () => {
    setDragId(null);
    setDropBeforeId(null);
  };

  // ── Sprint row renderer ─────────────────────────────────────────────────────
  const renderSprintRow = (sprint: SprintRead, draggable: boolean) => {
    const pct =
      sprint.ticket_count > 0
        ? Math.round((sprint.tickets_done_count / sprint.ticket_count) * 100)
        : 0;
    const isSelected = sprint.id === selectedSprintId;
    const isDragging = dragId === sprint.id;
    const isDropTarget = dropBeforeId === sprint.id && dragId !== sprint.id;

    return (
      <div key={sprint.id}>
        {isDropTarget && (
          <div className="mx-3 my-0.5 h-0.5 rounded-full bg-orange-400" />
        )}
        <div
          draggable={draggable}
          onDragStart={draggable ? (e) => handleDragStart(e, sprint.id) : undefined}
          onDragOver={draggable ? (e) => handleDragOver(e, sprint.id) : undefined}
          onDrop={draggable ? (e) => handleDrop(e, sprint.id) : undefined}
          onDragEnd={draggable ? handleDragEnd : undefined}
          className={cn(
            "group relative border-b border-slate-100 transition",
            isDragging && "opacity-30",
          )}
        >
          <button
            onClick={() => onSelectSprint(sprint)}
            className={cn(
              "w-full py-3 pr-3 text-left transition",
              draggable ? "pl-7" : "pl-3",
              isSelected ? "bg-orange-50" : "hover:bg-slate-50",
            )}
          >
            {draggable && (
              <span
                className="absolute left-1.5 top-1/2 -translate-y-1/2 cursor-grab text-slate-300 opacity-0 group-hover:opacity-100 active:cursor-grabbing"
                onMouseDown={(e) => e.stopPropagation()}
              >
                <GripVertical className="h-3.5 w-3.5" />
              </span>
            )}

            <div className="flex items-start justify-between gap-1.5">
              <span
                className={cn(
                  "truncate text-sm font-medium leading-snug",
                  isSelected ? "text-orange-800" : "text-slate-700",
                )}
              >
                {sprint.name}
              </span>
              <StatusBadge status={sprint.status} />
            </div>

            {sprint.ticket_count > 0 && (
              <div className="mt-1.5 space-y-0.5">
                <div className="flex justify-between text-[10px] text-slate-400">
                  <span>
                    {sprint.tickets_done_count}/{sprint.ticket_count}
                  </span>
                  <span>{pct}%</span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      sprint.status === "completed" ? "bg-blue-300" : "bg-orange-400",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            )}

            {sprint.goal && (
              <p className="mt-1 truncate text-[10px] text-slate-400">{sprint.goal}</p>
            )}
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Sprints
        </span>
        <button
          onClick={onNewSprint}
          title="New sprint"
          className="flex items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium text-orange-500 hover:bg-orange-50 transition"
        >
          <Plus className="h-3 w-3" />
          New
        </button>
      </div>

      {/* Backlog button */}
      <button
        onClick={onSelectBacklog}
        className={cn(
          "w-full border-b border-slate-100 px-3 py-2.5 text-left text-sm font-medium transition",
          showingBacklog ? "bg-orange-50 text-orange-800" : "text-slate-700 hover:bg-slate-50",
        )}
      >
        📋 Backlog
      </button>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="px-4 py-6 text-center text-xs text-slate-400">Loading…</p>
        )}

        {!loading && sprints.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
            <p className="text-sm text-slate-500">No sprints yet.</p>
            <button
              onClick={onNewSprint}
              className="mt-1 flex items-center gap-1 rounded-md bg-orange-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-600 transition"
            >
              <Plus className="h-3 w-3" />
              Create first sprint
            </button>
          </div>
        )}

        {/* ── Active ─────────────────────────────────────────────────────── */}
        {active.length > 0 && (
          <div>
            <SectionLabel label="Active" color="text-green-600" />
            {active.map((s) => renderSprintRow(s, false))}
          </div>
        )}

        {/* ── Upcoming ───────────────────────────────────────────────────── */}
        {upcoming.length > 0 && (
          <div>
            <SectionLabel
              label={onReorder ? "Upcoming — drag to reorder" : "Upcoming"}
              color="text-slate-400"
            />
            {upcoming.map((s) => renderSprintRow(s, !!onReorder))}
            {/* Drop zone after last item */}
            <div
              onDragOver={handleDragOverEnd}
              onDrop={(e) => handleDrop(e, null)}
              className={cn(
                "h-3 transition",
                dropBeforeId === "__end__" && dragId ? "border-t-2 border-orange-400" : "",
              )}
            />
          </div>
        )}

        {/* ── Done ───────────────────────────────────────────────────────── */}
        {done.length > 0 && (
          <div>
            <button
              onClick={() => setShowDone((v) => !v)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-600 transition"
            >
              {showDone ? (
                <ChevronDown className="h-3 w-3 shrink-0" />
              ) : (
                <ChevronRight className="h-3 w-3 shrink-0" />
              )}
              Done
              <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-normal text-slate-500">
                {done.length}
              </span>
            </button>
            {showDone && done.map((s) => renderSprintRow(s, false))}
          </div>
        )}
      </div>
    </div>
  );
}
