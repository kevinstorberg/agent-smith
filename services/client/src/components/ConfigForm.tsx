import { ALL_AGENTS, toggleArrayItem, isValidRepo } from '../constants';

interface ConfigFormProps {
  title?: string;
  device: string;
  repo: string;
  agents: string[];
  subagents: string[];
  enabled: boolean;
  exclude: boolean;
  saving: boolean;
  onDeviceChange: (v: string) => void;
  onRepoChange: (v: string) => void;
  onAgentsChange: (v: string[]) => void;
  onSubagentsChange: (v: string[]) => void;
  onEnabledChange: (v: boolean) => void;
  onExcludeChange: (v: boolean) => void;
  onSave: () => void;
  onCancel: () => void;
  submitLabel?: string;
}

export function ConfigForm({
  title,
  device, repo, agents, subagents, enabled, exclude, saving,
  onDeviceChange, onRepoChange, onAgentsChange, onSubagentsChange, onEnabledChange, onExcludeChange,
  onSave, onCancel,
  submitLabel = 'Save',
}: ConfigFormProps) {
  const toggleAgent = (agent: string) => onAgentsChange(toggleArrayItem(agents, agent));
  const toggleSubagent = (agent: string) => onSubagentsChange(toggleArrayItem(subagents, agent));

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 14, marginBottom: 8 }}>
      {title && <div style={{ fontSize: 'var(--font-base)', fontWeight: 600, marginBottom: 10 }}>{title}</div>}
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 180px' }}>
          <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 4 }}>Device</label>
          <input style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '6px 10px', fontSize: 'var(--font-base)', fontFamily: 'var(--font)', width: '100%' }} value={device} onChange={e => onDeviceChange(e.target.value)} placeholder="* = all devices" />
        </div>
        <div style={{ flex: '2 1 280px' }}>
          <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 4 }}>Repo</label>
          <input style={{ background: 'var(--bg)', border: `1px solid ${isValidRepo(repo) ? 'var(--border)' : 'var(--highlight)'}`, borderRadius: 'var(--radius)', color: 'var(--text)', padding: '6px 10px', fontSize: 'var(--font-base)', fontFamily: 'var(--mono)', width: '100%' }} value={repo} onChange={e => onRepoChange(e.target.value)} placeholder="* = global, or /absolute/path" />
          {!isValidRepo(repo) && <span style={{ fontSize: 'var(--font-xs)', color: 'var(--highlight)', marginTop: 2, display: 'block' }}>Must be * or an absolute path</span>}
        </div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 }}>Agents</label>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          {ALL_AGENTS.map(a => (
            <label key={a} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 'var(--font-base)' }}>
              <input type="checkbox" checked={agents.includes(a)} onChange={() => toggleAgent(a)} style={{ accentColor: 'var(--highlight)', width: 14, height: 14 }} />
              {a}
            </label>
          ))}
        </div>
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 }}>Subagents (optional)</label>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          {ALL_AGENTS.map(a => (
            <label key={a} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 'var(--font-base)' }}>
              <input type="checkbox" checked={subagents.includes(a)} onChange={() => toggleSubagent(a)} style={{ accentColor: 'var(--warning)', width: 14, height: 14 }} />
              {a}
            </label>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 'var(--font-base)' }}>
          <input type="checkbox" checked={enabled} onChange={() => onEnabledChange(!enabled)} style={{ accentColor: 'var(--success)', width: 14, height: 14 }} />
          Enabled
        </label>
        <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-sm)' }}>|</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 'var(--font-base)' }}>
          <input type="radio" name="cfgMode" checked={!exclude} onChange={() => onExcludeChange(false)} style={{ accentColor: 'var(--success)', width: 14, height: 14 }} />
          Include
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 'var(--font-base)' }}>
          <input type="radio" name="cfgMode" checked={exclude} onChange={() => onExcludeChange(true)} style={{ accentColor: 'var(--highlight)', width: 14, height: 14 }} />
          Exclude
        </label>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn-sm" onClick={onSave} disabled={saving || !isValidRepo(repo)}>{saving ? 'Saving...' : submitLabel}</button>
        <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
