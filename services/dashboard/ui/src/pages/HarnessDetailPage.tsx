import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import type { HarnessItem, HarnessConfig } from '../api';
import { CopyButton } from '../components/CopyButton';
import { ConfigForm } from '../components/ConfigForm';
import { useNotification } from '../context/useNotification';
import { ALL_AGENTS, TYPE_PATHS, isMarkdownType, toggleArrayItem, formatError } from '../constants';
import { harnessStyles as styles } from '../styles/harness';

function formatBody(item: HarnessItem, type: string): string {
  if (isMarkdownType(type)) return item.content.body;
  return JSON.stringify(item.content.metadata, null, 2);
}

function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}


export function HarnessDetailPage() {
  const { type = '', id = '' } = useParams<{ type: string; id: string }>();
  const navigate = useNavigate();
  const { notify } = useNotification();
  const numericId = Number(id);

  const [item, setItem] = useState<HarnessItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [editName, setEditName] = useState('');
  const [editProject, setEditProject] = useState('');
  const [editSortKey, setEditSortKey] = useState('');
  const [editAgents, setEditAgents] = useState<string[]>([]);
  const [editEnabled, setEditEnabled] = useState(true);
  const [editBody, setEditBody] = useState('');

  const [history, setHistory] = useState<HarnessItem[]>([]);
  const [previewVersion, setPreviewVersion] = useState<HarnessItem | null>(null);

  const [addingConfig, setAddingConfig] = useState(false);
  const [editingConfigId, setEditingConfigId] = useState<number | null>(null);
  const [cfgDevice, setCfgDevice] = useState('*');
  const [cfgRepo, setCfgRepo] = useState('*');
  const [cfgAgents, setCfgAgents] = useState<string[]>([...ALL_AGENTS]);
  const [cfgEnabled, setCfgEnabled] = useState(true);
  const [cfgExclude, setCfgExclude] = useState(false);
  const [cfgSaving, setCfgSaving] = useState(false);

  const loadItem = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.harness.items.get(type, numericId);
      setItem(data);
      setEditName(data.name);
      setEditProject(data.project || '');
      setEditSortKey(data.sort_key || '');
      setEditAgents([...data.agents]);
      setEditEnabled(data.enabled);
      setEditBody(formatBody(data, type));
    } finally {
      setLoading(false);
    }
  }, [type, numericId]);

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.harness.items.history(type, numericId);
      setHistory(data);
    } catch {
      setHistory([]);
    }
  }, [type, numericId]);

  useEffect(() => {
    loadItem();
    loadHistory();
  }, [loadItem, loadHistory]);

  const startEditing = () => {
    if (!item) return;
    setEditName(item.name);
    setEditProject(item.project || '');
    setEditSortKey(item.sort_key || '');
    setEditAgents([...item.agents]);
    setEditEnabled(item.enabled);
    setEditBody(formatBody(item, type));
    setPreviewVersion(null);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
  };

  const save = async () => {
    if (!item) return;
    setSaving(true);
    try {
      const originalBody = formatBody(item, type);
      const bodyChanged = editBody !== originalBody;
      const metadataChanged =
        editName !== item.name ||
        editEnabled !== item.enabled ||
        editSortKey !== (item.sort_key || '') ||
        (editProject || null) !== item.project ||
        JSON.stringify(editAgents.sort()) !== JSON.stringify([...item.agents].sort());

      let currentId = item.id;

      if (bodyChanged) {
        const newContent = isMarkdownType(type)
          ? { body: editBody, metadata: item.content.metadata }
          : { body: item.content.body, metadata: JSON.parse(editBody) };
        const updated = await api.harness.items.updateContent(type, currentId, newContent);
        currentId = updated.id;
      }

      if (metadataChanged) {
        await api.harness.items.updateMetadata(type, currentId, {
          name: editName,
          project: editProject || null,
          sort_key: editSortKey || undefined,
          agents: editAgents,
          enabled: editEnabled,
        });
      }

      setEditing(false);
      if (currentId !== item.id) {
        navigate(`/harness/${type}/${currentId}`, { replace: true });
      } else {
        await loadItem();
        await loadHistory();
      }
    } catch (err) {
      notify(`Save failed: ${formatError(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const restoreVersion = async (oldItem: HarnessItem) => {
    if (!item) return;
    setSaving(true);
    try {
      const updated = await api.harness.items.updateContent(type, item.id, oldItem.content);
      setPreviewVersion(null);
      navigate(`/harness/${type}/${updated.id}`, { replace: true });
    } catch (err) {
      notify(`Restore failed: ${formatError(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const toggleAgent = (agent: string) => setEditAgents(prev => toggleArrayItem(prev, agent));

  const isValidRepo = (r: string) => r === '*' || r.startsWith('/');

  const resetCfgForm = () => {
    setCfgDevice('*');
    setCfgRepo('*');
    setCfgAgents([...ALL_AGENTS]);
    setCfgEnabled(true);
    setCfgExclude(false);
  };

  const startAddConfig = () => {
    resetCfgForm();
    setEditingConfigId(null);
    setAddingConfig(true);
  };

  const startEditConfig = (cfg: HarnessConfig) => {
    setCfgDevice(cfg.device);
    setCfgRepo(cfg.repo);
    setCfgAgents([...cfg.agents]);
    setCfgEnabled(cfg.enabled);
    setCfgExclude(cfg.exclude);
    setEditingConfigId(cfg.id);
    setAddingConfig(false);
  };

  const cancelConfigForm = () => {
    setAddingConfig(false);
    setEditingConfigId(null);
  };

  const saveConfig = async () => {
    if (!item || !isValidRepo(cfgRepo)) return;
    setCfgSaving(true);
    try {
      if (editingConfigId) {
        await api.harness.items.configs.update(type, item.id, editingConfigId, {
          device: cfgDevice, repo: cfgRepo, agents: cfgAgents, enabled: cfgEnabled, exclude: cfgExclude,
        });
      } else {
        await api.harness.items.configs.add(type, item.id, {
          device: cfgDevice, repo: cfgRepo, agents: cfgAgents, enabled: cfgEnabled, exclude: cfgExclude,
        });
      }
      cancelConfigForm();
      await loadItem();
    } catch (err) {
      notify(`Config save failed: ${formatError(err)}`, 'error');
    } finally {
      setCfgSaving(false);
    }
  };

  const deleteConfig = async (configId: number) => {
    if (!item) return;
    try {
      await api.harness.items.configs.remove(type, item.id, configId);
      await loadItem();
    } catch (err) {
      notify(`Config delete failed: ${formatError(err)}`, 'error');
    }
  };


  if (loading) return <div className="loading">Loading...</div>;
  if (!item) return <div className="loading">Item not found</div>;

  const displayItem = previewVersion || item;
  const displayBody = formatBody(displayItem, type);
  const backPath = `/harness/${TYPE_PATHS[type] || type}`;

  return (
    <div>
      <div style={styles.header}>
        <button style={styles.backLink} onClick={() => navigate(backPath)}>
          &larr; Back to {TYPE_PATHS[type] || type}
        </button>
        <div style={{ display: 'flex', gap: 8 }}>
          {!editing && !previewVersion && (
            <>
              <button style={styles.btn} onClick={startEditing}>Edit</button>
              <button className="btn btn-danger" onClick={() => {
                if (confirm(`Delete ${type} "${displayItem.name}"?`)) {
                  api.harness.items.remove(type, displayItem.id).then(() => navigate(backPath));
                }
              }}>Delete</button>
            </>
          )}
          {editing && (
            <>
              <button style={{ ...styles.btn, opacity: saving ? 0.5 : 1 }} onClick={save} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button style={styles.btn} onClick={cancelEditing}>Cancel</button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <input
          style={{ ...styles.input, marginBottom: 12 }}
          value={editName}
          onChange={e => setEditName(e.target.value)}
        />
      ) : (
        <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
          {displayItem.name}
          {previewVersion && (
            <span style={{ fontSize: 13, color: 'var(--warning)', marginLeft: 12 }}>
              (viewing v{previewVersion.version})
            </span>
          )}
        </h2>
      )}

      <div style={styles.badges}>
        <span className="tag" style={{ fontFamily: 'var(--mono)' }}>v{displayItem.version}</span>
        <span className="tag" style={{ fontFamily: 'var(--mono)' }}>#{displayItem.sort_key}</span>
        <span className="tag" style={{ background: displayItem.enabled ? 'var(--success)' : 'var(--text-muted)', color: '#1a1a2e' }}>
          {displayItem.enabled ? 'Enabled' : 'Disabled'}
        </span>
        {displayItem.project && (
          <span className="tag" style={{ background: 'rgba(91,141,239,0.15)', color: 'var(--info)', borderColor: 'rgba(91,141,239,0.3)' }}>
            {displayItem.project}
          </span>
        )}
        {displayItem.agents.map(a => (
          <span key={a} className="tag">{a}</span>
        ))}
      </div>

      {editing && (
        <>
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 }}>
                Project
              </label>
              <input
                style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '6px 10px', fontSize: 13, fontFamily: 'var(--font)', width: 220 }}
                value={editProject}
                onChange={e => setEditProject(e.target.value)}
                placeholder="Empty = shared/global"
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 }}>
                Sort Order
              </label>
              <input
                style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '6px 10px', fontSize: 13, fontFamily: 'var(--mono)', width: 120 }}
                value={editSortKey}
                onChange={e => setEditSortKey(e.target.value)}
                placeholder="e.g. 005"
              />
            </div>
          </div>
          <div style={styles.checkboxRow}>
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={editEnabled}
                onChange={() => setEditEnabled(!editEnabled)}
                style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
              />
              Enabled
            </label>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>|</span>
            {ALL_AGENTS.map(agent => (
              <label key={agent} style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={editAgents.includes(agent)}
                  onChange={() => toggleAgent(agent)}
                  style={{ accentColor: 'var(--highlight)', width: 16, height: 16 }}
                />
                {agent}
              </label>
            ))}
          </div>
        </>
      )}

      <div className="card" style={{ marginBottom: 24 }}>
        {editing ? (
          isMarkdownType(type) ? (
            <div data-color-mode="dark">
              <MDEditor
                value={editBody}
                onChange={val => setEditBody(val || '')}
                height={400}
              />
            </div>
          ) : (
            <textarea
              style={styles.textarea}
              value={editBody}
              onChange={e => setEditBody(e.target.value)}
              spellCheck={false}
            />
          )
        ) : (
          <div style={{ position: 'relative' }}>
            <CopyButton text={displayBody} style={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }} />
            {isMarkdownType(type) ? (
              <div className="markdown-content">
                <ReactMarkdown>{displayBody}</ReactMarkdown>
              </div>
            ) : (
              <pre>{displayBody}</pre>
            )}
          </div>
        )}
      </div>

      {previewVersion && (
        <div style={{ marginBottom: 24, display: 'flex', gap: 8 }}>
          <button style={styles.btnDanger} onClick={() => restoreVersion(previewVersion)} disabled={saving}>
            {saving ? 'Restoring...' : `Restore v${previewVersion.version}`}
          </button>
          <button style={styles.btn} onClick={() => setPreviewVersion(null)}>
            Back to current
          </button>
        </div>
      )}

      <h3 className="section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        Configurations
        {!previewVersion && !addingConfig && editingConfigId === null && (
          <button style={{ ...styles.btn, fontSize: 12, padding: '4px 10px' }} onClick={startAddConfig}>+ Add</button>
        )}
      </h3>
      <div style={{ marginBottom: 24 }}>
        {(item.configs ?? []).length === 0 && !addingConfig && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 12 }}>
            No configurations — using legacy defaults
          </div>
        )}
        {(item.configs ?? []).map(cfg => (
          editingConfigId === cfg.id ? (
            <ConfigForm
              key={cfg.id}
              device={cfgDevice} repo={cfgRepo} agents={cfgAgents} enabled={cfgEnabled} exclude={cfgExclude} saving={cfgSaving}
              onDeviceChange={setCfgDevice} onRepoChange={setCfgRepo} onAgentsChange={setCfgAgents} onEnabledChange={setCfgEnabled} onExcludeChange={setCfgExclude}
              onSave={saveConfig} onCancel={cancelConfigForm}
            />
          ) : (
            <div
              key={cfg.id}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                padding: '10px 14px',
                marginBottom: 8,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 8,
              }}
            >
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span className="tag" style={{ background: cfg.exclude ? 'rgba(255,100,100,0.15)' : 'rgba(100,200,100,0.15)', color: cfg.exclude ? 'var(--highlight)' : 'var(--success)', fontWeight: 600, fontSize: 11 }}>
                  {cfg.exclude ? 'Exclude' : 'Include'}
                </span>
                <span className="tag" style={{ background: 'rgba(255,165,0,0.15)', color: 'var(--warning)' }}>
                  {cfg.device === '*' ? 'All devices' : cfg.device}
                </span>
                <span className="tag" style={{ background: 'rgba(100,200,100,0.15)', color: 'var(--success)', fontFamily: 'var(--mono)', fontSize: 11 }}>
                  {cfg.repo === '*' ? 'Global' : cfg.repo}
                </span>
                {cfg.agents.map(a => (
                  <span key={a} className="tag">{a}</span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: cfg.enabled ? 'var(--success)' : 'var(--text-muted)' }}>
                  {cfg.enabled ? 'Enabled' : 'Disabled'}
                </span>
                {!previewVersion && (
                  <>
                    <button style={{ ...styles.btn, fontSize: 11, padding: '2px 8px' }} onClick={() => startEditConfig(cfg)}>Edit</button>
                    <button style={{ ...styles.btnDanger, fontSize: 11, padding: '2px 8px' }} onClick={() => { if (confirm('Delete this configuration?')) deleteConfig(cfg.id); }}>Delete</button>
                  </>
                )}
              </div>
            </div>
          )
        ))}
        {addingConfig && (
          <ConfigForm
            title="New Configuration"
            device={cfgDevice} repo={cfgRepo} agents={cfgAgents} enabled={cfgEnabled} exclude={cfgExclude} saving={cfgSaving}
            onDeviceChange={setCfgDevice} onRepoChange={setCfgRepo} onAgentsChange={setCfgAgents} onEnabledChange={setCfgEnabled} onExcludeChange={setCfgExclude}
            onSave={saveConfig} onCancel={cancelConfigForm} submitLabel="Add"
          />
        )}
      </div>

      <h3 className="section-title">Version History</h3>
      <div>
        {history.map(h => (
          <div
            key={h.id}
            style={{
              ...styles.versionItem,
              background: previewVersion?.id === h.id ? 'var(--surface-hover)' : 'var(--surface)',
            }}
            onMouseEnter={e => {
              if (previewVersion?.id !== h.id) {
                (e.currentTarget as HTMLElement).style.background = 'var(--surface-hover)';
              }
            }}
            onMouseLeave={e => {
              if (previewVersion?.id !== h.id) {
                (e.currentTarget as HTMLElement).style.background = 'var(--surface)';
              }
            }}
            onClick={() => {
              if (h.id === item.id) {
                setPreviewVersion(null);
              } else {
                setPreviewVersion(h);
              }
            }}
          >
            <div>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 13 }}>v{h.version}</span>
              {h.id === item.id && (
                <span style={{ fontSize: 11, color: 'var(--success)', marginLeft: 8 }}>current</span>
              )}
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              {formatTimestamp(h.created_at)}
            </span>
          </div>
        ))}
        {history.length === 0 && (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 12 }}>
            No version history available
          </div>
        )}
      </div>
    </div>
  );
}
