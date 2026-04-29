"use client";

import { cn } from "@/lib/utils";
import type { PlanStatus } from "@/api/plans";

type Props = {
  status: PlanStatus;
  className?: string;
};

// Brand-aware plan-status tones — driven by semantic tokens in tailwind.config.cjs.
const CONFIG: Record<PlanStatus, { label: string; classes: string }> = {
  draft:     { label: "Draft",     classes: "bg-neutral-soft text-neutral border border-neutral-border" },
  active:    { label: "Active",    classes: "bg-info-soft text-info border border-info-border" },
  completed: { label: "Completed", classes: "bg-success-soft text-success border border-success-border" },
  archived:  { label: "Archived",  classes: "bg-warning-soft text-warning border border-warning-border" },
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
