"use client";

import { cn } from "@/lib/utils";
import type { PlanStatus } from "@/api/plans";

type Props = {
  status: PlanStatus;
  className?: string;
};

const CONFIG: Record<PlanStatus, { label: string; classes: string }> = {
  draft:     { label: "Draft",     classes: "bg-slate-100 text-slate-600" },
  active:    { label: "Active",    classes: "bg-orange-100 text-orange-700" },
  completed: { label: "Completed", classes: "bg-green-100 text-green-700" },
  archived:  { label: "Archived",  classes: "bg-amber-100 text-amber-700" },
};

export function PlanStatusBadge({ status, className }: Props) {
  const cfg = CONFIG[status] ?? CONFIG.draft;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        cfg.classes,
        className,
      )}
    >
      {cfg.label}
    </span>
  );
}
