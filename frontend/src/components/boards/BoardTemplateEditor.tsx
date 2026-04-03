"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteBoardTemplate,
  getBoardTemplate,
  listBoardTemplates,
  previewBoardTemplate,
  upsertBoardTemplate,
  type BoardTemplateRead,
  type TemplateSource,
} from "@/api/boardTemplates";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

interface BoardTemplateEditorProps {
  boardId: string;
}

const FILE_NAMES = [
  "IDENTITY.md",
  "SOUL.md",
  "TOOLS.md",
  "USER.md",
  "BOOTSTRAP.md",
  "HEARTBEAT.md",
  "MEMORY.md",
  "AGENTS.md",
] as const;

const SOURCE_LABELS: Record<TemplateSource, string> = {
  board: "Board override",
  org: "Org-wide override",
  "built-in": "Built-in default",
};

const SOURCE_BADGE_CLASSES: Record<TemplateSource, string> = {
  board:
    "bg-violet-100 text-violet-700 border border-violet-200",
  org: "bg-blue-100 text-blue-700 border border-blue-200",
  "built-in": "bg-slate-100 text-slate-600 border border-slate-200",
};

const JINJA_CONTEXT_VARS = [
  { name: "agent_name", description: "Agent name" },
  { name: "board_name", description: "Board name" },
  { name: "user_name", description: "User display name" },
  { name: "user_email", description: "User email" },
  { name: "role", description: "Agent role / identity profile role" },
  { name: "board_goal", description: "Board goal / description" },
  { name: "today", description: "Today's date (UTC)" },
];

export function BoardTemplateEditor({ boardId }: BoardTemplateEditorProps) {
  const [overrides, setOverrides] = useState<Map<string, BoardTemplateRead>>(
    new Map(),
  );
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [isDirty, setIsDirty] = useState(false);

  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [agentIdForPreview, setAgentIdForPreview] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [showVarRef, setShowVarRef] = useState(false);

  const loadTemplates = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const resp = await listBoardTemplates(boardId);
      const map = new Map<string, BoardTemplateRead>();
      for (const t of resp.data) {
        map.set(t.file_name, t);
      }
      setOverrides(map);
    } catch (err) {
      setListError(
        err instanceof Error ? err.message : "Failed to load templates.",
      );
    } finally {
      setListLoading(false);
    }
  }, [boardId]);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const handleSelectFile = useCallback(
    async (name: string) => {
      setSelectedFile(name);
      setPreviewText(null);
      setPreviewError(null);
      setSaveError(null);
      setSaveSuccess(false);
      setDeleteError(null);
      setConfirmDelete(false);
      setIsDirty(false);

      const existing = overrides.get(name);
      if (existing) {
        setEditText(existing.template_content);
      } else {
        // Try fetching (will return 404 → built-in)
        try {
          const resp = await getBoardTemplate(boardId, name);
          setEditText(resp.data.template_content);
        } catch {
          setEditText("");
        }
      }
    },
    [boardId, overrides],
  );

  const handleTextChange = (value: string) => {
    setEditText(value);
    setIsDirty(true);
  };

  const handlePreview = async () => {
    if (!selectedFile) return;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewText(null);
    try {
      const resp = await previewBoardTemplate(boardId, selectedFile, {
        template_content: editText,
        agent_id: agentIdForPreview.trim() || null,
      });
      setPreviewText(resp.data.rendered);
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : "Preview failed.",
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedFile) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const resp = await upsertBoardTemplate(boardId, selectedFile, {
        template_content: editText,
      });
      setOverrides((prev) => {
        const next = new Map(prev);
        next.set(selectedFile, resp.data);
        return next;
      });
      setIsDirty(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save template.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedFile) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteBoardTemplate(boardId, selectedFile);
      setOverrides((prev) => {
        const next = new Map(prev);
        next.delete(selectedFile);
        return next;
      });
      setEditText("");
      setIsDirty(false);
      setConfirmDelete(false);
      setPreviewText(null);
    } catch (err) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete template.",
      );
    } finally {
      setDeleting(false);
    }
  };

  const currentSource: TemplateSource =
    overrides.get(selectedFile ?? "")?.source ?? "built-in";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-strong">
            Board template overrides
          </p>
          <p className="text-xs text-muted">
            Customise the Jinja2 templates written to agent workspaces on this
            board. Higher priority than org-wide defaults.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowVarRef((v) => !v)}
          className="text-xs text-muted underline hover:text-strong"
        >
          {showVarRef ? "Hide" : "Show"} template variables
        </button>
      </div>

      {/* Variable reference */}
      {showVarRef ? (
        <div className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
            Available Jinja2 context variables
          </p>
          <dl className="grid gap-1.5 text-xs sm:grid-cols-2">
            {JINJA_CONTEXT_VARS.map((v) => (
              <div key={v.name} className="flex items-start gap-2">
                <dt className="shrink-0 font-mono text-[color:var(--accent)]">
                  {`{{ ${v.name} }}`}
                </dt>
                <dd className="text-muted">{v.description}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      {listError ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
          {listError}
        </div>
      ) : null}

      <div className="flex min-h-[440px] overflow-hidden rounded-xl border border-[color:var(--border)] bg-[color:var(--surface)]">
        {/* File list */}
        <div className="w-44 shrink-0 overflow-y-auto border-r border-[color:var(--border)] bg-[color:var(--surface-muted)]">
          <div className="border-b border-[color:var(--border)] px-3 py-3">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
              Templates
            </p>
          </div>
          {listLoading ? (
            <div className="px-3 py-4 text-xs text-muted">Loading…</div>
          ) : (
            <ul className="divide-y divide-[color:var(--border)]">
              {FILE_NAMES.map((name) => {
                const hasOverride = overrides.has(name);
                const src: TemplateSource =
                  overrides.get(name)?.source ?? "built-in";
                return (
                  <li key={name}>
                    <button
                      type="button"
                      onClick={() => void handleSelectFile(name)}
                      className={`w-full px-3 py-2.5 text-left text-xs transition ${
                        selectedFile === name
                          ? "bg-[color:var(--accent)] font-semibold text-white"
                          : "text-muted hover:bg-[color:var(--surface-strong)] hover:text-strong"
                      }`}
                    >
                      <span className="block truncate">{name}</span>
                      {hasOverride ? (
                        <span
                          className={`mt-0.5 inline-block rounded px-1 py-0.5 text-[9px] font-semibold uppercase ${
                            selectedFile === name
                              ? "bg-white/20 text-white"
                              : SOURCE_BADGE_CLASSES[src]
                          }`}
                        >
                          {src === "board" ? "board" : "org"}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Editor pane */}
        <div className="flex min-w-0 flex-1 flex-col">
          {!selectedFile ? (
            <div className="flex flex-1 items-center justify-center text-sm text-muted">
              Select a template to edit.
            </div>
          ) : (
            <>
              {/* Toolbar */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border)] px-4 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-strong">
                    {selectedFile}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${SOURCE_BADGE_CLASSES[currentSource]}`}
                  >
                    {SOURCE_LABELS[currentSource]}
                  </span>
                  {isDirty ? (
                    <span className="text-[10px] font-semibold text-amber-600">
                      unsaved
                    </span>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  {overrides.has(selectedFile) ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="border-rose-200 text-rose-600 hover:border-rose-300 hover:text-rose-700"
                      onClick={() => setConfirmDelete(true)}
                      disabled={deleting}
                    >
                      Remove override
                    </Button>
                  ) : null}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleSave}
                    disabled={saving || !isDirty}
                  >
                    {saving ? "Saving…" : "Save"}
                  </Button>
                </div>
              </div>

              {/* Editor */}
              <div className="flex flex-1 flex-col gap-3 p-4">
                <Textarea
                  value={editText}
                  onChange={(e) => handleTextChange(e.target.value)}
                  className="flex-1 resize-none font-mono text-xs"
                  placeholder={`# Jinja2 template for ${selectedFile}\n# Use {{ variable_name }} for context variables`}
                  rows={14}
                />

                {/* Preview section */}
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-quiet">
                      Preview
                    </span>
                    <Input
                      value={agentIdForPreview}
                      onChange={(e) => setAgentIdForPreview(e.target.value)}
                      placeholder="Agent ID (optional, for real context)"
                      className="h-7 max-w-[260px] text-xs"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handlePreview}
                      disabled={previewLoading || !editText.trim()}
                    >
                      {previewLoading ? "Previewing…" : "Preview"}
                    </Button>
                  </div>
                  {previewError ? (
                    <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                      {previewError}
                    </div>
                  ) : previewText !== null ? (
                    <pre className="max-h-40 overflow-y-auto rounded-lg border border-[color:var(--border)] bg-[color:var(--surface-muted)] p-3 font-mono text-xs text-slate-700 whitespace-pre-wrap break-words">
                      {previewText}
                    </pre>
                  ) : null}
                </div>

                {saveError ? (
                  <p className="text-xs text-rose-600">{saveError}</p>
                ) : null}
                {saveSuccess ? (
                  <p className="text-xs font-medium text-emerald-600">
                    ✓ Template saved.
                  </p>
                ) : null}

                {confirmDelete ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 p-3">
                    <p className="text-xs font-medium text-rose-700">
                      Remove the board override for{" "}
                      <strong>{selectedFile}</strong>? The org-wide or built-in
                      template will be used instead.
                    </p>
                    {deleteError ? (
                      <p className="mt-1 text-xs text-rose-600">{deleteError}</p>
                    ) : null}
                    <div className="mt-2 flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-rose-200 text-rose-600 hover:border-rose-300"
                        onClick={handleDelete}
                        disabled={deleting}
                      >
                        {deleting ? "Removing…" : "Yes, remove"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setConfirmDelete(false)}
                        disabled={deleting}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
