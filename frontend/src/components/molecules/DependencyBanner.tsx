import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface DependencyBannerDependency {
  id: string;
  title: string;
  statusLabel: string;
  isBlocking?: boolean;
  isDone?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}

interface DependencyBannerProps {
  variant?: DependencyBannerVariant;
  dependencies?: DependencyBannerDependency[];
  children?: ReactNode;
  className?: string;
  emptyMessage?: string;
}

type DependencyBannerVariant = "blocked" | "resolved";

// Brand-aware tone classes — driven by --danger-* and --info-* CSS vars set
// in src/lib/branding.tsx. Works on both light and dark surfaces.
const toneClassByVariant: Record<DependencyBannerVariant, string> = {
  blocked: "border-danger-border bg-danger-soft text-danger",
  resolved: "border-info-border bg-info-soft text-info",
};

export function DependencyBanner({
  variant = "blocked",
  dependencies = [],
  children,
  className,
  emptyMessage = "No dependencies.",
}: DependencyBannerProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {dependencies.length > 0 ? (
        dependencies.map((dependency) => {
          const isBlocking = dependency.isBlocking === true;
          const isDone = dependency.isDone === true;
          return (
            <button
              key={dependency.id}
              type="button"
              onClick={dependency.onClick}
              disabled={dependency.disabled}
              className={cn(
                "w-full rounded-lg border px-3 py-2 text-left transition",
                isBlocking
                  ? "border-danger-border bg-danger-soft hover:opacity-90"
                  : isDone
                    ? "border-success-border bg-success-soft hover:opacity-90"
                    : "border-neutral-border bg-neutral-soft hover:opacity-90",
                dependency.disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <p
                  className={cn(
                    "truncate text-sm font-medium",
                    isBlocking
                      ? "text-danger"
                      : isDone
                        ? "text-success"
                        : "text-neutral",
                  )}
                >
                  {dependency.title}
                </p>
                <span
                  className={cn(
                    "text-[10px] font-semibold uppercase tracking-wide",
                    isBlocking
                      ? "text-danger"
                      : isDone
                        ? "text-success"
                        : "text-neutral",
                  )}
                >
                  {dependency.statusLabel}
                </span>
              </div>
            </button>
          );
        })
      ) : (
        <p className="text-sm text-neutral">{emptyMessage}</p>
      )}
      {children ? (
        <div
          className={cn(
            "rounded-lg border p-3 text-xs",
            toneClassByVariant[variant],
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
