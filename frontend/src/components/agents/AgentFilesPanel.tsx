"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteAgentFile,
  getAgentFile,
  listAgentFiles,
  setAgentFile,
  type AgentFileContent,
  type AgentFileEntry,
} from "@/api/agentFiles";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Markdown } from "@/components/atoms/Markdown";

interface AgentFilesPanelProps {
  agentId: string;
  isAdmin: boolean;
}

const MARKDOWN_FILES = new Set([
  "IDENTITY.md",
  "SOUL.md",
  "TOOLS.md",
  "USER.md",
  "BOOTSTRAP.md",
  "HEARTBEAT.md",
  "MEMORY.md",
  "AGENTS.md",
  "DELIVERY_STATUS.md",
]);

export function AgentFilesPanel({ agentId, isAdmin }: AgentFilesPanelProps) {
  const [files, setFiles] = useState<AgentFileEntry[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<AgentFileContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentError, setContentError] = useState<string | null>(null);

  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState("");
  const [rawMode, setRawMode] = useState(false);
  const [resetSession, setResetSession] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const loadFiles = useCallback(async () => {
    if (!agentId) return;
    setFilesLoading(true);
    setFilesError(null);
    try {
      const resp = await listAgentFiles(agentId);
      setFiles(resp.data.files);
    } catch (err) {
      setFilesError(err instanceof Error ? err.message : "Failed to load files.");
    } finally {
      setFilesLoading(false);
    }
  }, [agentId]);

  const loadFile = useCallback(
    async (name: string) => {
      setContentLoading(true);
      setContentError(null);
      setEditMode(false);
      setSaveError(null);
      setSaveSuccess(false);
      setDeleteError(null);
      setConfirmDelete(false);
      try {
        const resp = await getAgentFile(agentId, name);
        setFileContent(resp.data);
        setEditText(resp.data.content);
      } catch (err) {
        setContentError(err instanceof Error ? err.message : "Failed to load file.");
        setFileContent(null);
      } finally {
        setContentLoading(false);
      }
    },
    [agentId],
  );

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const handleSelectFile = (name: string) => {
    setSelectedFile(name);
    void loadFile(name);
  };

  const handleSave = async () => {
    if (!selectedFile) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const resp = await setAgentFile(
        agentId,
        selectedFile,
        { content: editText },
        resetSession,
      );
      setFileContent(resp.data);
      setEditText(resp.data.content);
      setEditMode(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save file.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedFile) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteAgentFile(agentId, selectedFile);
      setSelectedFile(null);
      setFileContent(null);
      setEditMode(false);
      setConfirmDelete(false);
      await loadFiles();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete file.");
    } finally {
      setDeleting(false);
    }
  };

  const isMarkdown = selectedFile ? MARKDOWN_FILES.has(selectedFile) : false;

  return (
    <div className="flex h-full min-h-[400px] overflow-hidden rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)]">
      {/* File list */}
      <div className="w-48 shrink-0 overflow-y-auto border-r border-[color:var(--border)] bg-[color:var(--surface-muted)]">
        <div className="border-b border-[color:var(--border)] px-3 py-3">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-quiet">
            Files
          </p>
        </div>
        {filesLoading ? (
          <div className="px-3 py-4 text-xs text-muted">Loading…</div>
        ) : filesError ? (
          <div className="px-3 py-4 text-xs text-rose-600">{filesError}</div>
        ) : files.length === 0 ? (
          <div className="px-3 py-4 text-xs text-muted">No files found.</div>
        ) : (
          <ul className="divide-y divide-[color:var(--border)]">
            {files.map((file) => (
              <li key={file.name}>
                <button
                  type="button"
                  onClick={() => handleSelectFile(file.name)}
                  className={`w-full px-3 py-2.5 text-left text-xs transition ${
                    selectedFile === file.name
                      ? "bg-[color:var(--accent)] font-semibold text-white"
                      : "text-muted hover:bg-[color:var(--surface-strong)] hover:text-strong"
                  } ${file.missing ? "opacity-50" : ""}`}
                >
                  {file.name}
                  {file.missing ? (
                    <span className="ml-1 text-[10px] opacity-70">(missing)</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="px-3 py-2">
          <button
            type="button"
            onClick={loadFiles}
            className="w-full rounded border border-dashed border-[color:var(--border-strong)] py-1 text-[10px] text-quiet transition hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* File content pane */}
      <div className="flex min-w-0 flex-1 flex-col">
        {!selectedFile ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted">
            Select a file to view.
          </div>
        ) : contentLoading ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted">
            Loading…
          </div>
        ) : contentError ? (
          <div className="flex flex-1 items-center justify-center px-6 text-sm text-rose-600">
            {contentError}
          </div>
        ) : fileContent ? (
          <>
            {/* Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border)] px-4 py-2">
              <span className="text-xs font-semibold text-strong">
                {selectedFile}
              </span>
              <div className="flex flex-wrap items-center gap-2">
                {isMarkdown && !editMode && (
                  <button
                    type="button"
                    onClick={() => setRawMode((v) => !v)}
                    className="text-xs text-muted underline hover:text-strong"
                  >
                    {rawMode ? "Rendered" : "Raw"}
                  </button>
                )}
                {isAdmin && !editMode && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setEditText(fileContent.content);
                      setEditMode(true);
                    }}
                  >
                    Edit
                  </Button>
                )}
                {isAdmin && !editMode && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="border-rose-200 text-rose-600 hover:border-rose-300 hover:text-rose-700"
                    onClick={() => setConfirmDelete(true)}
                    disabled={deleting}
                  >
                    Delete
                  </Button>
                )}
              </div>
            </div>

            {/* Content area */}
            <div className="flex-1 overflow-y-auto p-4">
              {editMode ? (
                <div className="flex h-full flex-col gap-3">
                  <Textarea
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    className="flex-1 resize-none font-mono text-xs"
                    rows={18}
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
                      <input
                        type="checkbox"
                        checked={resetSession}
                        onChange={(e) => setResetSession(e.target.checked)}
                        className="rounded"
                      />
                      Reset agent session after save
                    </label>
                    <div className="ml-auto flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setEditMode(false);
                          setSaveError(null);
                        }}
                        disabled={saving}
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleSave}
                        disabled={saving}
                      >
                        {saving ? "Saving…" : "Save"}
                      </Button>
                    </div>
                  </div>
                  {saveError ? (
                    <p className="text-xs text-rose-600">{saveError}</p>
                  ) : null}
                </div>
              ) : isMarkdown && !rawMode ? (
                <div className="prose prose-sm max-w-none text-slate-700">
                  <Markdown content={fileContent.content} variant="description" />
                </div>
              ) : (
                <pre className="whitespace-pre-wrap break-words font-mono text-xs text-slate-700">
                  {fileContent.content}
                </pre>
              )}
            </div>

            {/* Status messages below content pane */}
            {saveSuccess ? (
              <div className="border-t border-[color:var(--border)] bg-emerald-50 px-4 py-2 text-xs font-medium text-emerald-700">
                ✓ File saved successfully.
              </div>
            ) : null}

            {/* Delete confirm */}
            {confirmDelete ? (
              <div className="border-t border-[color:var(--border)] bg-rose-50 px-4 py-3">
                <p className="text-xs font-medium text-rose-700">
                  Delete <strong>{selectedFile}</strong>? This cannot be undone.
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
                    {deleting ? "Deleting…" : "Yes, delete"}
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
          </>
        ) : null}
      </div>
    </div>
  );
}
