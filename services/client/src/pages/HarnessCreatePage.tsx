import { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import { useNotification } from '../context/useNotification';
import { ALL_AGENTS, TYPE_PATHS, TYPE_LABELS, isMarkdownType, toggleArrayItem, formatError, MAX_NAME_LENGTH, nameError, isValidRepo } from '../constants';
import { AgentCheckboxes } from '../components/AgentCheckboxes';
import { FieldError } from '../components/FieldError';
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
      notify('Repository must be * or an absolute path.', 'error');
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
        <Link className="detail-back" to={backPath}>
          &larr; Back to {TYPE_PATHS[type] || type}
        </Link>
      </div>

      <h2 className="page-title" style={{ marginBottom: 20 }}>
        New {TYPE_LABELS[type] || type}
      </h2>

      <div style={styles.field}>
        <label className="form-label" htmlFor="harness-name">Name</label>
        <input
          id="harness-name" className="input" aria-invalid={Boolean(name && nameError(name))} aria-describedby={name && nameError(name) ? "harness-name-error" : undefined}
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={`e.g. ${type === 'tool' ? 'my_api' : type === 'hook' ? 'lint_on_save' : 'my_new_' + type}`}
          maxLength={MAX_NAME_LENGTH}
        />
        <FieldError id="harness-name-error" error={name ? nameError(name) : null} maxLength={MAX_NAME_LENGTH} currentLength={name.length} />
      </div>

      <div className="form-grid" style={styles.field}>
        <div>
          <label className="form-label" htmlFor="harness-project">Project</label>
          <input
            id="harness-project" className="input"
            value={project}
            onChange={e => setProject(e.target.value)}
            placeholder="Empty = shared/global"
          />
        </div>
        <div>
          <label className="form-label" htmlFor="harness-sort">Sort Order</label>
          <input
            type="number"
            min={0}
            id="harness-sort" className="input"
            value={sortKey}
            onChange={e => setSortKey(e.target.value)}
            placeholder="e.g. 5"
          />
        </div>
      </div>

      <fieldset className="form-group" disabled={saving}>
        <legend className="form-label">Agents</legend>
        <div style={styles.checkboxRow}>
          <AgentCheckboxes
            selected={agents}
            onToggle={toggleAgent}
          />
        </div>
      </fieldset>

      <div style={styles.field}>
        <div style={styles.checkboxRow}>
          <label style={styles.checkboxLabel}>
            <input
              type="checkbox"
                className="form-checkbox"
              checked={enabled}
              onChange={() => setEnabled(!enabled)}
            />
            Enabled
          </label>
          {type === 'rule' && (
            <label style={styles.checkboxLabel}>
              <input
                type="checkbox"
                className="form-checkbox"
                checked={cloneAsSkill}
                onChange={() => setCloneAsSkill(!cloneAsSkill)}
              />
              Clone as Skill
            </label>
          )}
        </div>
      </div>

      <div style={{ ...styles.field, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
        <h3 className="section-title">Deployment configuration</h3>
        <div className="form-grid">
          <div>
            <label className="form-label" htmlFor="harness-device">Device</label>
            <input
              id="harness-device" className="input"
              value={device}
              onChange={e => setDevice(e.target.value)}
              placeholder="* = all devices"
            />
          </div>
          <div>
            <label className="form-label" htmlFor="harness-repo">Repository</label>
            <input
              id="harness-repo" className="input" aria-invalid={!isValidRepo(repo)} aria-describedby={!isValidRepo(repo) ? "harness-repo-error" : undefined}
              value={repo}
              onChange={e => setRepo(e.target.value)}
              placeholder="* = global, or /absolute/path"
            />
            {!isValidRepo(repo) && <span id="harness-repo-error" className="field-error">Must be * or an absolute path</span>}
          </div>
        </div>
      </div>

      <div style={styles.field}>
        <label className="form-label" htmlFor="harness-body">
          {isMarkdownType(type) ? 'Body' : 'Configuration (JSON)'}
        </label>
        {isMarkdownType(type) ? (
          <div data-color-mode="dark">
            <MDEditor
              textareaProps={{ id: "harness-body", "aria-label": "Body" }}
              value={body}
              onChange={val => setBody(val || '')}
              height={400}
            />
          </div>
        ) : (
          <textarea
            id="harness-body" style={styles.textarea}
            value={metadataJson}
            onChange={e => setMetadataJson(e.target.value)}
            spellCheck={false}
          />
        )}
      </div>

      <div style={styles.actions}>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Creating...' : `Create ${TYPE_LABELS[type] || type}`}
        </button>
        <button className="btn" disabled={saving} onClick={() => navigate(backPath)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
