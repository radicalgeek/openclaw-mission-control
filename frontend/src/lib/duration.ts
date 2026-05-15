export function formatDurationMinutes(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "Not set";

  const totalMinutes = Math.max(0, Math.round(value));
  if (totalMinutes < 60) return `${totalMinutes}m`;

  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
}

export function durationMinutesTitle(value?: number | null): string | undefined {
  if (value == null || !Number.isFinite(value)) return undefined;
  const totalMinutes = Math.max(0, Math.round(value));
  return `${totalMinutes} minute${totalMinutes === 1 ? "" : "s"}`;
}
