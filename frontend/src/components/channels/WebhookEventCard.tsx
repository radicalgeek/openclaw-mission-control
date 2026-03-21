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
    border: "border-blue-300",
    bg: "bg-blue-50",
    icon: "ℹ️",
    label: "Info",
  },
  warning: {
    border: "border-amber-300",
    bg: "bg-amber-50",
    icon: "⚠️",
    label: "Warning",
  },
  error: {
    border: "border-red-300",
    bg: "bg-red-50",
    icon: "❌",
    label: "Error",
  },
  critical: {
    border: "border-red-500",
    bg: "bg-red-100",
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

  // Metadata rows: exclude url (shown as link) and severity (shown via colour)
  const metaRows = Object.entries(meta).filter(
    ([key]) => key !== "url" && key !== "severity",
  );

  return (
    <div
      className={cn(
        "rounded-xl border-l-4 p-3 text-sm",
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
          <p className="font-semibold text-slate-900 break-words">
            {title ?? message.content}
          </p>
          {title && message.content && message.content !== title ? (
            <p className="mt-1 text-xs text-slate-700 break-words">
              {message.content}
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
                  <div key={key} className="flex flex-wrap gap-x-2 text-xs text-slate-700">
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
              className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline"
            >
              View →
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}
