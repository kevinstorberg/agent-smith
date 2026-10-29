import { useState, useMemo } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { MemoryItem } from '../api';
import { Pagination } from '../components/Pagination';
import { CopyButton } from '../components/CopyButton';
import { useNotification } from '../context/useNotification';
import { usePolling } from '../hooks/usePolling';
import { usePagination } from '../hooks/usePagination';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { parseTags } from '../utils/tags';

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
  const [filterRepo, setFilterRepo] = useState('');
  const [filterTags, setFilterTags] = useState('');
  const [listSort, setListSort] = useState('created_at_desc');
  const [searchSort, setSearchSort] = useState('relevance');
  const [meetingsOnly, setMeetingsOnly] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editRepo, setEditRepo] = useState('');
  const [editTags, setEditTags] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const debouncedQuery = useDebouncedValue(query.trim());
  const searchTerm = query.trim() ? debouncedQuery : '';
  const repo = useDebouncedValue(filterRepo.trim());
  const tagText = useDebouncedValue(filterTags);
  const tagsArray = useMemo(() => parseTags(tagText), [tagText]);
  const mode = searchTerm ? 'search' : 'list';
  const sort = mode === 'search' ? searchSort : listSort;
  const sortOptions = mode === 'search' ? SEARCH_SORT_OPTIONS : LIST_SORT_OPTIONS;

  const { items, total, loading, error, refresh, limit, offset, setLimit, setOffset } = usePagination<MemoryItem>((limit, offset) => {
    const opts = {
      limit,
      offset,
      meeting_only: meetingsOnly,
      ...(repo ? { repo } : {}),
      ...(tagsArray.length ? { tags: tagsArray } : {}),
      ...(sort ? { sort } : {}),
    };
    return searchTerm
      ? api.memory.search(searchTerm, opts)
      : api.memory.list(opts);
  }, [searchTerm, meetingsOnly, repo, tagsArray, sort]);

  usePolling(
    () => refresh({ showLoading: false }),
    { enabled: !editingId && !saving && !confirmDeleteId },
  );

  const onSortChange = (value: string) => { if (mode === 'search') setSearchSort(value); else setListSort(value); };

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
      const tags = parseTags(editTags);
      await api.memory.update(id, {
        content: editContent,
        repo: editRepo || undefined,
        tags: tags.length ? tags : undefined,
      });
      setEditingId(null);
      await refresh();
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
      await refresh();
    } catch (err) {
      notify(`Delete failed: ${err instanceof Error ? err.message : String(err)}`, 'error');
    }
    setSaving(false);
  };


  return (
    <div className="memory-page">
      <h2 className="page-title" style={{ marginBottom: 16 }}>Memory</h2>

      <div className="search-bar">
        <input
          placeholder="Semantic search..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        {query && (
          <button className="btn" onClick={() => setQuery('')}>Clear</button>
        )}
      </div>

      <div className="search-bar" style={{ marginTop: 8 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={meetingsOnly} onChange={event => { setMeetingsOnly(event.target.checked); setOffset(0); }} />
          Meetings only
        </label>
        <input
          className="input"
          placeholder="Filter by repo"
          value={filterRepo}
          onChange={e => setFilterRepo(e.target.value)}
        />
        <input
          className="input"
          placeholder="Filter by tags (comma-separated)"
          value={filterTags}
          onChange={e => setFilterTags(e.target.value)}
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
      {error && <div role="alert" className="card">
        Could not load memories. <button className="btn btn-sm" onClick={() => refresh()}>Retry</button>
      </div>}

      {!loading && !error && items.length === 0 && (
        <div className="loading">
          {mode === 'search'
            ? 'No results found'
            : (meetingsOnly || filterRepo || tagsArray.length > 0)
              ? 'No memories match the current filters'
              : 'No memories yet'}
        </div>
      )}

      {!loading && !error && items.map(item => {
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
              {item.from_meeting && <span className="tag tag-info">Meeting</span>}
              {item.from_meeting && item.source_id && <Link className="text-muted-sm" to={`/meetings/${encodeURIComponent(item.source_id)}`}>Source meeting</Link>}
              {item.repo && <span className="tag tag-info">{item.repo}</span>}
              {item.context_tags?.filter(tag => !item.tags?.includes(tag)).map(tag => <span key={`context-${tag}`} className="tag" title="Meeting topic">{tag}</span>)}
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

      {!loading && !error && (
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
