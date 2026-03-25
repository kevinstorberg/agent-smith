import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { HarnessItem } from '../api';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
};

export function HarnessIndexPage({ type }: { type: string }) {
  const [items, setItems] = useState<HarnessItem[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    api.harness.items.list(type).then(setItems).finally(() => setLoading(false));
  }, [type]);

  const toggleEnabled = async (item: HarnessItem) => {
    await api.harness.items.updateMetadata(type, item.id, { enabled: !item.enabled });
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, enabled: !i.enabled } : i));
  };

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>{TYPE_LABELS[type] || type}</h2>
        <button className="btn btn-primary" onClick={() => navigate(`/harness/${type}/new`)}>
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Enabled</th>
            <th>Agents</th>
            <th>Version</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => (
            <tr key={item.id} onClick={() => navigate(`/harness/${type}/${item.id}`)} style={{ cursor: 'pointer' }}>
              <td>
                {item.name}
                {item.name === '_main' && <span className="tag" style={{ marginLeft: 8 }}>Preamble</span>}
              </td>
              <td onClick={e => e.stopPropagation()}>
                <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    onChange={() => toggleEnabled(item)}
                    style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
                  />
                  <span style={{ color: item.enabled ? 'var(--success)' : 'var(--text-muted)', fontSize: 12 }}>
                    {item.enabled ? 'On' : 'Off'}
                  </span>
                </label>
              </td>
              <td>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {item.agents.map(a => (
                    <span key={a} className="tag">{a}</span>
                  ))}
                </div>
              </td>
              <td style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>v{item.version}</td>
              <td style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                {new Date(item.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={5} className="loading">No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
