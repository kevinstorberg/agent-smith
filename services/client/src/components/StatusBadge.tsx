// One home for status-badge coloring. Per-domain maps (not one merged map) so a
// future status name in one domain can never silently collide with another's.
const PLAN_STATUS_COLORS: Record<string, string> = {
  draft: 'var(--info, #3498db)',
  // final -> default tag styling
};

const PROPOSAL_STATUS_COLORS: Record<string, string> = {
  pending: 'var(--info, #3498db)',
  approved: 'var(--success, #2ecc71)',
  rejected: 'var(--text-muted)',
};

const MAPS = { plan: PLAN_STATUS_COLORS, proposal: PROPOSAL_STATUS_COLORS };

export function StatusBadge({ status, kind }: { status: string; kind: keyof typeof MAPS }) {
  const color = MAPS[kind][status];
  return (
    <span className="tag" style={color ? { color, borderColor: color } : undefined}>
      {status}
    </span>
  );
}
