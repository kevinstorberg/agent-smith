import { useRef, useState } from 'react';
import { api, type ActionItemEpic } from '../api';
import { EpicNameForm } from '../components/ActionItemEpicControls';
import { ButtonLink } from '../components/ButtonLink';
import { FilterBar } from '../components/FilterBar';
import { ScrollableTable } from '../components/ScrollableTable';
import { DateCell } from '../components/table';
import { useActionItemWrites } from '../hooks/useActionItemWrites';
import { useApiRead } from '../hooks/useApiRead';
import { epicOptionLabel } from '../utils/actionItemEpics';
import './epics.css';

export function EpicsIndexPage() {
  const catalog = useApiRead(api.actionItemEpics.list);
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<ActionItemEpic | null>(null);
  const [error, setError] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const view = `epics:${query}`;
  const {
    busy,
    writing,
    focus: focusRef,
    runWrite,
  } = useActionItemWrites({
    refresh: catalog.refresh,
    view,
    paused: editing !== null,
    canStart: () => Boolean(catalog.data && !catalog.loading && !catalog.error),
    onError: setError,
    onFinish: () => undefined,
  });
  const epics = catalog.data?.items ?? [];
  const matches = epics.filter((epic) =>
    epicOptionLabel(epic, epics)
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase()),
  );
  const disabled =
    catalog.loading || Boolean(catalog.error) || busy || editing !== null;

  function rememberFocus() {
    focusRef.current = {
      handle:
        document.activeElement instanceof HTMLButtonElement
          ? document.activeElement
          : null,
      fallback: list.current ?? undefined,
      view,
    };
  }
  function cancelEditing() {
    setEditing(null);
    setError(null);
  }
  async function rename(title: string) {
    if (!editing) return false;
    const current = epics.find((epic) => epic.id === editing.id);
    if (!current || current.revision !== editing.revision) {
      setError(
        'This Epic changed. Cancel editing and review it before saving again.',
      );
      return false;
    }
    setError(null);
    const result = await runWrite(
      () =>
        api.actionItemEpics.rename(editing.id, {
          title,
          expected_revision: editing.revision,
        }),
      'Could not rename this Epic.',
      { pendingId: editing.id },
    );
    return Boolean(result);
  }
  async function remove(epic: ActionItemEpic) {
    if (disabled || writing.current) return;
    const label = epicOptionLabel(epic, epics);
    if (
      !window.confirm(
        `Delete Epic “${label}”? Its action items will be kept and moved out of the Epic.`,
      )
    )
      return;
    rememberFocus();
    setError(null);
    await runWrite(
      () =>
        api.actionItemEpics.remove(epic.id, {
          expected_revision: epic.revision,
          cohort: epic.cohort,
        }),
      'Could not delete this Epic.',
      { pendingId: epic.id },
    );
  }

  return (
    <div className="epic-management-page">
      <div className="page-header">
        <h2 className="page-title">Epics</h2>
        <div className="flex-row">
          <ButtonLink to="/action-items">Back to action items</ButtonLink>
          <button
            type="button"
            className="btn"
            disabled={disabled}
            onClick={() => void catalog.refresh()}
          >
            Refresh Epics
          </button>
        </div>
      </div>
      <p className="text-muted">
        Manage all Epics. Deleting an Epic keeps its action items and moves them
        out.
      </p>
      {error && <p role="alert">{error}</p>}
      {catalog.error && (
        <div className="card" role="alert">
          <p>Could not refresh Epics. {catalog.error}</p>
          <button
            type="button"
            className="btn"
            disabled={busy || catalog.loading}
            onClick={() => void catalog.refresh()}
          >
            Retry
          </button>
        </div>
      )}
      {editing && (
        <section className="card" aria-label={`Rename Epic ${editing.title}`}>
          <h3>Rename {epicOptionLabel(editing, epics)}</h3>
          <EpicNameForm
            key={`${editing.id}:${editing.revision}`}
            initial={editing.title}
            busy={busy}
            onSave={rename}
            onCancel={cancelEditing}
          />
        </section>
      )}
      <FilterBar
        nameValue={query}
        onNameChange={setQuery}
        nameLabel="Search Epics"
        namePlaceholder="Search Epic names…"
        disabled={busy || editing !== null}
      />
      {busy && <p role="status">Saving Epic…</p>}
      {!catalog.data && catalog.loading && (
        <p className="loading">Loading Epics…</p>
      )}
      {catalog.data && (
        <p className="text-muted-sm" role="status">
          Showing {matches.length} of {epics.length} Epics
        </p>
      )}
      <div ref={list} tabIndex={-1}>
        <ScrollableTable
          label="Epic management"
          tableLabel="Epics"
          className="epics-table"
          busy={catalog.loading || busy}
          emptyState={
            catalog.data && !catalog.error && !matches.length ? (
              <p className="loading">
                {query.trim()
                  ? 'No Epics match your search.'
                  : 'No Epics yet. Create an Epic from Action Items.'}
              </p>
            ) : undefined
          }
        >
          <colgroup>
            <col />
            <col className="epic-count-column" />
            <col className="epic-count-column" />
            <col className="epic-date-column" />
            <col className="epic-actions-column" />
          </colgroup>
          <thead>
            <tr>
              {['Name', 'Open', 'Total', 'Updated', 'Actions'].map((name) => (
                <th key={name} scope="col">
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matches.map((epic) => {
              const label = epicOptionLabel(epic, epics);
              return (
                <tr key={epic.id}>
                  <td>{label}</td>
                  <td>{epic.open_count}</td>
                  <td>{epic.total_count ?? '—'}</td>
                  <td>
                    <DateCell date={epic.updated_at} />
                  </td>
                  <td>
                    <div className="flex-row">
                      <button
                        type="button"
                        className="btn btn-sm"
                        aria-label={`Rename Epic ${label}`}
                        disabled={disabled}
                        onClick={() => {
                          rememberFocus();
                          setError(null);
                          setEditing(epic);
                        }}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        aria-label={`Delete Epic ${label}`}
                        disabled={disabled}
                        onClick={() => void remove(epic)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </ScrollableTable>
      </div>
    </div>
  );
}
