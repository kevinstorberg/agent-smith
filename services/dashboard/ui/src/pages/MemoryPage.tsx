import { useState } from 'react';
import { api } from '../api';
import type { MemoryItem } from '../api';

export function MemoryPage() {
  const [query, setQuery] = useState('');
  const [repo, setRepo] = useState('');
  const [results, setResults] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'search' | 'list'>('list');

  const runQuery = async (fn: () => Promise<MemoryItem[]>, queryMode: 'search' | 'list') => {
    setLoading(true);
    try {
      setResults(await fn());
      setMode(queryMode);
    } catch {
      setResults([]);
    }
    setLoading(false);
  };

  const doSearch = () => {
    if (!query.trim()) return;
    runQuery(() => api.memory.search(query, repo), 'search');
  };

  const doList = () => runQuery(() => api.memory.list(repo), 'list');

  return (
    <div>
      <div className="search-bar">
        <input
          placeholder="Semantic search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && doSearch()}
        />
        <input
          placeholder="Repo filter"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          style={{ width: 150 }}
        />
        <button className="sub-tabs" onClick={doSearch} style={{ padding: '8px 16px', cursor: 'pointer', background: 'var(--accent)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          Search
        </button>
        <button onClick={doList} style={{ padding: '8px 16px', cursor: 'pointer', background: 'var(--surface)', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
          List All
        </button>
      </div>

      {loading && <div className="loading">Loading...</div>}

      {!loading && results.length === 0 && (
        <div className="loading">
          {mode === 'search' ? 'No results' : 'Click "List All" to browse memories'}
        </div>
      )}

      {results.map((m) => (
        <div key={m.id} className="card">
          <div style={{ marginBottom: 8 }}>{m.content}</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {m.repo && <span className="tag">{m.repo}</span>}
            {m.tags?.map((t) => <span key={t} className="tag">{t}</span>)}
            {m.created_at && (
              <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 'auto' }}>
                {new Date(m.created_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
