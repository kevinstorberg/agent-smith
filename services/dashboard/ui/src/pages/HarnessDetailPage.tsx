import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import type { HarnessItem } from '../api';

const ALL_AGENTS = ['claude', 'codex', 'gemini'];

const TYPE_PATHS: Record<string, string> = {
  rule: 'rules',
  skill: 'skills',
  tool: 'tools',
  hook: 'hooks',
};

function isMarkdownType(type: string): boolean {
  return type === 'rule' || type === 'skill';
}

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

const styles = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  } as React.CSSProperties,
  backLink: {
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 13,
    background: 'none',
    border: 'none',
    fontFamily: 'var(--font)',
    textDecoration: 'underline',
  } as React.CSSProperties,
  badges: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
    marginBottom: 16,
    flexWrap: 'wrap',
  } as React.CSSProperties,
  btn: {
    background: 'var(--accent)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '6px 14px',
    cursor: 'pointer',
    fontSize: 13,
    fontFamily: 'var(--font)',
  } as React.CSSProperties,
  btnDanger: {
    background: 'var(--highlight)',
    color: 'var(--text)',
    border: '1px solid var(--highlight)',
    borderRadius: 'var(--radius)',
    padding: '4px 10px',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'var(--font)',
  } as React.CSSProperties,
  input: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 18,
    fontWeight: 600,
    fontFamily: 'var(--font)',
    width: '100%',
  } as React.CSSProperties,
  textarea: {
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: 12,
    fontFamily: 'var(--mono)',
    fontSize: 13,
    width: '100%',
    minHeight: 400,
    resize: 'vertical' as const,
  } as React.CSSProperties,
  checkboxRow: {
    display: 'flex',
    gap: 16,
    alignItems: 'center',
    marginBottom: 20,
  } as React.CSSProperties,
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
    fontSize: 13,
  } as React.CSSProperties,
  versionItem: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '10px 14px',
    marginBottom: 8,
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    cursor: 'pointer',
    transition: 'background 0.15s',
  } as React.CSSProperties,
} as const;

export function HarnessDetailPage() {
  const { type = '', id = '' } = useParams<{ type: string; id: string }>();
  const navigate = useNavigate();
  const numericId = Number(id);

  const [item, setItem] = useState<HarnessItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [editName, setEditName] = useState('');
  const [editProject, setEditProject] = useState('');
  const [editAgents, setEditAgents] = useState<string[]>([]);
  const [editEnabled, setEditEnabled] = useState(true);
  const [editBody, setEditBody] = useState('');

  const [history, setHistory] = useState<HarnessItem[]>([]);
  const [previewVersion, setPreviewVersion] = useState<HarnessItem | null>(null);

  const loadItem = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.harness.items.get(type, numericId);
      setItem(data);
      setEditName(data.name);
      setEditProject(data.project || '');
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
      alert(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
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
      alert(`Restore failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const toggleAgent = (agent: string) => {
    setEditAgents(prev =>
      prev.includes(agent) ? prev.filter(a => a !== agent) : [...prev, agent]
    );
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
            <button style={styles.btn} onClick={startEditing}>Edit</button>
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
          <div style={{ marginBottom: 16 }}>
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
          isMarkdownType(type) ? (
            <div className="markdown-content">
              <ReactMarkdown>{displayBody}</ReactMarkdown>
            </div>
          ) : (
            <pre>{displayBody}</pre>
          )
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
