import { type ThreadMessageRead, getMessageSeverity, type MessageSeverity } from "@/api/channels";
import { cn } from "@/lib/utils";

type Props = {
  message: ThreadMessageRead;
};

const SEVERITY_STYLES: Record<
  MessageSeverity,
  { border: string; bg: string; icon: string; label: string }
> = {
  info: {
    border: "border-blue-400",
    bg: "bg-[color:var(--surface-muted)]",
    icon: "ℹ️",
    label: "Info",
  },
  warning: {
    border: "border-amber-400",
    bg: "bg-[color:var(--surface-muted)]",
    icon: "⚠️",
    label: "Warning",
  },
  error: {
    border: "border-red-400",
    bg: "bg-[color:var(--surface-muted)]",
    icon: "❌",
    label: "Error",
  },
  critical: {
    border: "border-red-500",
    bg: "bg-[color:var(--surface-muted)]",
    icon: "🚨",
    label: "Critical",
  },
};

const humanizeKey = (key: string): string =>
  key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

export function WebhookEventCard({ message }: Props) {
  const severity = getMessageSeverity(message);
  const style = SEVERITY_STYLES[severity];
  const meta = message.event_metadata ?? {};

  // Extract known display fields from metadata
  const url =
    typeof meta.url === "string" ? meta.url : null;
  const title =
    typeof meta.title === "string"
      ? meta.title
      : typeof meta.event === "string"
        ? meta.event
        : null;
  const summary = typeof meta.summary === "string" ? meta.summary : null;

  // Metadata rows: exclude url (shown as link) and severity (shown via colour)
  const metaRows = Object.entries(meta).filter(
    ([key]) =>
      !["url", "severity", "raw", "title", "summary"].includes(key),
  );

  return (
    <div
      className={cn(
        "rounded-lg border border-l-4 p-3 text-sm shadow-sm",
        style.border,
        style.bg,
      )}
      data-testid="webhook-event-card"
      data-severity={severity}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-base leading-none" role="img" aria-label={style.label}>
          {style.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-[color:var(--text)] break-words">
            {title ?? message.content}
          </p>
          {summary ? (
            <p className="mt-1 text-xs text-[color:var(--text-muted)] break-words">
              {summary}
            </p>
          ) : null}
          {metaRows.length > 0 ? (
            <dl className="mt-2 space-y-1">
              {metaRows.map(([key, value]) => {
                const displayValue =
                  typeof value === "string" || typeof value === "number"
                    ? String(value)
                    : JSON.stringify(value);
                return (
                  <div
                    key={key}
                    className="flex flex-wrap gap-x-2 text-xs text-[color:var(--text-muted)]"
                  >
                    <dt className="font-semibold">{humanizeKey(key)}:</dt>
                    <dd className="break-all">{displayValue}</dd>
                  </div>
                );
              })}
            </dl>
          ) : null}
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-[color:var(--accent)] hover:underline"
            >
              View →
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}
