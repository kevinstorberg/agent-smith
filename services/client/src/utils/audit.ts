/** Human-readable duration for an audit event; em dash when not yet completed. */
export function formatDuration(ms: number | null): string {
  return ms == null ? '—' : `${ms} ms`;
}
