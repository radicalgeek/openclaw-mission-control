"use client";

import { useEffect, useState } from "react";
import { Copy, RefreshCw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChannelRead, ChannelWebhookInfo } from "@/api/channels";
import { getChannelWebhookInfo, regenerateChannelWebhookSecret } from "@/api/channels";

type Props = {
  channel: ChannelRead;
  isOpen: boolean;
  onClose: () => void;
};

export function ChannelWebhookModal({ channel, isOpen, onClose }: Props) {
  const [info, setInfo] = useState<ChannelWebhookInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedField, setCopiedField] = useState<"url" | "secret" | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setInfo(null);
    setError(null);
    setIsLoading(true);
    getChannelWebhookInfo(channel.id)
      .then((res) => {
        if (res.status === 200) setInfo(res.data);
        else setError("Failed to load webhook information.");
      })
      .catch(() => setError("Failed to load webhook information."))
      .finally(() => setIsLoading(false));
  }, [isOpen, channel.id]);

  const handleCopy = async (text: string, field: "url" | "secret") => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      // ignore
    }
  };

  const handleRegenerate = async () => {
    if (!confirm("Regenerate the webhook secret? Any existing integrations using the current secret will stop working.")) return;
    setIsRegenerating(true);
    try {
      const res = await regenerateChannelWebhookSecret(channel.id);
      if (res.status === 200) setInfo(res.data);
      else setError("Failed to regenerate secret.");
    } catch {
      setError("Failed to regenerate secret.");
    } finally {
      setIsRegenerating(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Webhook Configuration</h2>
            <p className="mt-0.5 text-xs text-slate-500">#{channel.name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {isLoading && (
          <p className="py-4 text-center text-sm text-slate-500">Loading…</p>
        )}

        {error && (
          <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</div>
        )}

        {info && !isLoading && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              POST JSON payloads to the webhook URL below. Optionally include an{" "}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">X-Webhook-Secret</code>{" "}
              header matching the secret to authenticate the request.
            </p>

            {/* Webhook URL */}
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Webhook URL</label>
              {info.webhook_url ? (
                <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <span className="flex-1 truncate font-mono text-xs text-slate-700">
                    {info.webhook_url}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleCopy(info.webhook_url!, "url")}
                    className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                    title="Copy URL"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                  {copiedField === "url" && (
                    <span className="flex-shrink-0 text-xs text-green-600">Copied!</span>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  Set <code className="rounded bg-slate-100 px-1 text-xs">BASE_URL</code> in your server configuration to generate a webhook URL.
                </p>
              )}
            </div>

            {/* Webhook Secret */}
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Webhook Secret</label>
              <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <span className="flex-1 truncate font-mono text-xs text-slate-700">
                  {info.webhook_secret}
                </span>
                <button
                  type="button"
                  onClick={() => handleCopy(info.webhook_secret, "secret")}
                  className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                  title="Copy secret"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                {copiedField === "secret" && (
                  <span className="flex-shrink-0 text-xs text-green-600">Copied!</span>
                )}
              </div>
            </div>

            {/* Regenerate */}
            <div className="flex items-center justify-between border-t border-slate-200 pt-4">
              <p className="text-xs text-slate-500">
                Regenerating the secret invalidates the current one immediately.
              </p>
              <button
                type="button"
                onClick={handleRegenerate}
                disabled={isRegenerating}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium",
                  isRegenerating
                    ? "cursor-not-allowed text-slate-400"
                    : "text-rose-600 hover:bg-rose-50",
                )}
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isRegenerating && "animate-spin")} />
                {isRegenerating ? "Regenerating…" : "Regenerate Secret"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
