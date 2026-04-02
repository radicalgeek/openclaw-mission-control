import Link from "next/link";

type Props = {
  taskId: string;
  boardId: string;
  taskTitle?: string | null;
  taskStatus?: string | null;
};

const statusLabel = (status: string | null | undefined): string => {
  if (!status) return "Unknown";
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
};

export function LinkedTaskBadge({ taskId, boardId, taskTitle, taskStatus }: Props) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-[color:var(--accent)] bg-[color:var(--accent-soft)] px-3 py-2 text-sm"
      data-testid="linked-task-badge"
    >
      <span className="text-base leading-none">🔗</span>
      <span className="font-semibold text-[color:var(--accent-strong)]">
        {taskTitle ?? taskId}
      </span>
      {taskStatus ? (
        <span className="rounded-full bg-white/60 px-2 py-0.5 text-xs font-medium text-[color:var(--accent-strong)]">
          {statusLabel(taskStatus)}
        </span>
      ) : null}
      <Link
        href={`/boards/${boardId}?taskId=${taskId}`}
        className="ml-auto text-xs font-semibold text-[color:var(--accent)] hover:underline whitespace-nowrap"
      >
        View Task →
      </Link>
    </div>
  );
}
