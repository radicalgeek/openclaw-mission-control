"use client";

/**
 * McpAppRenderer — renders a live MCP App from a gateway resource URI.
 *
 * Phase 2B integration: used when a chat message has `content_type === "mcp_app_result"`
 * AND `metadata.resource_uri` is set (indicating a live gateway resource, not a
 * Phase 2A built-in app with stored metadata).
 *
 * Architecture:
 * - Fetches the resource HTML via the backend proxy (`GET /mcp/resources`)
 * - Renders in a strictly sandboxed iframe (`sandbox="allow-scripts"`)
 * - Passes tool result content via postMessage
 * - Handles bidirectional postMessage communication:
 *   - `callServerTool`  → forwarded to `POST /mcp/tools/call`
 *   - `sendMessage`     → surfaced via `onSendMessage` callback
 *   - `openLink`        → surfaced via `onOpenLink` callback
 *
 * CSP: the iframe's `srcdoc` is served with no network access (connect-src none)
 * thanks to sandbox restrictions, preventing data exfiltration from MCP App HTML.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { McpToolCallResponse, McpToolContent } from "@/api/mcp";
import { callMcpTool, readMcpResource } from "@/api/mcp";
import { Markdown } from "@/components/atoms/Markdown";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface McpAppRendererProps {
  boardId: string;
  agentId: string;
  /** The ``ui://`` resource URI to fetch and render. */
  resourceUri: string;
  /** Pre-fetched HTML — if provided, no gateway fetch is needed. */
  resourceHtml?: string | null;
  /** Structured tool result to inject into the rendered app via postMessage. */
  toolResult?: McpToolCallResponse;
  /** Fallback text rendered as Markdown if the resource cannot load. */
  fallbackContent?: string;
  /** Called when the MCP App sends a `sendMessage` postMessage event. */
  onSendMessage?: (message: string) => void;
  /** Called when the MCP App requests a link to be opened. */
  onOpenLink?: (url: string) => void;
}

// ─── PostMessage protocol ─────────────────────────────────────────────────────

interface MpcAppMessage {
  type: "callServerTool" | "sendMessage" | "openLink" | "updateContext" | "ready";
  payload?: unknown;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function McpAppRenderer({
  boardId,
  agentId,
  resourceUri,
  resourceHtml: resourceHtmlProp,
  toolResult,
  fallbackContent = "",
  onSendMessage,
  onOpenLink,
}: McpAppRendererProps) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // ── Fetch resource HTML ──────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setError(null);

    (async () => {
      try {
        // Priority: pre-fetched prop → inline tool result → gateway fetch
        if (resourceHtmlProp) {
          if (!cancelled) {
            setHtml(resourceHtmlProp);
            setLoading(false);
          }
          return;
        }
        if (toolResult?.resource_html) {
          if (!cancelled) {
            setHtml(toolResult.resource_html);
            setLoading(false);
          }
          return;
        }
        const resource = await readMcpResource(boardId, agentId, resourceUri);
        if (!cancelled) {
          setHtml(resource.text);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load MCP App resource");
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [boardId, agentId, resourceUri, resourceHtmlProp, toolResult?.resource_html]);

  // ── Inject tool result after iframe loads ────────────────────────────────
  const handleIframeLoad = useCallback(() => {
    if (!iframeRef.current || !toolResult) return;
    const message = {
      type: "toolResult",
      payload: {
        content: toolResult.content,
        _meta: { ui: { resourceUri: toolResult.ui_meta.resource_uri } },
      },
    };
    iframeRef.current.contentWindow?.postMessage(message, "*");
  }, [toolResult]);

  // ── Handle postMessage events from iframe ────────────────────────────────
  useEffect(() => {
    const handleMessage = async (event: MessageEvent) => {
      if (!iframeRef.current) return;
      if (event.source !== iframeRef.current.contentWindow) return;

      const data = event.data as MpcAppMessage;
      if (!data || typeof data.type !== "string") return;

      switch (data.type) {
        case "sendMessage": {
          const msg = typeof data.payload === "string" ? data.payload : "";
          if (msg && onSendMessage) onSendMessage(msg);
          break;
        }
        case "openLink": {
          const url = typeof data.payload === "string" ? data.payload : "";
          if (url && onOpenLink) {
            onOpenLink(url);
          }
          break;
        }
        case "callServerTool": {
          if (!data.payload || typeof data.payload !== "object") break;
          const { name, arguments: args } = data.payload as {
            name: string;
            arguments: Record<string, unknown>;
          };
          if (!name) break;
          try {
            const result = await callMcpTool(boardId, {
              agent_id: agentId,
              tool_name: name,
              arguments: args ?? {},
            });
            // Send result back to iframe
            iframeRef.current?.contentWindow?.postMessage(
              { type: "toolResult", payload: result },
              "*",
            );
          } catch {
            // Surface errors back to iframe so it can display them
            iframeRef.current?.contentWindow?.postMessage(
              { type: "toolError", payload: { name, error: "Tool call failed" } },
              "*",
            );
          }
          break;
        }
        default:
          break;
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [boardId, agentId, onSendMessage, onOpenLink]);

  // ── Render states ─────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="my-1 flex h-12 w-full items-center justify-center rounded-xl border border-slate-200 bg-slate-50">
        <span className="text-xs text-slate-400">Loading app…</span>
      </div>
    );
  }

  if (error || !html) {
    return (
      <div className="my-1 w-full rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-500">
        <span className="font-mono">[mcp-app error: {error ?? "empty resource"}]</span>
        {fallbackContent && (
          <div className="mt-1 text-slate-600">
            <Markdown content={fallbackContent} variant="basic" />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="my-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <iframe
        ref={iframeRef}
        srcDoc={html}
        // Strict sandbox: scripts allowed but no same-origin access, no popups,
        // no top navigation — preventing cookie theft or page takeover.
        sandbox="allow-scripts"
        title={`MCP App: ${resourceUri}`}
        className="h-64 w-full border-none"
        onLoad={handleIframeLoad}
      />
    </div>
  );
}

// ─── Helper: compute displayable text from tool content ──────────────────────

export function mcpToolContentText(content: McpToolContent[]): string {
  return content
    .filter((c) => c.type === "text" && c.text)
    .map((c) => c.text as string)
    .join("\n");
}
