import { useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import { api } from '../api';
import type { Rule, Skill, McpServer } from '../api';

type SubTab = 'rules' | 'skills' | 'mcp';

export function HarnessPage() {
  const [subTab, setSubTab] = useState<SubTab>('rules');
  const [rules, setRules] = useState<Rule[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [mcp, setMcp] = useState<McpServer[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    api.harness.rules().then(setRules);
    api.harness.skills().then(setSkills);
    api.harness.mcp().then(setMcp);
  }, []);

  return (
    <div>
      <div className="sub-tabs">
        {(['rules', 'skills', 'mcp'] as SubTab[]).map((t) => (
          <button key={t} className={t === subTab ? 'active' : ''} onClick={() => setSubTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)} ({t === 'rules' ? rules.length : t === 'skills' ? skills.length : mcp.length})
          </button>
        ))}
      </div>

      {subTab === 'rules' && (
        <div>
          {rules.map((r) => (
            <div key={r.name} className="card">
              <h3
                style={{ cursor: 'pointer' }}
                onClick={() => setExpanded(expanded === r.name ? null : r.name)}
              >
                {expanded === r.name ? '▾' : '▸'} {r.name}
              </h3>
              {expanded === r.name && (
                <div className="markdown-content">
                  <Markdown>{r.content}</Markdown>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {subTab === 'skills' && (
        <div className="card-grid">
          {skills.map((s) => (
            <div key={s.name} className="card">
              <h3>{s.name}</h3>
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                {s.files.length} file{s.files.length !== 1 ? 's' : ''}
              </div>
            </div>
          ))}
        </div>
      )}

      {subTab === 'mcp' && (
        <div className="card-grid">
          {mcp.map((m) => (
            <div key={m.name} className="card">
              <h3>{m.name}</h3>
              <pre>{JSON.stringify(m.config, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
