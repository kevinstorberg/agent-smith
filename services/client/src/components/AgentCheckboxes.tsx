import type { CSSProperties } from 'react';
import { useAssignableAgents } from '../hooks/useAssignableAgents';

interface AgentCheckboxesProps {
  selected: string[];
  onToggle: (agent: string) => void;
  labelStyle: CSSProperties;
  checkboxStyle: CSSProperties;
}

export function AgentCheckboxes({ selected, onToggle, labelStyle, checkboxStyle }: AgentCheckboxesProps) {
  const { agents, virtual_agents } = useAssignableAgents();

  const renderCheckbox = (agent: string, isVirtual: boolean) => (
    <label key={agent} style={labelStyle}>
      <input
        type="checkbox"
        checked={selected.includes(agent)}
        onChange={() => onToggle(agent)}
        style={checkboxStyle}
      />
      {agent}
      {isVirtual && <span style={{ color: 'var(--text-muted)' }}>(graph)</span>}
    </label>
  );

  return (
    <>
      {agents.map(a => renderCheckbox(a, false))}
      {virtual_agents.length > 0 && <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>|</span>}
      {virtual_agents.map(a => renderCheckbox(a, true))}
    </>
  );
}
