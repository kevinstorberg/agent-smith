import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { api } from '../api';
import type { EvalSuite, EvalScenario } from '../api';
import { CopyButton } from '../components/CopyButton';

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
  const [saving, setSaving] = useState(false);

  // Suite edit state
  const [editing, setEditing] = useState(isNew);
  const [editName, setEditName] = useState('');
  const [editEvalType, setEditEvalType] = useState('');
  const [editSubcategory, setEditSubcategory] = useState('');
  const [editJudgePrompt, setEditJudgePrompt] = useState('');
  const [editItemsJson, setEditItemsJson] = useState('{}');
  const [editConfigJson, setEditConfigJson] = useState('{}');
  const [editEnabled, setEditEnabled] = useState(true);

  // Scenario edit state
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [editingScenarioId, setEditingScenarioId] = useState<number | null>(null);
  const [editScenarioName, setEditScenarioName] = useState('');
  const [editScenarioPrompt, setEditScenarioPrompt] = useState('');

  // Add scenario state
  const [addingScenario, setAddingScenario] = useState(false);
  const [newName, setNewName] = useState('');
  const [newPrompt, setNewPrompt] = useState('');

  const loadSuite = () => {
    if (isNew) return;
    api.evalConfigs.suites.get(Number(id)).then(data => {
      setSuite(data);
      setScenarios(data.scenarios || []);
      populateEditFields(data);
    });
  };

  const populateEditFields = (data: Partial<EvalSuite>) => {
    setEditName(data.name || '');
    setEditEvalType(data.eval_type || '');
    setEditSubcategory(data.subcategory || '');
    setEditJudgePrompt(data.judge_prompt || '');
    setEditItemsJson(JSON.stringify(data.items || {}, null, 2));
    setEditConfigJson(JSON.stringify(data.config || {}, null, 2));
    setEditEnabled(data.enabled ?? true);
  };

  useEffect(() => { loadSuite(); }, [id, isNew]); // eslint-disable-line react-hooks/exhaustive-deps

  const startEditing = () => {
    populateEditFields(suite);
    setEditing(true);
  };

  const cancelEditing = () => {
    if (isNew) { navigate('/eval-configs'); return; }
    populateEditFields(suite);
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      let parsedItems: Record<string, unknown>;
      let parsedConfig: Record<string, unknown>;
      try { parsedItems = JSON.parse(editItemsJson); } catch { alert('Invalid JSON in Items field'); return; }
      try { parsedConfig = JSON.parse(editConfigJson); } catch { alert('Invalid JSON in Config field'); return; }

      const body = {
        name: editName,
        eval_type: editEvalType,
        subcategory: editSubcategory,
        judge_prompt: editJudgePrompt,
        items: parsedItems,
        config: parsedConfig,
        enabled: editEnabled,
      };

      if (isNew) {
        const created = await api.evalConfigs.suites.create(body);
        navigate(`/eval-configs/${created.id}`, { replace: true });
      } else {
        await api.evalConfigs.suites.update(Number(id), body);
        const updated = await api.evalConfigs.suites.get(Number(id));
        setSuite(updated);
        setEditing(false);
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
    setScenarios(prev => prev.map(s => (s.id === sc.id ? { ...s, enabled: !s.enabled } : s)));
  };

  const deleteScenario = async (sc: EvalScenario) => {
    if (!confirm(`Delete scenario "${sc.name}"?`)) return;
    await api.evalConfigs.scenarios.remove(sc.id);
    setScenarios(prev => prev.filter(s => s.id !== sc.id));
  };

  const startScenarioEdit = (sc: EvalScenario) => {
    setEditingScenarioId(sc.id);
    setEditScenarioName(sc.name);
    setEditScenarioPrompt(sc.prompt);
    setExpandedId(sc.id);
  };

  const cancelScenarioEdit = () => {
    setEditingScenarioId(null);
  };

  const saveScenarioEdit = async (scId: number) => {
    setSaving(true);
    try {
      await api.evalConfigs.scenarios.update(scId, { name: editScenarioName, prompt: editScenarioPrompt });
      setScenarios(prev => prev.map(s => (s.id === scId ? { ...s, name: editScenarioName, prompt: editScenarioPrompt } : s)));
      setEditingScenarioId(null);
    } finally {
      setSaving(false);
    }
  };

  const addScenario = async () => {
    if (!newName.trim() || !newPrompt.trim()) return;
    setSaving(true);
    try {
      const created = await api.evalConfigs.scenarios.create(Number(id), {
        name: newName.trim(),
        prompt: newPrompt.trim(),
        enabled: true,
      });
      setScenarios(prev => [...prev, created]);
      setAddingScenario(false);
      setNewName('');
      setNewPrompt('');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <a
          onClick={() => navigate('/eval-configs')}
          style={{ color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13 }}
        >
          &larr; Back to Evals
        </a>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {!isNew && suite.eval_type && (
            <a
              onClick={() => navigate(`/evals?category=${suite.eval_type}&subcategory=${suite.subcategory}`)}
              style={{ color: 'var(--info)', cursor: 'pointer', fontSize: 13, marginRight: 8 }}
            >
              View Results &rarr;
            </a>
          )}
          {!editing && (
            <button className="btn" onClick={startEditing}>Edit</button>
          )}
          {editing && (
            <>
              <button className="btn btn-primary" onClick={save} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button className="btn" onClick={cancelEditing}>Cancel</button>
            </>
          )}
          {!isNew && !editing && (
            <button className="btn btn-danger" onClick={deleteSuite}>Delete</button>
          )}
        </div>
      </div>

      {/* Suite title */}
      {editing ? (
        <input
          type="text"
          value={editName}
          onChange={e => setEditName(e.target.value)}
          placeholder="Suite name"
          style={{ width: '100%', fontSize: 18, fontWeight: 600, marginBottom: 16 }}
        />
      ) : (
        <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>
          {suite.name || 'New Suite'}
        </h2>
      )}

      {/* Suite details card */}
      <div className="card" style={{ marginBottom: 24 }}>
        {/* Eval Type / Subcategory */}
        {editing ? (
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Eval Type</label>
              <input type="text" value={editEvalType} onChange={e => setEditEvalType(e.target.value)} style={{ width: '100%', fontSize: 13 }} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Subcategory</label>
              <input type="text" value={editSubcategory} onChange={e => setEditSubcategory(e.target.value)} style={{ width: '100%', fontSize: 13 }} />
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <span className="tag">{suite.eval_type} / {suite.subcategory}</span>
            <span style={{ color: suite.enabled ? 'var(--success)' : 'var(--text-muted)', fontSize: 12, alignSelf: 'center' }}>
              {suite.enabled ? 'Enabled' : 'Disabled'}
            </span>
          </div>
        )}

        {/* Judge Prompt */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Judge Prompt</label>
          {editing ? (
            <textarea
              value={editJudgePrompt}
              onChange={e => setEditJudgePrompt(e.target.value)}
              rows={10}
              style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)' }}
            />
          ) : (
            <div style={{ position: 'relative' }}>
              <CopyButton text={suite.judge_prompt || ''} style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} />
              <pre style={{
                whiteSpace: 'pre-wrap',
                fontFamily: 'var(--mono)',
                fontSize: 13,
                lineHeight: 1.6,
                color: 'var(--text)',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                padding: 12,
                paddingRight: 60,
                margin: 0,
              }}>
                {suite.judge_prompt}
              </pre>
            </div>
          )}
        </div>

        {/* Items JSON */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Items (JSON)</label>
          {editing ? (
            <textarea
              value={editItemsJson}
              onChange={e => setEditItemsJson(e.target.value)}
              rows={6}
              style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text)' }}
            />
          ) : (
            <pre style={{
              fontFamily: 'var(--mono)',
              fontSize: 12,
              color: 'var(--text)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: 12,
              margin: 0,
            }}>
              {JSON.stringify(suite.items, null, 2)}
            </pre>
          )}
        </div>

        {/* Config JSON */}
        <div style={{ marginBottom: editing ? 16 : 0 }}>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Config (JSON)</label>
          {editing ? (
            <textarea
              value={editConfigJson}
              onChange={e => setEditConfigJson(e.target.value)}
              rows={4}
              style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--text)' }}
            />
          ) : (
            <pre style={{
              fontFamily: 'var(--mono)',
              fontSize: 12,
              color: 'var(--text)',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: 12,
              margin: 0,
            }}>
              {JSON.stringify(suite.config, null, 2)}
            </pre>
          )}
        </div>

        {/* Enabled toggle (only in edit mode) */}
        {editing && (
          <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="checkbox"
              checked={editEnabled}
              onChange={e => setEditEnabled(e.target.checked)}
              style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
            />
            Enabled
          </label>
        )}
      </div>

      {/* Scenarios */}
      {!isNew && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 className="section-title">Scenarios ({scenarios.length})</h3>
            <button onClick={() => setAddingScenario(true)} className="btn btn-primary" style={{ fontSize: 12 }}>
              + Add Scenario
            </button>
          </div>

          {addingScenario && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Name</label>
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)} placeholder="scenario_name" style={{ width: '100%', fontSize: 13 }} />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Prompt</label>
                <textarea value={newPrompt} onChange={e => setNewPrompt(e.target.value)} rows={6} placeholder="Scenario prompt..." style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 13, color: 'var(--text)' }} />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={addScenario} disabled={saving} className="btn btn-primary" style={{ fontSize: 12 }}>
                  {saving ? 'Adding...' : 'Add'}
                </button>
                <button onClick={() => { setAddingScenario(false); setNewName(''); setNewPrompt(''); }} className="btn" style={{ fontSize: 12 }}>
                  Cancel
                </button>
              </div>
            </div>
          )}

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
              {scenarios.map(sc => {
                const isExpanded = expandedId === sc.id;
                const isScenarioEditing = editingScenarioId === sc.id;

                return (
                  <tr key={sc.id} style={{ verticalAlign: 'top' }}>
                    <td style={{ fontWeight: 500 }}>
                      {isScenarioEditing ? (
                        <input type="text" value={editScenarioName} onChange={e => setEditScenarioName(e.target.value)} style={{ width: '100%', fontSize: 13 }} />
                      ) : (
                        sc.name
                      )}
                    </td>
                    <td style={{ fontSize: 13, maxWidth: 500 }}>
                      {isScenarioEditing ? (
                        <div>
                          <textarea
                            value={editScenarioPrompt}
                            onChange={e => setEditScenarioPrompt(e.target.value)}
                            rows={8}
                            style={{ width: '100%', fontFamily: 'var(--mono)', fontSize: 12, marginBottom: 8, color: 'var(--text)' }}
                          />
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button onClick={() => saveScenarioEdit(sc.id)} disabled={saving} className="btn btn-primary" style={{ fontSize: 11 }}>
                              {saving ? 'Saving...' : 'Save'}
                            </button>
                            <button onClick={cancelScenarioEdit} className="btn" style={{ fontSize: 11 }}>Cancel</button>
                          </div>
                        </div>
                      ) : isExpanded ? (
                        <div>
                          <div style={{ position: 'relative' }}>
                            <CopyButton text={sc.prompt} style={{ position: 'absolute', top: 0, right: 0 }} />
                            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--mono)', fontSize: 12, margin: 0, paddingRight: 60, color: 'var(--text)' }}>
                              {sc.prompt}
                            </pre>
                          </div>
                          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                            <button onClick={() => startScenarioEdit(sc)} className="btn" style={{ fontSize: 11 }}>Edit</button>
                            <button onClick={() => setExpandedId(null)} className="btn" style={{ fontSize: 11 }}>Collapse</button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span
                            style={{ color: 'var(--text-muted)', cursor: 'pointer' }}
                            onClick={() => setExpandedId(sc.id)}
                          >
                            {sc.prompt.slice(0, 120)}...
                          </span>
                          <span
                            onClick={() => startScenarioEdit(sc)}
                            style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 14, flexShrink: 0 }}
                            title="Edit scenario"
                          >
                            &#9998;
                          </span>
                        </div>
                      )}
                    </td>
                    <td>
                      <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                          type="checkbox"
                          checked={sc.enabled}
                          onChange={() => toggleScenario(sc)}
                          style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
                        />
                        <span style={{ color: sc.enabled ? 'var(--success)' : 'var(--text-muted)', fontSize: 12 }}>
                          {sc.enabled ? 'On' : 'Off'}
                        </span>
                      </label>
                    </td>
                    <td>
                      <button onClick={() => deleteScenario(sc)} className="btn btn-danger" style={{ fontSize: 11, padding: '2px 8px' }}>
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
