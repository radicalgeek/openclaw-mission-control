"use client";

/**
 * MpcAppResultCard — renders a structured MCP App result embedded in a chat message.
 *
 * When `content_type === "mcp_app_result"`, chat surfaces pass `metadata` here
 * instead of rendering the raw `content` as Markdown.
 *
 * Supported built-in apps (via `metadata.app`):
 *   - `"chart"` — renders a `ChartSpec` using <ChartBlock>
 *
 * Future MCP App results with unknown `app` values show a generic card,
 * preserving forward compatibility.
 *
 * Always falls back to <Markdown> if metadata is missing or malformed.
 */

import { ChartBlock } from "@/components/atoms/ChartBlock";
import { Markdown } from "@/components/atoms/Markdown";
import type { MarkdownVariant } from "@/components/atoms/Markdown";

export type MpcAppMetadata = Record<string, unknown>;

interface Props {
  /** The `metadata` / `event_metadata` field from the message. */
  metadata: MpcAppMetadata | null | undefined;
  /** Raw `content` field — used as Markdown fallback when metadata is invalid. */
  fallbackContent: string;
  /** Markdown variant to use in fallback mode (matches surrounding context). */
  variant?: MarkdownVariant;
}

/**
 * Narrow check: is this object shaped like a chart spec?
 * We only verify the minimum required fields; ChartBlock does full validation.
 */
function isChartMetadata(
  meta: MpcAppMetadata,
): meta is MpcAppMetadata & { spec: unknown } {
  return (
    typeof meta.app === "string" &&
    meta.app === "chart" &&
    meta.spec !== undefined &&
    meta.spec !== null
  );
}

export function MpcAppResultCard({ metadata, fallbackContent, variant = "basic" }: Props) {
  // Safety: if no metadata, fall back to plain Markdown rendering.
  if (!metadata || typeof metadata !== "object") {
    return <Markdown content={fallbackContent} variant={variant} />;
  }

  // Built-in chart app
  if (isChartMetadata(metadata)) {
    return (
      <div className="my-1 w-full rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <ChartBlock spec={metadata.spec} />
      </div>
    );
  }

  // Unknown / future MCP App — show a generic card so we don't crash.
  if (typeof metadata.app === "string") {
    return (
      <div className="my-1 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
        <span className="font-mono text-xs text-slate-400">[mcp-app: {metadata.app}]</span>
        {fallbackContent && (
          <div className="mt-1">
            <Markdown content={fallbackContent} variant={variant} />
          </div>
        )}
      </div>
    );
  }

  // Malformed metadata — fall back to Markdown.
  return <Markdown content={fallbackContent} variant={variant} />;
}
