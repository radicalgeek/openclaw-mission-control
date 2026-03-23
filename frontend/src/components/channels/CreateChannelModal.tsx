"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: { name: string; channel_type: "discussion" | "alert"; description: string }) => Promise<void>;
};

export function CreateChannelModal({ isOpen, onClose, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [channelType, setChannelType] = useState<"discussion" | "alert">("discussion");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      await onSubmit({ name: name.trim(), channel_type: channelType, description: description.trim() });
      // Reset on success
      setName("");
      setChannelType("discussion");
      setDescription("");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create channel");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Create Channel</h2>
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
            <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="channel-name" className="mb-1 block text-sm font-medium text-slate-700">
              Channel Name
            </label>
            <input
              id="channel-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. deployment-alerts"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">
              Channel Type
            </label>
            <div className="space-y-2">
              <label className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 cursor-pointer hover:bg-slate-50">
                <input
                  type="radio"
                  name="channel-type"
                  value="discussion"
                  checked={channelType === "discussion"}
                  onChange={() => setChannelType("discussion")}
                  className="mt-0.5"
                  disabled={isSubmitting}
                />
                <div>
                  <p className="text-sm font-medium text-slate-900">Discussion</p>
                  <p className="text-xs text-slate-500">For team conversations and collaboration</p>
                </div>
              </label>
              <label className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 cursor-pointer hover:bg-slate-50">
                <input
                  type="radio"
                  name="channel-type"
                  value="alert"
                  checked={channelType === "alert"}
                  onChange={() => setChannelType("alert")}
                  className="mt-0.5"
                  disabled={isSubmitting}
                />
                <div>
                  <p className="text-sm font-medium text-slate-900">Alert</p>
                  <p className="text-xs text-slate-500">For automated notifications and webhooks</p>
                </div>
              </label>
            </div>
          </div>

          <div>
            <label htmlFor="channel-description" className="mb-1 block text-sm font-medium text-slate-700">
              Description (optional)
            </label>
            <textarea
              id="channel-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this channel for?"
              rows={2}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={isSubmitting}
            />
          </div>

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
                isSubmitting
                  ? "bg-blue-400 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-700"
              )}
            >
              {isSubmitting ? "Creating..." : "Create Channel"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
