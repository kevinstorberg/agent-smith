import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { HarnessItem } from '../api';
import { Pagination } from '../components/Pagination';

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rules',
  skill: 'Skills',
  tool: 'Tools',
  hook: 'Hooks',
};

export function HarnessIndexPage({ type }: { type: string }) {
  const [items, setItems] = useState<HarnessItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [projectFilter, setProjectFilter] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    setOffset(0);
  }, [type]);

  useEffect(() => {
    setLoading(true);
    api.harness.items.list(type, { limit, offset }).then(res => {
      setItems(res.items);
      setTotal(res.total);
    }).finally(() => setLoading(false));
  }, [type, limit, offset]);

  const toggleEnabled = async (item: HarnessItem) => {
    await api.harness.items.updateMetadata(type, item.id, { enabled: !item.enabled });
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, enabled: !i.enabled } : i));
  };

  const displayed = items.filter(i => {
    if (nameFilter && !i.name.toLowerCase().includes(nameFilter.toLowerCase())) return false;
    if (projectFilter) {
      const pf = projectFilter.toLowerCase();
      if (!(i.project?.toLowerCase().includes(pf) || (!i.project && pf === 'shared'))) return false;
    }
    return true;
  });

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>{TYPE_LABELS[type] || type}</h2>
        <button className="btn btn-primary" onClick={() => navigate(`/harness/${type}/new`)}>
          + New {type.charAt(0).toUpperCase() + type.slice(1)}
        </button>
      </div>

      <div className="filters" style={{ marginBottom: 12 }}>
        <input
          placeholder="Search by name..."
          value={nameFilter}
          onChange={e => setNameFilter(e.target.value)}
          style={{ maxWidth: 260 }}
        />
        <input
          placeholder="Filter by project..."
          value={projectFilter}
          onChange={e => setProjectFilter(e.target.value)}
          style={{ maxWidth: 220 }}
        />
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Project</th>
            <th>Enabled</th>
            <th>Agents</th>
            <th>Version</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map(item => (
            <tr key={item.id} onClick={() => navigate(`/harness/${type}/${item.id}`)} style={{ cursor: 'pointer' }}>
              <td>
                {item.name}
                {item.name === '_main' && <span className="tag" style={{ marginLeft: 8 }}>Preamble</span>}
              </td>
              <td>
                {item.project
                  ? <span className="tag tag-project">{item.project}</span>
                  : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>shared</span>
                }
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
          {displayed.length === 0 && (
            <tr><td colSpan={6} className="loading">No {TYPE_LABELS[type]?.toLowerCase() || 'items'} found</td></tr>
          )}
        </tbody>
      </table>

      <Pagination
        total={total}
        limit={limit}
        offset={offset}
        onPageChange={setOffset}
        onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
      />
    </div>
  );
}
