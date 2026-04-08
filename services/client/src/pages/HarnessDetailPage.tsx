import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import type { HarnessItem, HarnessConfig } from '../api';
import { CopyButton } from '../components/CopyButton';
import { ConfigForm } from '../components/ConfigForm';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { useDetailPageEdit } from '../hooks/useDetailPageEdit';
import { useApiMutation } from '../hooks/useApiMutation';
import { useNotification } from '../context/useNotification';
import { ALL_AGENTS, TYPE_PATHS, isMarkdownType, toggleArrayItem, formatError, MAX_NAME_LENGTH, nameError, isValidRepo } from '../constants';
import { FieldError } from '../components/FieldError';
import { harnessStyles as styles } from '../styles/harness';

function formatBody(item: HarnessItem, type: string): string {
  if (!item.content) return '';
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


interface HarnessEditValues {
  name: string;
  project: string;
  sort_key: string;
  agents: string[];
  enabled: boolean;
  clone_as_skill: boolean;
  body: string;
}

export function HarnessDetailPage() {
  const { type = '', id = '' } = useParams<{ type: string; id: string }>();
  const navigate = useNavigate();
  const { notify } = useNotification();
  const numericId = Number(id);

  const [item, setItem] = useState<HarnessItem | null>(null);
  const [loading, setLoading] = useState(true);

  const {
    editing,
    saving,
    editValues,
    setEditValue,
    startEditing: startEdit,
    cancelEditing: cancelEdit,
    setSaving,
  } = useDetailPageEdit<HarnessEditValues>({
    initialData: item ? {
      name: item.name,
      project: item.project || '',
      sort_key: String(item.sort_key ?? 0),
      agents: [...item.agents],
      enabled: item.enabled,
      clone_as_skill: !!item.clone_as_skill,
      body: formatBody(item, type),
    } : undefined,
  });

  const [history, setHistory] = useState<HarnessItem[]>([]);
  const [previewVersion, setPreviewVersion] = useState<HarnessItem | null>(null);

  const deleteMutation = useApiMutation({
    mutationFn: () => api.harness.items.remove(type, numericId),
    onSuccess: () => {
      const backPath = `/harness/${TYPE_PATHS[type] || type}`;
      navigate(backPath);
    },
  });

  const restoreMutation = useApiMutation({
    mutationFn: (oldItem: HarnessItem) => api.harness.items.updateContent(type, numericId, oldItem.content),
    onSuccess: (updated) => {
      setPreviewVersion(null);
      navigate(`/harness/${type}/${updated.id}`, { replace: true });
    },
  });

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
    startEdit({
      name: item.name,
      project: item.project || '',
      sort_key: String(item.sort_key ?? 0),
      agents: [...item.agents],
      enabled: item.enabled,
      clone_as_skill: !!item.clone_as_skill,
      body: formatBody(item, type),
    });
    setPreviewVersion(null);
  };

  const save = async () => {
    if (!item) return;

    const name = editValues.name?.trim() ?? '';
    const project = editValues.project ?? '';
    const sortKey = editValues.sort_key ?? '';
    const agents = editValues.agents ?? [];
    const enabled = editValues.enabled ?? true;
    const cloneAsSkill = editValues.clone_as_skill ?? false;
    const body = editValues.body ?? '';

    const nameErr = nameError(name);
    if (nameErr) { notify(nameErr, 'error'); return; }
    if (agents.length === 0) { notify('At least one agent must be selected.', 'error'); return; }

    if (!isMarkdownType(type)) {
      try { JSON.parse(body); } catch { notify('Invalid JSON in metadata field.', 'error'); return; }
    }

    setSaving(true);
    try {
      const originalBody = formatBody(item, type);
      const bodyChanged = body !== originalBody;
      const sortKeyNum = sortKey ? parseInt(sortKey, 10) : 0;
      const metadataChanged =
        name !== item.name ||
        enabled !== item.enabled ||
        cloneAsSkill !== !!item.clone_as_skill ||
        sortKeyNum !== (item.sort_key || 0) ||
        (project || null) !== item.project ||
        JSON.stringify(agents.sort()) !== JSON.stringify([...item.agents].sort());

      let currentId = item.id;

      if (bodyChanged) {
        const newContent = isMarkdownType(type)
          ? { body, metadata: item.content?.metadata ?? {} }
          : { body: item.content?.body ?? '', metadata: JSON.parse(body) };
        const updated = await api.harness.items.updateContent(type, currentId, newContent);
        currentId = updated.id;
      }

      if (metadataChanged) {
        await api.harness.items.updateMetadata(type, currentId, {
          name,
          project: project || null,
          sort_key: sortKeyNum,
          agents,
          enabled,
          ...(type === 'rule' ? { clone_as_skill: cloneAsSkill } : {}),
        });
      }

      cancelEdit();
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
      await restoreMutation.mutateAsync(oldItem);
    } finally {
      setSaving(false);
    }
  };

  const toggleAgent = (agent: string) => {
    const current = editValues.agents ?? [];
    setEditValue('agents', toggleArrayItem(current, agent));
  };

  const handleDelete = async () => {
    if (!item) return;
    await deleteMutation.mutateAsync();
  };


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
    if (!item) return;
    if (!isValidRepo(cfgRepo)) {
      notify('Repo must be * or an absolute path.', 'error');
      return;
    }
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
      <DetailPageHeader
        backTo={{ label: TYPE_PATHS[type] || type, path: backPath }}
        editing={editing}
        saving={saving}
        onEdit={startEditing}
        onSave={save}
        onCancel={cancelEdit}
        onDelete={!previewVersion ? handleDelete : undefined}
        onNavigateBack={() => navigate(backPath)}
        deleteConfirmMessage={`Delete ${type} "${displayItem.name}"?`}
        showActions={!previewVersion}
      />

      {editing ? (
        <div style={{ marginBottom: 12 }}>
          <input
            style={{ ...styles.input, borderColor: editValues.name && nameError(editValues.name) ? 'var(--highlight)' : undefined }}
            value={editValues.name ?? ''}
            onChange={e => setEditValue('name', e.target.value)}
            maxLength={MAX_NAME_LENGTH}
          />
          <FieldError error={editValues.name ? nameError(editValues.name) : null} maxLength={MAX_NAME_LENGTH} currentLength={editValues.name?.length ?? 0} />
        </div>
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
        {displayItem.clone_as_skill && (
          <span className="tag" style={{ background: 'rgba(255,100,100,0.15)', color: 'var(--highlight)' }}>
            Skill Clone
          </span>
        )}
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
                value={editValues.project ?? ''}
                onChange={e => setEditValue('project', e.target.value)}
                placeholder="Empty = shared/global"
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 6 }}>
                Sort Order
              </label>
              <input
                type="number"
                min={0}
                style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '6px 10px', fontSize: 13, fontFamily: 'var(--mono)', width: 120 }}
                value={editValues.sort_key ?? ''}
                onChange={e => setEditValue('sort_key', e.target.value)}
                placeholder="e.g. 5"
              />
            </div>
          </div>
          <div style={styles.checkboxRow}>
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={editValues.enabled ?? true}
                onChange={() => setEditValue('enabled', !(editValues.enabled ?? true))}
                style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
              />
              Enabled
            </label>
            {type === 'rule' && (
              <label style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={editValues.clone_as_skill ?? false}
                  onChange={() => setEditValue('clone_as_skill', !(editValues.clone_as_skill ?? false))}
                  style={{ accentColor: 'var(--highlight)', width: 16, height: 16 }}
                />
                Clone as Skill
              </label>
            )}
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>|</span>
            {ALL_AGENTS.map(agent => (
              <label key={agent} style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={(editValues.agents ?? []).includes(agent)}
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
                value={editValues.body ?? ''}
                onChange={val => setEditValue('body', val || '')}
                height={400}
              />
            </div>
          ) : (
            <textarea
              style={styles.textarea}
              value={editValues.body ?? ''}
              onChange={e => setEditValue('body', e.target.value)}
              spellCheck={false}
            />
          )
        ) : (
          <div style={{ position: 'relative' }}>
            <CopyButton text={displayBody} style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }} />
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
          <button className="btn btn-danger" onClick={() => restoreVersion(previewVersion)} disabled={saving}>
            {saving ? 'Restoring...' : `Restore v${previewVersion.version}`}
          </button>
          <button className="btn" onClick={() => setPreviewVersion(null)}>
            Back to current
          </button>
        </div>
      )}

      <h3 className="section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        Configurations
        {!previewVersion && !addingConfig && editingConfigId === null && (
          <button className="btn btn-sm" onClick={startAddConfig}>+ Add</button>
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
                {cfg.subagents && cfg.subagents.length > 0 && (
                  <>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', margin: '0 4px' }}>|</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Subagents:</span>
                    {cfg.subagents.map(s => (
                      <span key={s} style={{
                        fontSize: 11,
                        padding: '2px 6px',
                        background: 'var(--warning)',
                        color: 'var(--bg)',
                        borderRadius: 4,
                        marginLeft: 4,
                        fontWeight: 500
                      }}>{s}</span>
                    ))}
                  </>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: cfg.enabled ? 'var(--success)' : 'var(--text-muted)' }}>
                  {cfg.enabled ? 'Enabled' : 'Disabled'}
                </span>
                {!previewVersion && (
                  <>
                    <button className="btn btn-sm" onClick={() => startEditConfig(cfg)}>Edit</button>
                    <button className="btn btn-sm btn-danger" onClick={() => { if (confirm('Delete this configuration?')) deleteConfig(cfg.id); }}>Delete</button>
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
