import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { api } from '../api';
import { useNotification } from '../context/useNotification';
import { ALL_AGENTS, TYPE_PATHS, TYPE_LABELS, isMarkdownType, toggleArrayItem, formatError, MAX_NAME_LENGTH, nameError, isValidRepo } from '../constants';
import { FieldError } from '../components/FieldError';
import { MarkdownEditor } from '../components/MarkdownEditor';
import { harnessStyles as styles } from '../styles/harness';
import { validators } from '../utils/validation';

function typeFromPath(pathname: string): string {
  const match = pathname.match(/\/harness\/(\w+)\/new/);
  return match ? match[1] : 'rule';
}

const PLACEHOLDER_METADATA: Record<string, string> = {
  tool: JSON.stringify({ url: 'https://...', headers: {} }, null, 2),
  hook: JSON.stringify({
    event: 'pre_tool_use',
    matcher: 'Bash',
    hooks: [{ type: 'command', command: '/path/to/script.sh' }],
  }, null, 2),
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
  const [cloneAsSkill, setCloneAsSkill] = useState(false);
  const [body, setBody] = useState('');
  const [metadataJson, setMetadataJson] = useState(PLACEHOLDER_METADATA[type] || '{}');
  const [saving, setSaving] = useState(false);
  const [device, setDevice] = useState('*');
  const [repo, setRepo] = useState('*');
  const { notify } = useNotification();

  const toggleAgent = (agent: string) => setAgents(prev => toggleArrayItem(prev, agent));

  const save = async () => {
    const nameErr = nameError(name.trim());
    if (nameErr) {
      notify(nameErr, 'error');
      return;
    }
    if (agents.length === 0) {
      notify('At least one agent must be selected.', 'error');
      return;
    }
    if (!isValidRepo(repo)) {
      notify('Repo must be * or an absolute path.', 'error');
      return;
    }

    let content: { body: string; metadata: Record<string, unknown> };
    if (isMarkdownType(type)) {
      content = { body, metadata: type === 'skill' ? { description: '', files: {} } : {} };
    } else {
      const jsonError = validators.json(metadataJson);
      if (jsonError) {
        notify('Invalid JSON in metadata field.', 'error');
        return;
      }
      content = { body: '', metadata: JSON.parse(metadataJson) };
    }

    setSaving(true);
    try {
      const created = await api.harness.items.create(type, {
        name: name.trim(),
        project: project.trim() || null,
        sort_key: sortKey ? parseInt(sortKey, 10) : undefined,
        content,
        agents,
        enabled,
        device: device.trim() || '*',
        repo: repo.trim() || '*',
      });
      if (cloneAsSkill && type === 'rule') {
        await api.harness.items.updateMetadata(type, created.id, { clone_as_skill: true });
      }
      navigate(`/harness/${type}/${created.id}`);
    } catch (err) {
      notify(formatError(err), 'error');
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

      <h2 className="page-title" style={{ marginBottom: 20 }}>
        New {TYPE_LABELS[type] || type}
      </h2>

      <div style={styles.field}>
        <label style={styles.label}>Name</label>
        <input
          style={{ ...styles.input, borderColor: name && nameError(name) ? 'var(--highlight)' : undefined }}
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={`e.g. ${type === 'tool' ? 'my_api' : type === 'hook' ? 'lint_on_save' : 'my_new_' + type}`}
          maxLength={MAX_NAME_LENGTH}
        />
        <FieldError error={name ? nameError(name) : null} maxLength={MAX_NAME_LENGTH} currentLength={name.length} />
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
            type="number"
            min={0}
            style={{ ...styles.input, fontFamily: 'var(--mono)' }}
            value={sortKey}
            onChange={e => setSortKey(e.target.value)}
            placeholder="e.g. 5"
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
        <div style={styles.checkboxRow}>
          <label style={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={enabled}
              onChange={() => setEnabled(!enabled)}
              style={{ accentColor: 'var(--success)', width: 16, height: 16 }}
            />
            Enabled
          </label>
          {type === 'rule' && (
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={cloneAsSkill}
                onChange={() => setCloneAsSkill(!cloneAsSkill)}
                style={{ accentColor: 'var(--highlight)', width: 16, height: 16 }}
              />
              Clone as Skill
            </label>
          )}
        </div>
      </div>

      <div style={{ ...styles.field, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
        <label style={{ ...styles.label, marginBottom: 12 }}>Deployment Configuration</label>
        <div style={{ display: 'flex', gap: 16 }}>
          <div style={{ flex: '1 1 180px' }}>
            <label style={styles.label}>Device</label>
            <input
              style={styles.input}
              value={device}
              onChange={e => setDevice(e.target.value)}
              placeholder="* = all devices"
            />
          </div>
          <div style={{ flex: '2 1 280px' }}>
            <label style={styles.label}>Repo</label>
            <input
              style={{ ...styles.input, fontFamily: 'var(--mono)', borderColor: isValidRepo(repo) ? undefined : 'var(--highlight)' }}
              value={repo}
              onChange={e => setRepo(e.target.value)}
              placeholder="* = global, or /absolute/path"
            />
            {!isValidRepo(repo) && <span style={{ fontSize: 11, color: 'var(--highlight)', marginTop: 2, display: 'block' }}>Must be * or an absolute path</span>}
          </div>
        </div>
      </div>

      <div style={styles.field}>
        <label style={styles.label}>
          {isMarkdownType(type) ? 'Body' : 'Configuration (JSON)'}
        </label>
        {isMarkdownType(type) ? (
          <div data-color-mode="dark">
            <MarkdownEditor
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
