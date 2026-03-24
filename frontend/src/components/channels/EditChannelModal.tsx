"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChannelRead } from "@/api/channels";
import { updateChannel } from "@/api/channels";

type Props = {
  channel: ChannelRead;
  isOpen: boolean;
  onClose: () => void;
  onUpdated: (updated: ChannelRead) => void;
};

export function EditChannelModal({ channel, isOpen, onClose, onUpdated }: Props) {
  const [name, setName] = useState(channel.name);
  const [description, setDescription] = useState(channel.description);
  const [isReadonly, setIsReadonly] = useState(channel.is_readonly);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset fields when modal opens with current channel data
  useEffect(() => {
    if (isOpen) {
      setName(channel.name);
      setDescription(channel.description);
      setIsReadonly(channel.is_readonly);
      setError(null);
    }
  }, [isOpen, channel]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Channel name is required");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const res = await updateChannel(channel.id, {
        name: name.trim(),
        description: description.trim(),
        is_readonly: isReadonly,
      });
      if (res.status === 200) {
        onUpdated(res.data);
        onClose();
      } else {
        throw new Error("Failed to update channel");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update channel");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Edit Channel</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</div>
          )}

          <div>
            <label htmlFor="edit-channel-name" className="mb-1 block text-sm font-medium text-slate-700">
              Channel Name
            </label>
            <input
              id="edit-channel-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label htmlFor="edit-channel-description" className="mb-1 block text-sm font-medium text-slate-700">
              Description
            </label>
            <textarea
              id="edit-channel-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={isSubmitting}
            />
          </div>

          <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 p-3 hover:bg-slate-50">
            <input
              type="checkbox"
              checked={isReadonly}
              onChange={(e) => setIsReadonly(e.target.checked)}
              disabled={isSubmitting}
              className="h-4 w-4 rounded border-slate-300"
            />
            <div>
              <p className="text-sm font-medium text-slate-900">Read-only</p>
              <p className="text-xs text-slate-500">Only webhooks and agents can post — humans cannot send messages</p>
            </div>
          </label>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                "flex-1 rounded-lg px-4 py-2 text-sm font-medium text-white",
                isSubmitting ? "cursor-not-allowed bg-blue-400" : "bg-blue-600 hover:bg-blue-700",
              )}
            >
              {isSubmitting ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
