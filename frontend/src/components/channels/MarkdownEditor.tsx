"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import {
  Bold,
  Code,
  Italic,
  Link,
  List,
  ListOrdered,
  Quote,
  Eye,
  Pencil,
} from "lucide-react";

import { cn } from "@/lib/utils";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  rows?: number;
  className?: string;
};

type ToolbarAction = {
  icon: React.ReactNode;
  title: string;
  fn: (textarea: HTMLTextAreaElement, value: string) => { next: string; cursor: [number, number] };
};

function wrapInline(
  textarea: HTMLTextAreaElement,
  value: string,
  before: string,
  after: string,
  placeholder: string,
): { next: string; cursor: [number, number] } {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = value.slice(start, end) || placeholder;
  const next = value.slice(0, start) + before + selected + after + value.slice(end);
  return { next, cursor: [start + before.length, start + before.length + selected.length] };
}

function prefixLines(
  textarea: HTMLTextAreaElement,
  value: string,
  prefix: string,
): { next: string; cursor: [number, number] } {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lineEnd = value.indexOf("\n", end);
  const regionEnd = lineEnd === -1 ? value.length : lineEnd;
  const lines = value.slice(lineStart, regionEnd).split("\n");
  const replaced = lines.map((l) => prefix + l).join("\n");
  const next = value.slice(0, lineStart) + replaced + value.slice(regionEnd);
  const newEnd = lineStart + replaced.length;
  return { next, cursor: [lineStart, newEnd] };
}

const ACTIONS: ToolbarAction[] = [
  {
    icon: <Bold className="h-3.5 w-3.5" />,
    title: "Bold (Ctrl+B)",
    fn: (ta, v) => wrapInline(ta, v, "**", "**", "bold text"),
  },
  {
    icon: <Italic className="h-3.5 w-3.5" />,
    title: "Italic (Ctrl+I)",
    fn: (ta, v) => wrapInline(ta, v, "*", "*", "italic text"),
  },
  {
    icon: <Code className="h-3.5 w-3.5" />,
    title: "Code",
    fn: (ta, v) => {
      const sel = v.slice(ta.selectionStart, ta.selectionEnd);
      if (sel.includes("\n")) {
        return wrapInline(ta, v, "```\n", "\n```", "code");
      }
      return wrapInline(ta, v, "`", "`", "code");
    },
  },
  {
    icon: <Link className="h-3.5 w-3.5" />,
    title: "Link",
    fn: (ta, v) => {
      const sel = v.slice(ta.selectionStart, ta.selectionEnd);
      const label = sel || "link text";
      const result = wrapInline(ta, v, "[", "](url)", label);
      // place cursor on "url"
      const pos = result.cursor[1] + 2; // after "]("
      return { next: result.next, cursor: [pos, pos + 3] };
    },
  },
  {
    icon: <Quote className="h-3.5 w-3.5" />,
    title: "Blockquote",
    fn: (ta, v) => prefixLines(ta, v, "> "),
  },
  {
    icon: <List className="h-3.5 w-3.5" />,
    title: "Bullet list",
    fn: (ta, v) => prefixLines(ta, v, "- "),
  },
  {
    icon: <ListOrdered className="h-3.5 w-3.5" />,
    title: "Numbered list",
    fn: (ta, v) => prefixLines(ta, v, "1. "),
  },
];

export function MarkdownEditor({
  value,
  onChange,
  onKeyDown,
  placeholder = "Write a message… (markdown supported)",
  rows = 6,
  className,
}: Props) {
  const [mode, setMode] = useState<"write" | "preview">("write");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const applyAction = (action: ToolbarAction) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const { next, cursor } = action.fn(ta, value);
    onChange(next);
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(cursor[0], cursor[1]);
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.ctrlKey && e.key === "b") {
      e.preventDefault();
      applyAction(ACTIONS[0]);
      return;
    }
    if (e.ctrlKey && e.key === "i") {
      e.preventDefault();
      applyAction(ACTIONS[1]);
      return;
    }
    onKeyDown?.(e);
  };

  return (
    <div className={cn("flex flex-col", className)}>
      {/* Toolbar */}
      <div className="flex items-center gap-0.5 border-b border-slate-100 px-1 py-1">
        {/* Write / Preview tabs */}
        <button
          type="button"
          onClick={() => setMode("write")}
          className={cn(
            "flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
            mode === "write"
              ? "bg-slate-100 text-slate-800"
              : "text-slate-400 hover:text-slate-600",
          )}
        >
          <Pencil className="h-3 w-3" />
          Write
        </button>
        <button
          type="button"
          onClick={() => setMode("preview")}
          className={cn(
            "flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors",
            mode === "preview"
              ? "bg-slate-100 text-slate-800"
              : "text-slate-400 hover:text-slate-600",
          )}
        >
          <Eye className="h-3 w-3" />
          Preview
        </button>

        <div className="mx-1 h-4 w-px bg-slate-200" />

        {/* Format buttons — only shown in write mode */}
        {mode === "write" &&
          ACTIONS.map((action) => (
            <button
              key={action.title}
              type="button"
              title={action.title}
              onClick={() => applyAction(action)}
              className="rounded p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              {action.icon}
            </button>
          ))}
      </div>

      {/* Editor / Preview */}
      {mode === "write" ? (
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={rows}
          className="w-full resize-none border-0 p-3 text-sm text-slate-700 placeholder-slate-400 outline-none focus:outline-none"
        />
      ) : (
        <div className="min-h-[96px] p-3">
          {value.trim() ? (
            <div className="prose prose-sm max-w-none text-slate-700">
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                {value}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-slate-400 italic">Nothing to preview yet.</p>
          )}
        </div>
      )}
    </div>
  );
}
