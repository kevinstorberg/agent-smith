import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { MemoryItem } from '../api';
import { Pagination } from '../components/Pagination';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';

type Mode = 'list' | 'search';

export function MemoryPage() {
  const { notify } = useNotification();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<Mode>('list');
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editRepo, setEditRepo] = useState('');
  const [editTags, setEditTags] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = mode === 'search' && query.trim()
        ? await api.memory.search(query, { limit, offset })
        : await api.memory.list({ limit, offset });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      setItems([]);
      setTotal(0);
    }
    setLoading(false);
  }, [mode, query, limit, offset]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const doSearch = () => {
    if (!query.trim()) return;
    setMode('search');
    setOffset(0);
  };

  const clearSearch = () => {
    setQuery('');
    setMode('list');
    setOffset(0);
  };

  const startEdit = (item: MemoryItem) => {
    setEditingId(item.id);
    setEditContent(item.content);
    setEditRepo(item.repo || '');
    setEditTags(item.tags?.join(', ') || '');
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const saveEdit = async (id: string) => {
    setSaving(true);
    try {
      const tags = editTags.split(',').map(t => t.trim()).filter(Boolean);
      await api.memory.update(id, {
        content: editContent,
        repo: editRepo || undefined,
        tags: tags.length ? tags : undefined,
      });
      setEditingId(null);
      await fetchData();
    } catch (err) {
      notify(`Save failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
    setSaving(false);
  };

  const deleteMemory = async (id: string) => {
    setSaving(true);
    try {
      await api.memory.remove(id);
      setConfirmDeleteId(null);
      await fetchData();
    } catch (err) {
      notify(`Delete failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
    setSaving(false);
  };


  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Memory</h2>

      <div className="search-bar">
        <input
          placeholder="Semantic search..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && doSearch()}
        />
        <button className="btn btn-primary" onClick={doSearch}>Search</button>
        {mode === 'search' && (
          <button className="btn" onClick={clearSearch}>Clear</button>
        )}
      </div>

      {loading && <div className="loading">Loading...</div>}

      {!loading && items.length === 0 && (
        <div className="loading">
          {mode === 'search' ? 'No results found' : 'No memories yet'}
        </div>
      )}

      {!loading && items.map(item => {
        const isEditing = editingId === item.id;

        return (
          <div key={item.id} className="card">
            <div>
              {isEditing ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const }}>Content</label>
                  <textarea
                    style={{
                      background: 'var(--bg)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)',
                      color: 'var(--text)',
                      padding: 10,
                      fontFamily: 'var(--font)',
                      fontSize: 13,
                      width: '100%',
                      minHeight: 120,
                      resize: 'vertical',
                    }}
                    value={editContent}
                    onChange={e => setEditContent(e.target.value)}
                    onClick={e => e.stopPropagation()}
                  />
                  <div style={{ display: 'flex', gap: 12 }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, display: 'block', marginBottom: 4 }}>Repo</label>
                      <input
                        className="input"
                        value={editRepo}
                        onChange={e => setEditRepo(e.target.value)}
                        placeholder="e.g. agent-smith"
                        onClick={e => e.stopPropagation()}
                      />
                    </div>
                    <div style={{ flex: 2 }}>
                      <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-muted)', textTransform: 'uppercase' as const, display: 'block', marginBottom: 4 }}>Tags (comma-separated)</label>
                      <input
                        className="input"
                        value={editTags}
                        onChange={e => setEditTags(e.target.value)}
                        placeholder="e.g. architecture, convention"
                        onClick={e => e.stopPropagation()}
                      />
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    <button className="btn btn-success" onClick={e => { e.stopPropagation(); saveEdit(item.id); }} disabled={saving}>
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button className="btn" onClick={e => { e.stopPropagation(); cancelEdit(); }}>Cancel</button>
                  </div>
                </div>
              ) : (
                <div style={{ marginBottom: 8, fontSize: 13, lineHeight: 1.6, position: 'relative' }}>
                  <CopyButton text={item.content} style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }} />
                  <div style={{ paddingRight: 60 }}>
                    {item.content}
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: isEditing ? 12 : 0 }}>
              {item.repo && <span className="tag" style={{ background: 'rgba(91,141,239,0.15)', color: 'var(--info)', borderColor: 'rgba(91,141,239,0.3)' }}>{item.repo}</span>}
              {item.tags?.map(t => <span key={t} className="tag">{t}</span>)}
              {item.created_at && (
                <span className="text-muted-sm">
                  {new Date(item.created_at).toLocaleString()}
                </span>
              )}
              {!isEditing && (
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  <button className="btn" style={{ fontSize: 11, padding: '3px 10px' }} onClick={e => { e.stopPropagation(); startEdit(item); }}>Edit</button>
                  {confirmDeleteId === item.id ? (
                    <>
                      <span style={{ color: 'var(--warning)', fontSize: 12, alignSelf: 'center' }}>Delete?</span>
                      <button className="btn btn-danger" style={{ fontSize: 11, padding: '3px 10px' }} onClick={e => { e.stopPropagation(); deleteMemory(item.id); }} disabled={saving}>
                        {saving ? '...' : 'Yes'}
                      </button>
                      <button className="btn" style={{ fontSize: 11, padding: '3px 10px' }} onClick={e => { e.stopPropagation(); setConfirmDeleteId(null); }}>No</button>
                    </>
                  ) : (
                    <button className="btn btn-danger" style={{ fontSize: 11, padding: '3px 10px' }} onClick={e => { e.stopPropagation(); setConfirmDeleteId(item.id); }}>Delete</button>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {!loading && (
        <Pagination
          total={total}
          limit={limit}
          offset={offset}
          onPageChange={setOffset}
          onLimitChange={newLimit => { setLimit(newLimit); setOffset(0); }}
        />
      )}
    </div>
  );
}
