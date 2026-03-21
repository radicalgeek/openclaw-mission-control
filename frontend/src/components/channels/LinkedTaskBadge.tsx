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
      className="flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm"
      data-testid="linked-task-badge"
    >
      <span className="text-base leading-none">🔗</span>
      <span className="font-semibold text-blue-900">
        {taskTitle ?? taskId}
      </span>
      {taskStatus ? (
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
          {statusLabel(taskStatus)}
        </span>
      ) : null}
      <Link
        href={`/boards/${boardId}?taskId=${taskId}`}
        className="ml-auto text-xs font-semibold text-blue-600 hover:underline whitespace-nowrap"
      >
        View Task →
      </Link>
    </div>
  );
}
