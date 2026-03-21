"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ChannelRead } from "@/api/channels";

type Props = {
  channel: ChannelRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Called with topic and content (first message).
   * Content is required by the backend.
   */
  onCreate: (topic: string, content: string) => Promise<void>;
  isCreating?: boolean;
  error?: string | null;
};

export function NewThreadModal({
  channel,
  open,
  onOpenChange,
  onCreate,
  isCreating = false,
  error = null,
}: Props) {
  const [topic, setTopic] = useState("");
  const [content, setContent] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const handleCreate = async () => {
    const trimmedTopic = topic.trim();
    if (!trimmedTopic) {
      setLocalError("A topic is required.");
      return;
    }
    const trimmedContent = content.trim();
    if (!trimmedContent) {
      setLocalError("A first message is required.");
      return;
    }
    setLocalError(null);
    await onCreate(trimmedTopic, trimmedContent);
    setTopic("");
    setContent("");
  };

  const displayError = localError ?? error;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isCreating) {
          onOpenChange(next);
          if (!next) {
            setTopic("");
            setContent("");
            setLocalError(null);
          }
        }
      }}
    >
      <DialogContent aria-label="New thread">
        <DialogHeader>
          <DialogTitle>New thread</DialogTitle>
          <DialogDescription>
            Start a new discussion thread in{" "}
            <span className="font-semibold">#{channel.name}</span>.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Topic <span className="text-rose-600">*</span>
            </label>
            <Input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What is this thread about?"
              disabled={isCreating}
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              First message <span className="text-rose-600">*</span>
            </label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Add context or details…"
              className="min-h-[100px]"
              disabled={isCreating}
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.ctrlKey) {
                  e.preventDefault();
                  void handleCreate();
                }
              }}
            />
          </div>
          {displayError ? (
            <p className="text-xs text-rose-600">{displayError}</p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isCreating}
          >
            Cancel
          </Button>
          <Button onClick={() => void handleCreate()} disabled={isCreating}>
            {isCreating ? "Creating…" : "Create thread"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
