import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api';
import type { ProfileRevision } from '../api';
import { usePagination } from '../hooks/usePagination';
import { useApiRead } from '../hooks/useApiRead';
import { Pagination } from './Pagination';
import { DateCell } from './table';
import { ContentDiff } from './ContentDiff';
import { CODE_BOX } from './codeBox';
import { profileChanges } from '../utils/profileChanges';
import { usePolling } from '../hooks/usePolling';
import ReactMarkdown from 'react-markdown';

export function ProfileHistory({ profileId, revision, onViewEvidence, evidenceHref = '#profile-evidence', legacyRelationships }: { profileId: string; revision: number; onViewEvidence?: () => void; evidenceHref?: string; legacyRelationships?: { text: string; human: boolean } }) {
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mode, setMode] = useState<'changes' | 'before' | 'after'>('changes');
  const list = usePagination<ProfileRevision>((limit, offset) => open ? api.profiles.history(profileId, { limit, offset }) : Promise.resolve({ items: [], total: 0 }), [profileId, revision, open]);
  const read = useCallback(() => open && selectedId !== null ? api.profiles.historyOne(profileId, selectedId) : Promise.resolve(null), [profileId, selectedId, open]);
  const detail = useApiRead(read);
  usePolling(() => { list.refresh({ showLoading: false }); if (selectedId !== null) detail.refresh({ showLoading: false }); }, { enabled: open });
  const changes = detail.data ? profileChanges(detail.data) : null;
  return <details className="card" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>History</summary>
    {open && <>
      {legacyRelationships && <details className="profile-legacy-assessment"><summary>Previous combined relationship assessment</summary>
        <p className="text-muted-sm">This earlier assessment combined multiple relationships. Current assessments are shown per person in Relationships.</p>
        {legacyRelationships.text ? <div className="markdown-content"><ReactMarkdown>{legacyRelationships.text}</ReactMarkdown></div>
          : <p className="text-muted-sm">{legacyRelationships.human ? 'You previously kept this assessment empty.' : 'This earlier assessment is empty.'}</p>}
      </details>}
      {list.loading && <p className="text-muted-sm">Loading history...</p>}
      {list.error && <p role="alert">Could not load history. <button className="btn btn-sm" onClick={() => list.refresh()}>Retry history</button></p>}
      {!list.loading && !list.error && list.total === 0 && <p className="text-muted-sm">No changes recorded yet.</p>}
      {!list.loading && !list.error && list.items.map(change => <article key={change.id} className="relationship-row">
        <div className="flex-wrap" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
          <div><strong>Revision {change.base_revision} → {change.new_revision}</strong><div className="text-muted-sm">{change.actor === 'agent' ? 'Automatic update' : change.actor === 'human' ? 'Edited by you' : 'System update'} · <DateCell date={change.created_at} /></div></div>
          <button className="btn btn-sm" onClick={() => { setSelectedId(change.id); setMode('changes'); }}>View change #{change.id}</button>
        </div>
        {change.source === 'meeting' && change.source_id && <Link className="text-link" to={`/meetings/${change.source_id}`}>Source meeting</Link>}
      </article>)}
      {!list.loading && !list.error && list.total > 0 && <Pagination total={list.total} limit={list.limit} offset={list.offset}
        onPageChange={list.setOffset} onLimitChange={value => { list.setLimit(value); list.setOffset(0); }} />}
      {selectedId !== null && <section aria-label={`Profile change ${selectedId}`} style={{ marginTop: 16 }}>
        <div className="page-header profiles-header"><h3 className="section-title">Change #{selectedId}</h3><button className="btn btn-sm" onClick={() => setSelectedId(null)}>Close change</button></div>
        {detail.loading && <p>Loading change...</p>}
        {detail.error && <p role="alert">Could not load this change. <button className="btn btn-sm" onClick={() => detail.refresh()}>Retry change</button></p>}
        {!detail.loading && !detail.error && detail.data?.id === selectedId && <>
          {detail.data.source_restricted && <p className="text-muted-sm">Some generated content is hidden because its source evidence or participant attribution changed.</p>}
          <div className="sub-tabs">{(['changes', 'before', 'after'] as const).map(value => <button key={value} className={mode === value ? 'active' : ''} onClick={() => setMode(value)}>{value === 'changes' ? 'Changes' : value === 'before' ? 'Before' : 'After'}</button>)}</div>
          {changes?.fields.map(field => <section key={field.key} style={{ marginTop: 12 }}>
            <h4 style={{ marginBottom: 8 }}>{field.label}</h4>
            {mode === 'changes' ? <ContentDiff before={field.before} after={field.after} /> : <pre style={CODE_BOX}>{field[mode] || 'Empty'}</pre>}
          </section>)}
          {changes?.evidence && <p style={{ marginTop: 12 }}>Observations: {changes.evidence}. <Link className="text-link" to={evidenceHref} onClick={onViewEvidence}>View supporting evidence</Link></p>}
          {changes?.relationships && <p style={{ marginTop: 12 }}>Relationships updated. Review current assessments in the Relationships tab.</p>}
          {changes?.fields.length === 0 && !changes.evidence && !changes.relationships && !detail.data.source_restricted && <p className="text-muted-sm" style={{ marginTop: 12 }}>Supporting context updated. No profile text changed.</p>}
        </>}
      </section>}
    </>}
  </details>;
}
