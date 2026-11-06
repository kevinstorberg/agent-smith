import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { api, ApiError } from '../api';
import type { Project, ProjectFields, ProjectPatch } from '../api';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { ButtonLink } from '../components/ButtonLink';
import { FieldError } from '../components/FieldError';
import { DateCell } from '../components/table';
import { useApiRead } from '../hooks/useApiRead';
import { useApiMutation } from '../hooks/useApiMutation';
import { useDetailPageEdit } from '../hooks/useDetailPageEdit';
import { usePageLifetime } from '../hooks/usePageLifetime';
import { usePolling } from '../hooks/usePolling';
import { MAX_BODY_LENGTH } from '../constants';
import {
  MAX_PROJECT_NAME_LENGTH,
  newProjectName,
  projectLabel,
} from '../utils/actionItemProjects';
import './projects.css';

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectDetail key={id || 'new'} id={id} />;
}

function ProjectDetail({ id }: { id?: string }) {
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const isCurrent = usePageLifetime();
  const fetchProject = useCallback(() => api.projects.get(Number(id)), [id]);
  const read = useApiRead(fetchProject, { enabled: !isNew });
  const project = read.data;
  const form = useDetailPageEdit<ProjectFields>({
    isNew,
    onCancel: () => navigate('/projects'),
  });
  const [snapshot, setSnapshot] = useState<Project | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const stale =
    conflict &&
    (read.loading || !!read.error || project?.revision !== snapshot?.revision);
  const mutation = useApiMutation({
    mutationFn: (fields: ProjectFields | ProjectPatch) =>
      'expected_revision' in fields
        ? api.projects.update(Number(id), fields)
        : api.projects.create(fields),
    onSuccess: (saved) => {
      if (!isCurrent()) return;
      if (isNew) navigate(`/projects/${saved.id}`, { replace: true });
      else {
        setNotice(null);
        form.cancelEditing();
        void read.refresh({ showLoading: false });
      }
    },
    onError: (error) => {
      if (!isCurrent()) return;
      if (!isNew && error instanceof ApiError && error.status === 409) {
        setConflict(true);
        setNotice(`${error.message} Your draft is retained.`);
        void read.refresh();
      } else setNotice(error.message);
    },
  });
  usePolling(() => read.refresh({ showLoading: false }), {
    enabled: !isNew && !form.editing && !mutation.loading,
  });

  function startEditing() {
    if (!project || read.loading || read.error || mutation.loading) return;
    setSnapshot(project);
    form.startEditing({ name: project.name, description: project.description });
    setConflict(false);
    setSubmitted(false);
    setNotice(null);
  }
  const draftName = form.editValues.name ?? '';
  const description = form.editValues.description ?? '';
  const name =
    !isNew && draftName === snapshot?.name
      ? draftName
      : newProjectName(draftName);
  const nameError =
    name === null || name === ''
      ? `Enter a name with 1–${MAX_PROJECT_NAME_LENGTH} characters and no control characters.`
      : null;
  const descriptionError = description.includes('\0')
    ? 'Description cannot contain NUL characters.'
    : [...description].length > MAX_BODY_LENGTH
      ? `Description must contain ${MAX_BODY_LENGTH} characters or fewer.`
      : null;

  function save() {
    if (mutation.loading || stale) return;
    setSubmitted(true);
    if (nameError || descriptionError || name === null) return;
    if (isNew) void mutation.mutate({ name, description });
    else if (snapshot) {
      const fields: ProjectPatch = { expected_revision: snapshot.revision };
      if (name !== snapshot.name) fields.name = name;
      if (description !== snapshot.description)
        fields.description = description;
      if (Object.keys(fields).length === 1) form.cancelEditing();
      else void mutation.mutate(fields);
    }
  }

  if (read.loading && !project)
    return <div className="loading">Loading project...</div>;
  if (!isNew && !project)
    return (
      <div className="card" role="alert">
        <p>{read.error || 'Project not found.'}</p>
        <button type="button" className="btn" onClick={() => read.refresh()}>
          Retry
        </button>
        <Link className="detail-back" to="/projects">
          Back to projects
        </Link>
      </div>
    );

  return (
    <div>
      <DetailPageHeader
        backTo={{ label: 'projects', path: '/projects' }}
        editing={form.editing}
        saving={mutation.loading}
        onEdit={startEditing}
        onSave={save}
        onCancel={() => {
          form.cancelEditing();
          setNotice(null);
          setConflict(false);
        }}
        disabled={!isNew && !!read.error}
        saveDisabled={stale}
      />
      {notice && (
        <div className="card" role="alert">
          <p>{notice}</p>
          {stale && (
            <button
              type="button"
              className="btn"
              disabled={read.loading || !!read.error}
              onClick={startEditing}
            >
              Reload saved version
            </button>
          )}
        </div>
      )}
      {read.error && project && (
        <div className="card" role="alert">
          <p>{read.error}</p>
          <button type="button" className="btn" onClick={() => read.refresh()}>
            Retry
          </button>
        </div>
      )}
      {form.editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <h2 className="page-title detail-form-title">
            {isNew ? 'New project' : 'Edit project'}
          </h2>
          <div className="form-group">
            <label className="form-label" htmlFor="project-name">
              Name
            </label>
            <input
              id="project-name"
              className="input detail-title-input"
              value={draftName}
              disabled={mutation.loading}
              onChange={(event) =>
                form.setEditValue('name', event.target.value)
              }
              placeholder="e.g. WGU"
              aria-invalid={submitted && !!nameError}
              aria-describedby={
                submitted && nameError ? 'project-name-error' : undefined
              }
            />
            <FieldError
              id="project-name-error"
              error={submitted ? nameError : null}
              currentLength={[...draftName].length}
              maxLength={MAX_PROJECT_NAME_LENGTH}
            />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="project-description">
              Description
            </label>
            <textarea
              id="project-description"
              className="input"
              rows={7}
              value={description}
              disabled={mutation.loading}
              onChange={(event) =>
                form.setEditValue('description', event.target.value)
              }
              placeholder="e.g. Coursework, assessments, and study plans."
              aria-invalid={submitted && !!descriptionError}
              aria-describedby={
                submitted && descriptionError
                  ? 'project-description-error'
                  : undefined
              }
            />
            <FieldError
              id="project-description-error"
              error={submitted ? descriptionError : null}
              currentLength={[...description].length}
              maxLength={MAX_BODY_LENGTH}
            />
          </div>
        </form>
      ) : (
        <>
          <div className="page-header">
            <h2 className="page-title">{projectLabel(project!.name)}</h2>
            <ButtonLink
              to={`/action-items?${new URLSearchParams({ project: project!.name })}`}
            >
              View action items
            </ButtonLink>
          </div>
          <div className="card markdown-content">
            <ReactMarkdown>
              {project!.description || 'No description added.'}
            </ReactMarkdown>
          </div>
          <div className="text-muted-sm">
            Updated <DateCell date={project!.updated_at} />
          </div>
        </>
      )}
    </div>
  );
}
