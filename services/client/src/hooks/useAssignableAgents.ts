import { useEffect, useState } from 'react';
import { api, type AssignableAgents } from '../api';
import { ALL_AGENTS } from '../constants';

// Fallback while loading or when the API is unreachable. The backend
// (scripts/shared/agents.py) is the source of truth for agent names.
const FALLBACK: AssignableAgents = { agents: [...ALL_AGENTS], virtual_agents: [] };

export function useAssignableAgents(): AssignableAgents {
  const [value, setValue] = useState<AssignableAgents>(FALLBACK);

  useEffect(() => {
    let active = true;
    Promise.resolve()
      .then(() => api.harness.assignableAgents())
      .then(res => {
        if (active) setValue(res);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  return value;
}
