import { useId } from 'react';
import { ALL_AGENTS, toggleArrayItem, isValidRepo } from '../constants';
import { AgentCheckboxes } from './AgentCheckboxes';

interface ConfigFormProps {
  title?: string;
  device: string;
  repo: string;
  agents: string[];
  subagents: string[];
  enabled: boolean;
  exclude: boolean;
  saving: boolean;
  onDeviceChange: (v: string) => void;
  onRepoChange: (v: string) => void;
  onAgentsChange: (v: string[]) => void;
  onSubagentsChange: (v: string[]) => void;
  onEnabledChange: (v: boolean) => void;
  onExcludeChange: (v: boolean) => void;
  onSave: () => void;
  onCancel: () => void;
  submitLabel?: string;
}

export function ConfigForm({
  title,
  device, repo, agents, subagents, enabled, exclude, saving,
  onDeviceChange, onRepoChange, onAgentsChange, onSubagentsChange, onEnabledChange, onExcludeChange,
  onSave, onCancel,
  submitLabel = 'Save',
}: ConfigFormProps) {
  const id = useId();
  const validRepo = isValidRepo(repo);
  const toggleAgent = (agent: string) => onAgentsChange(toggleArrayItem(agents, agent));
  const toggleSubagent = (agent: string) => onSubagentsChange(toggleArrayItem(subagents, agent));

  return <fieldset className="config-form" disabled={saving} aria-busy={saving}>
    <legend className="form-label">{title || 'Deployment configuration'}</legend>
    <div className="form-grid">
      <label><span className="form-label">Device</span>
        <input className="input" value={device} onChange={event => onDeviceChange(event.target.value)} placeholder="* = all devices" />
      </label>
      <div><label><span className="form-label">Repository</span>
        <input className="input" value={repo} onChange={event => onRepoChange(event.target.value)} placeholder="* = global, or /absolute/path"
          aria-invalid={!validRepo} aria-describedby={!validRepo ? `${id}-repo-error` : undefined} /></label>
        {!validRepo && <span className="field-error" id={`${id}-repo-error`}>Must be * or an absolute path</span>}
      </div>
    </div>
    <fieldset className="form-group"><legend className="form-label">Agents</legend>
      <div className="choice-row"><AgentCheckboxes selected={agents} onToggle={toggleAgent} /></div>
    </fieldset>
    <fieldset className="form-group"><legend className="form-label">Subagents (optional)</legend>
      <div className="choice-row">{ALL_AGENTS.map(agent => <label key={agent} className="checkbox-label">
        <input type="checkbox" className="form-checkbox" checked={subagents.includes(agent)} onChange={() => toggleSubagent(agent)} />{agent}
      </label>)}</div>
    </fieldset>
    <div className="choice-row config-options">
      <label className="checkbox-label"><input type="checkbox" className="form-checkbox" checked={enabled} onChange={() => onEnabledChange(!enabled)} />Enabled</label>
      <fieldset className="form-group"><legend className="form-label">Deployment mode</legend>
        <div className="choice-row">
          <label className="checkbox-label"><input type="radio" className="form-radio" name={`${id}-mode`} checked={!exclude} onChange={() => onExcludeChange(false)} />Include</label>
          <label className="checkbox-label"><input type="radio" className="form-radio" name={`${id}-mode`} checked={exclude} onChange={() => onExcludeChange(true)} />Exclude</label>
        </div>
      </fieldset>
    </div>
    <div className="flex-wrap">
      <button type="button" className="btn btn-primary btn-sm" onClick={onSave} disabled={!validRepo}>{saving ? 'Saving...' : submitLabel}</button>
      <button type="button" className="btn btn-sm" onClick={onCancel}>Cancel</button>
    </div>
  </fieldset>;
}
