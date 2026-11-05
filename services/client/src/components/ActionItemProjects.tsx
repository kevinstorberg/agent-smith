import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { api } from '../api';
import { useActionItemProjects } from '../hooks/useActionItemProjects';
import { useApiMutation } from '../hooks/useApiMutation';
import {
  newProjectName,
  projectLabel,
  projectScopeKey,
} from '../utils/actionItemProjects';
import type { ProjectScope } from '../utils/actionItemProjects';
import './actionItemProjects.css';

type ProjectCommand =
  | { kind: 'create'; name: string; scope: string }
  | { kind: 'delete'; id: number; scope: string };

export function ActionItemProjectTabs({
  scope,
  onChange,
  disabled = false,
  paused = false,
  toolbarAccessory,
  beforeTabs,
}: {
  scope: ProjectScope;
  onChange: (scope: ProjectScope) => void;
  disabled?: boolean;
  paused?: boolean;
  toolbarAccessory?: ReactNode;
  beforeTabs?: ReactNode;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const currentScope = useRef(projectScopeKey(scope));
  const nameId = useId();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    currentScope.current = projectScopeKey(scope);
  }, [scope]);
  const mutation = useApiMutation({
    mutationFn: async (command: ProjectCommand) => {
      if (command.kind === 'create')
        return {
          command,
          project: await api.actionItemProjects.create(command.name),
        };
      await api.actionItemProjects.remove(command.id);
      return { command, project: null };
    },
    onSuccess: ({ command, project }) => {
      if (!mounted.current) return;
      setNotice(null);
      setCreating(false);
      setName('');
      if (currentScope.current === command.scope)
        onChange(
          project ? { kind: 'named', name: project.name } : { kind: 'all' },
        );
      void catalog.refresh({ showLoading: false });
    },
    onError: (error) => {
      if (mounted.current) setNotice(error.message);
    },
  });
  const catalog = useActionItemProjects(paused || creating || mutation.loading);
  const busy = disabled || mutation.loading;
  const projects = catalog.data?.items ?? [];
  const names = projects.map((project) => project.name);
  if (scope.kind === 'named' && !names.includes(scope.name))
    names.push(scope.name);
  const tabs: { label: string; scope: ProjectScope }[] = [
    { label: 'All projects', scope: { kind: 'all' } },
    { label: 'Unassigned', scope: { kind: 'unassigned' } },
    ...names.map((name) => ({
      label: projectLabel(name),
      scope: { kind: 'named' as const, name },
    })),
  ];
  const selected =
    scope.kind === 'named'
      ? projects.find((project) => project.name === scope.name)
      : undefined;

  function navigateTabs(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : event.key === 'ArrowRight'
            ? (index + 1) % tabs.length
            : event.key === 'ArrowLeft'
              ? (index + tabs.length - 1) % tabs.length
              : null;
    if (next === null || busy) return;
    event.preventDefault();
    const button =
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
        '[role="tab"]',
      )[next];
    button?.focus();
    button?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    onChange(tabs[next].scope);
  }

  return (
    <section className="action-projects" aria-label="Projects">
      <div className="action-projects-toolbar">
        {toolbarAccessory}
        <div
          className="action-projects-heading"
          role="group"
          aria-label="Project management"
        >
          {!toolbarAccessory && <strong>Projects</strong>}
          <button
            className="btn btn-sm"
            disabled={busy}
            onClick={() => {
              setCreating(true);
              setNotice(null);
            }}
          >
            New project
          </button>
          {selected && (
            <button
              className="btn btn-sm"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete project “${projectLabel(selected.name)}”? Only projects without task history can be deleted.`,
                  )
                )
                  void mutation.mutate({
                    kind: 'delete',
                    id: selected.id,
                    scope: projectScopeKey(scope),
                  });
              }}
            >
              Delete project
            </button>
          )}
        </div>
      </div>
      {catalog.loading && !catalog.data && (
        <p role="status">Loading projects…</p>
      )}
      {catalog.error && (
        <div role="alert">
          Could not load projects: {catalog.error}{' '}
          <button
            className="btn btn-sm"
            disabled={busy || catalog.loading}
            onClick={() => void catalog.refresh()}
          >
            Retry projects
          </button>
        </div>
      )}
      {creating && (
        <form
          className="action-project-create"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            const valid = newProjectName(name);
            if (!valid) {
              setNotice(
                'Project name is required, must contain 200 characters or fewer, and cannot contain control characters.',
              );
              return;
            }
            void mutation.mutate({
              kind: 'create',
              name: valid,
              scope: projectScopeKey(scope),
            });
          }}
        >
          <label htmlFor={nameId}>Project name</label>
          <input
            id={nameId}
            className="input"
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
          <button className="btn btn-primary" disabled={busy} type="submit">
            Create project
          </button>
          <button
            className="btn"
            disabled={busy}
            type="button"
            onClick={() => {
              setCreating(false);
              setNotice(null);
            }}
          >
            Cancel
          </button>
        </form>
      )}
      {notice && <p role="alert">{notice}</p>}
      {beforeTabs}
      <div
        className="action-project-tabs"
        role="tablist"
        aria-label="Action item projects"
      >
        {tabs.map((tab, index) => {
          const active = projectScopeKey(tab.scope) === projectScopeKey(scope);
          return (
            <button
              key={projectScopeKey(tab.scope)}
              role="tab"
              className={active ? 'active' : ''}
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              title={tab.label}
              disabled={busy}
              onClick={() => onChange(tab.scope)}
              onKeyDown={(event) => navigateTabs(event, index)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function ActionItemProjectPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const catalog = useActionItemProjects(true);
  const projects = catalog.data?.items ?? [];
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="form-label">
        Project
      </label>
      <select
        id={id}
        className="input"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">No project</option>
        {value && !projects.some((project) => project.name === value) && (
          <option value={value}>{projectLabel(value)}</option>
        )}
        {projects.map((project) => (
          <option key={project.id} value={project.name}>
            {projectLabel(project.name)}
          </option>
        ))}
      </select>
      {catalog.loading && !catalog.data && (
        <p role="status">Loading projects…</p>
      )}
      {catalog.error && (
        <div role="alert">
          Could not load projects. Your selection is retained.{' '}
          <button
            className="btn btn-sm"
            disabled={disabled || catalog.loading}
            onClick={() => void catalog.refresh()}
          >
            Retry projects
          </button>
        </div>
      )}
    </div>
  );
}
