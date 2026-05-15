import { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../api';
import type { MemoryItem } from '../api';
import { Pagination } from '../components/Pagination';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';

type Mode = 'list' | 'search';

const LIST_SORT_OPTIONS = [
  { value: 'created_at_desc', label: 'Newest first' },
  { value: 'created_at_asc', label: 'Oldest first' },
  { value: 'updated_at_desc', label: 'Recently updated' },
  { value: 'updated_at_asc', label: 'Least recently updated' },
];

const SEARCH_SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance' },
  ...LIST_SORT_OPTIONS,
];

export function MemoryPage() {
  const { notify } = useNotification();
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<Mode>('list');
  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [filterRepo, setFilterRepo] = useState('');
  const [filterTags, setFilterTags] = useState('');
  const [sort, setSort] = useState('created_at_desc');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editRepo, setEditRepo] = useState('');
  const [editTags, setEditTags] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const tagsArray = useMemo(
    () => filterTags.split(',').map(t => t.trim()).filter(Boolean),
    [filterTags],
  );
  const sortOptions = mode === 'search' ? SEARCH_SORT_OPTIONS : LIST_SORT_OPTIONS;

  const fetchData = useCallback(async () => {
    setLoading(true);
    const opts = {
      limit,
      offset,
      ...(filterRepo ? { repo: filterRepo } : {}),
      ...(tagsArray.length ? { tags: tagsArray } : {}),
      ...(sort ? { sort } : {}),
    };
    try {
      const res = mode === 'search' && query.trim()
        ? await api.memory.search(query, opts)
        : await api.memory.list(opts);
      setItems(res.items);
      setTotal(res.total);
    } catch {
      setItems([]);
      setTotal(0);
    }
    setLoading(false);
  }, [mode, query, limit, offset, filterRepo, tagsArray, sort]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const onFilterRepoChange = (v: string) => { setFilterRepo(v); setOffset(0); };
  const onFilterTagsChange = (v: string) => { setFilterTags(v); setOffset(0); };
  const onSortChange = (v: string) => { setSort(v); setOffset(0); };

  const doSearch = () => {
    if (!query.trim()) return;
    setMode('search');
    setSort('relevance');
    setOffset(0);
  };

  const clearSearch = () => {
    setQuery('');
    setMode('list');
    setSort('created_at_desc');
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
      <h2 className="page-title" style={{ marginBottom: 16 }}>Memory</h2>

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

      <div className="search-bar" style={{ marginTop: 8 }}>
        <input
          className="input"
          placeholder="Filter by repo"
          value={filterRepo}
          onChange={e => onFilterRepoChange(e.target.value)}
        />
        <input
          className="input"
          placeholder="Filter by tags (comma-separated)"
          value={filterTags}
          onChange={e => onFilterTagsChange(e.target.value)}
        />
        <label htmlFor="memory-sort" style={{ fontSize: 12, color: 'var(--text-muted)' }}>Sort</label>
        <select
          id="memory-sort"
          aria-label="Sort"
          className="pagination-select"
          value={sort}
          onChange={e => onSortChange(e.target.value)}
        >
          {sortOptions.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {tagsArray.length > 0 && (
        <div className="text-muted-sm" style={{ marginTop: 4 }}>
          Tag filter (AND): {tagsArray.join(' + ')}
        </div>
      )}

      {loading && <div className="loading">Loading...</div>}

      {!loading && items.length === 0 && (
        <div className="loading">
          {mode === 'search'
            ? 'No results found'
            : (filterRepo || tagsArray.length > 0)
              ? 'No memories match the current filters'
              : 'No memories yet'}
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
                <div style={{ marginBottom: 8, fontSize: 13, lineHeight: 1.6 }}>
                  {item.content}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: isEditing ? 12 : 0 }}>
              {item.repo && <span className="tag tag-info">{item.repo}</span>}
              {item.tags?.map(t => <span key={t} className="tag">{t}</span>)}
              {item.created_at && (
                <span className="text-muted-sm">
                  {new Date(item.created_at).toLocaleString()}
                </span>
              )}
              {!isEditing && (
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                  <CopyButton text={item.content} className="btn-sm" />
                  <button className="btn btn-sm" onClick={e => { e.stopPropagation(); startEdit(item); }}>Edit</button>
                  {confirmDeleteId === item.id ? (
                    <>
                      <span style={{ color: 'var(--warning)', fontSize: 12, alignSelf: 'center' }}>Delete?</span>
                      <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); deleteMemory(item.id); }} disabled={saving}>
                        {saving ? '...' : 'Yes'}
                      </button>
                      <button className="btn btn-sm" onClick={e => { e.stopPropagation(); setConfirmDeleteId(null); }}>No</button>
                    </>
                  ) : (
                    <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); setConfirmDeleteId(item.id); }}>Delete</button>
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
