export function formatSchedule(cfg: Record<string, number>): string {
  const parts = Object.entries(cfg).map(([unit, value]) => `${value} ${unit}`);
  return parts.length ? `every ${parts.join(', ')}` : '--';
}
