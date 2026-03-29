import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { api } from '../api';
import type { EvalSuite, EvalScenario } from '../api';

export function EvalSuiteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isNew = id === 'new' || !id;

  const [suite, setSuite] = useState<Partial<EvalSuite>>({
    name: '',
    eval_type: '',
    subcategory: '',
    judge_prompt: '',
    items: {},
    config: {},
    enabled: true,
  });
  const [scenarios, setScenarios] = useState<EvalScenario[]>([]);
  const [itemsJson, setItemsJson] = useState('{}');
  const [configJson, setConfigJson] = useState('{}');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isNew) return;
    api.evalConfigs.suites.get(Number(id)).then(data => {
      setSuite(data);
      setScenarios(data.scenarios || []);
      setItemsJson(JSON.stringify(data.items, null, 2));
      setConfigJson(JSON.stringify(data.config, null, 2));
    });
  }, [id, isNew]);

  const save = async () => {
    setSaving(true);
    try {
      let parsedItems: Record<string, unknown>;
      let parsedConfig: Record<string, unknown>;
      try {
        parsedItems = JSON.parse(itemsJson);
      } catch {
        alert('Invalid JSON in Items field');
        return;
      }
      try {
        parsedConfig = JSON.parse(configJson);
      } catch {
        alert('Invalid JSON in Config field');
        return;
      }

      const body = {
        name: suite.name,
        eval_type: suite.eval_type,
        subcategory: suite.subcategory,
        judge_prompt: suite.judge_prompt,
        items: parsedItems,
        config: parsedConfig,
        enabled: suite.enabled,
      };

      if (isNew) {
        const created = await api.evalConfigs.suites.create(body);
        navigate(`/eval-configs/${created.id}`, { replace: true });
      } else {
        await api.evalConfigs.suites.update(Number(id), body);
        const updated = await api.evalConfigs.suites.get(Number(id));
        setSuite(updated);
      }
    } finally {
      setSaving(false);
    }
  };

  const deleteSuite = async () => {
    if (!confirm(`Delete suite "${suite.name}" and all its scenarios?`)) return;
    await api.evalConfigs.suites.remove(Number(id));
    navigate('/eval-configs');
  };

  const toggleScenario = async (sc: EvalScenario) => {
    await api.evalConfigs.scenarios.update(sc.id, { enabled: !sc.enabled });
    setScenarios(prev =>
      prev.map(s => (s.id === sc.id ? { ...s, enabled: !s.enabled } : s)),
    );
  };

  const deleteScenario = async (sc: EvalScenario) => {
    if (!confirm(`Delete scenario "${sc.name}"?`)) return;
    await api.evalConfigs.scenarios.remove(sc.id);
    setScenarios(prev => prev.filter(s => s.id !== sc.id));
  };

  const field = (label: string, key: keyof EvalSuite, type: 'text' | 'textarea' = 'text') => (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
        {label}
      </label>
      {type === 'textarea' ? (
        <textarea
          value={(suite[key] as string) || ''}
          onChange={e => setSuite(prev => ({ ...prev, [key]: e.target.value }))}
          rows={8}
          style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 13 }}
        />
      ) : (
        <input
          type="text"
          value={(suite[key] as string) || ''}
          onChange={e => setSuite(prev => ({ ...prev, [key]: e.target.value }))}
          style={{ width: '100%', fontSize: 13 }}
        />
      )}
    </div>
  );

  return (
    <div>
      <a
        onClick={() => navigate('/eval-configs')}
        style={{ color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13 }}
      >
        &larr; Back to Eval Configs
      </a>

      <h2 style={{ fontSize: 20, fontWeight: 600, margin: '16px 0' }}>
        {isNew ? 'New Suite' : suite.name}
      </h2>

      <div className="card" style={{ marginBottom: 24 }}>
        {field('Name', 'name')}

        <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              Eval Type
            </label>
            <input
              type="text"
              value={suite.eval_type || ''}
              onChange={e => setSuite(prev => ({ ...prev, eval_type: e.target.value }))}
              style={{ width: '100%', fontSize: 13 }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              Subcategory
            </label>
            <input
              type="text"
              value={suite.subcategory || ''}
              onChange={e => setSuite(prev => ({ ...prev, subcategory: e.target.value }))}
              style={{ width: '100%', fontSize: 13 }}
            />
          </div>
        </div>

        {field('Judge Prompt', 'judge_prompt', 'textarea')}

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
            Items (JSON)
          </label>
          <textarea
            value={itemsJson}
            onChange={e => setItemsJson(e.target.value)}
            rows={6}
            style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12 }}
          />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
            Config (JSON)
          </label>
          <textarea
            value={configJson}
            onChange={e => setConfigJson(e.target.value)}
            rows={4}
            style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12 }}
          />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13 }}>
            <input
              type="checkbox"
              checked={suite.enabled ?? true}
              onChange={e => setSuite(prev => ({ ...prev, enabled: e.target.checked }))}
              style={{ marginRight: 8 }}
            />
            Enabled
          </label>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={save}
            disabled={saving}
            style={{
              padding: '6px 20px',
              fontSize: 13,
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
            }}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          {!isNew && (
            <button
              onClick={deleteSuite}
              style={{
                padding: '6px 16px',
                fontSize: 13,
                background: 'transparent',
                color: 'var(--highlight)',
                border: '1px solid var(--highlight)',
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
              }}
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {!isNew && (
        <>
          <h3 className="section-title" style={{ marginBottom: 12 }}>
            Scenarios ({scenarios.length})
          </h3>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Prompt</th>
                <th>Enabled</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map(sc => (
                <tr key={sc.id}>
                  <td style={{ fontWeight: 500 }}>{sc.name}</td>
                  <td style={{ color: 'var(--text-muted)', fontSize: 13, maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {sc.prompt.slice(0, 120)}...
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={sc.enabled}
                      onChange={() => toggleScenario(sc)}
                    />
                  </td>
                  <td>
                    <button
                      onClick={() => deleteScenario(sc)}
                      style={{
                        padding: '2px 8px',
                        fontSize: 11,
                        background: 'transparent',
                        color: 'var(--text-muted)',
                        border: '1px solid var(--surface-elevated)',
                        borderRadius: 'var(--radius)',
                        cursor: 'pointer',
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
