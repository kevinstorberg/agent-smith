import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api } from '../api';
import type { EvalSuite } from '../api';

export function EvalSuitesPage() {
  const navigate = useNavigate();
  const [suites, setSuites] = useState<EvalSuite[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.evalConfigs.suites
      .list({ enabled_only: 'false' })
      .then(res => {
        setSuites(res.items);
        setTotal(res.total);
      })
      .finally(() => setLoading(false));
  }, []);

  const toggleEnabled = async (suite: EvalSuite) => {
    await api.evalConfigs.suites.update(suite.id, { enabled: !suite.enabled });
    setSuites(prev =>
      prev.map(s => (s.id === suite.id ? { ...s, enabled: !s.enabled } : s)),
    );
  };

  return (
    <div>
      <div className="page-header">
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Evals</h2>
        <button className="btn btn-primary" onClick={() => navigate('/eval-configs/new')}>
          + New Suite
        </button>
      </div>

      {loading && <div className="loading">Loading...</div>}

      {!loading && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Scenarios</th>
              <th>Enabled</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {suites.map(suite => (
              <tr
                key={suite.id}
                style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/eval-configs/${suite.id}`)}
              >
                <td style={{ fontWeight: 500 }}>{suite.name}</td>
                <td>
                  <span className="tag">{suite.eval_type} / {suite.subcategory}</span>
                </td>
                <td>{suite.scenario_count ?? '—'}</td>
                <td onClick={e => e.stopPropagation()}>
                  <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input
                      type="checkbox"
                      checked={suite.enabled}
                      onChange={() => toggleEnabled(suite)}
                      style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
                    />
                    <span style={{ color: suite.enabled ? 'var(--success)' : 'var(--text-muted)', fontSize: 12 }}>
                      {suite.enabled ? 'On' : 'Off'}
                    </span>
                  </label>
                </td>
                <td style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                  {new Date(suite.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </td>
                <td onClick={e => e.stopPropagation()}>
                  <a
                    onClick={() => navigate(`/evals?category=${suite.eval_type}&subcategory=${suite.subcategory}`)}
                    style={{ color: 'var(--info)', cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap' }}
                  >
                    Results &rarr;
                  </a>
                </td>
              </tr>
            ))}
            {suites.length === 0 && (
              <tr>
                <td colSpan={6} className="loading">
                  No eval suites found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <p style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 8 }}>
        {total} suite{total !== 1 ? 's' : ''}
      </p>
    </div>
  );
}
