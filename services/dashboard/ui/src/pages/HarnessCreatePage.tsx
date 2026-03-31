import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import MDEditor from '@uiw/react-md-editor';

function typeFromPath(pathname: string): string {
  const match = pathname.match(/\/harness\/(\w+)\/new/);
  return match ? match[1] : 'rule';
}
import { api } from '../api';
import { useNotification } from '../context/useNotification';

const ALL_AGENTS = ['claude', 'codex', 'gemini'];

const TYPE_PATHS: Record<string, string> = {
  rule: 'rules',
  skill: 'skills',
  tool: 'tools',
  hook: 'hooks',
};

const TYPE_LABELS: Record<string, string> = {
  rule: 'Rule',
  skill: 'Skill',
  tool: 'Tool',
  hook: 'Hook',
};

function isMarkdownType(type: string): boolean {
  return type === 'rule' || type === 'skill';
}

const PLACEHOLDER_METADATA: Record<string, string> = {
  tool: JSON.stringify({ url: 'https://...', headers: {} }, null, 2),
  hook: JSON.stringify({
    event: 'pre_tool_use',
    matcher: 'Bash',
    hooks: [{ type: 'command', command: '/path/to/script.sh' }],
  }, null, 2),
};

const styles = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
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
  field: {
    marginBottom: 20,
  } as React.CSSProperties,
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 6,
  } as React.CSSProperties,
  input: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 14,
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
  } as React.CSSProperties,
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
    fontSize: 13,
  } as React.CSSProperties,
  actions: {
    display: 'flex',
    gap: 8,
    marginTop: 20,
  } as React.CSSProperties,
};

export function HarnessCreatePage() {
  const location = useLocation();
  const type = typeFromPath(location.pathname);
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [project, setProject] = useState('');
  const [sortKey, setSortKey] = useState('');
  const [agents, setAgents] = useState<string[]>([...ALL_AGENTS]);
  const [enabled, setEnabled] = useState(true);
  const [body, setBody] = useState('');
  const [metadataJson, setMetadataJson] = useState(PLACEHOLDER_METADATA[type] || '{}');
  const [saving, setSaving] = useState(false);
  const { notify } = useNotification();

  const toggleAgent = (agent: string) => {
    setAgents(prev =>
      prev.includes(agent) ? prev.filter(a => a !== agent) : [...prev, agent]
    );
  };

  const save = async () => {
    if (!name.trim()) {
      notify('Name is required.', 'error');
      return;
    }
    if (agents.length === 0) {
      notify('At least one agent must be selected.', 'error');
      return;
    }

    let content: { body: string; metadata: Record<string, unknown> };
    if (isMarkdownType(type)) {
      content = { body, metadata: type === 'skill' ? { description: '', files: {} } : {} };
    } else {
      try {
        const parsed = JSON.parse(metadataJson);
        content = { body: '', metadata: parsed };
      } catch {
        notify('Invalid JSON in metadata field.', 'error');
        return;
      }
    }

    setSaving(true);
    try {
      const created = await api.harness.items.create(type, {
        name: name.trim(),
        project: project.trim() || null,
        sort_key: sortKey.trim() || undefined,
        content,
        agents,
        enabled,
      });
      navigate(`/harness/${type}/${created.id}`);
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setSaving(false);
    }
  };

  const backPath = `/harness/${TYPE_PATHS[type] || type}`;

  return (
    <div>
      <div style={styles.header}>
        <button style={styles.backLink} onClick={() => navigate(backPath)}>
          &larr; Back to {TYPE_PATHS[type] || type}
        </button>
      </div>

      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 20 }}>
        New {TYPE_LABELS[type] || type}
      </h2>

      <div style={styles.field}>
        <label style={styles.label}>Name</label>
        <input
          style={styles.input}
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={`e.g. ${type === 'tool' ? 'MyAPI' : type === 'hook' ? 'lint_on_save' : 'my_new_' + type}`}
        />
      </div>

      <div style={{ ...styles.field, display: 'flex', gap: 16 }}>
        <div style={{ flex: 1 }}>
          <label style={styles.label}>Project</label>
          <input
            style={styles.input}
            value={project}
            onChange={e => setProject(e.target.value)}
            placeholder="Empty = shared/global"
          />
        </div>
        <div style={{ width: 140 }}>
          <label style={styles.label}>Sort Order</label>
          <input
            style={{ ...styles.input, fontFamily: 'var(--mono)' }}
            value={sortKey}
            onChange={e => setSortKey(e.target.value)}
            placeholder="e.g. 005"
          />
        </div>
      </div>

      <div style={styles.field}>
        <label style={styles.label}>Agents</label>
        <div style={styles.checkboxRow}>
          {ALL_AGENTS.map(agent => (
            <label key={agent} style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={agents.includes(agent)}
                onChange={() => toggleAgent(agent)}
                style={{ accentColor: 'var(--highlight)', width: 16, height: 16 }}
              />
              {agent}
            </label>
          ))}
        </div>
      </div>

      <div style={styles.field}>
        <label style={styles.checkboxLabel}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => setEnabled(!enabled)}
            style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
          />
          Enabled
        </label>
      </div>

      <div style={styles.field}>
        <label style={styles.label}>
          {isMarkdownType(type) ? 'Body' : 'Configuration (JSON)'}
        </label>
        {isMarkdownType(type) ? (
          <div data-color-mode="dark">
            <MDEditor
              value={body}
              onChange={val => setBody(val || '')}
              height={400}
            />
          </div>
        ) : (
          <textarea
            style={styles.textarea}
            value={metadataJson}
            onChange={e => setMetadataJson(e.target.value)}
            spellCheck={false}
          />
        )}
      </div>

      <div style={styles.actions}>
        <button className="btn btn-success" onClick={save} disabled={saving}>
          {saving ? 'Creating...' : `Create ${TYPE_LABELS[type] || type}`}
        </button>
        <button className="btn" onClick={() => navigate(backPath)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
