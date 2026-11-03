import type { CSSProperties } from 'react';
import { useAssignableAgents } from '../hooks/useAssignableAgents';

interface AgentCheckboxesProps {
  selected: string[];
  onToggle: (agent: string) => void;
  labelStyle?: CSSProperties;
  checkboxStyle?: CSSProperties;
}

export function AgentCheckboxes({ selected, onToggle, labelStyle, checkboxStyle }: AgentCheckboxesProps) {
  const { agents, virtual_agents } = useAssignableAgents();

  const renderCheckbox = (agent: string, isVirtual: boolean) => (
    <label key={agent} className="checkbox-label agent-checkbox-label" style={labelStyle}>
      <input
        type="checkbox"
        className="form-checkbox"
        checked={selected.includes(agent)}
        onChange={() => onToggle(agent)}
        style={checkboxStyle}
      />
      <span className="agent-checkbox-name">{agent}{isVirtual && <span className="text-muted"> (graph)</span>}</span>
    </label>
  );

  return (
    <>
      {agents.map(a => renderCheckbox(a, false))}
      {virtual_agents.map(a => renderCheckbox(a, true))}
    </>
  );
}
