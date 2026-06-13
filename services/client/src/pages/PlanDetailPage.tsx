import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import type { Plan } from '../api';
import { CopyButton } from '../components/CopyButton';
import { FieldError } from '../components/FieldError';
import { DetailPageHeader } from '../components/DetailPageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { useDetailPageEdit } from '../hooks/useDetailPageEdit';
import { useApiMutation } from '../hooks/useApiMutation';
import { useNotification } from '../context/useNotification';
import { MAX_TITLE_LENGTH } from '../constants';
import { validators } from '../utils/validation';

const styles = {
  input: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '8px 12px',
    fontSize: 18,
    fontWeight: 600,
    fontFamily: 'var(--font)',
    width: '100%',
  } as React.CSSProperties,
  fieldLabel: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--text-muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 6,
  } as React.CSSProperties,
  fieldInput: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text)',
    padding: '6px 10px',
    fontSize: 13,
    fontFamily: 'var(--font)',
    width: 220,
  } as React.CSSProperties,
} as const;

export function PlanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { notify } = useNotification();
  const isNew = id === 'new' || !id;

  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(!isNew);

  const {
    editing,
    saving,
    editValues,
    setEditValue,
    startEditing: startEdit,
    cancelEditing: cancelEdit,
    setSaving,
  } = useDetailPageEdit<Plan>({
    initialData: plan,
    isNew,
    onCancel: () => navigate('/plans'),
  });

  const createMutation = useApiMutation({
    mutationFn: api.plans.create,
    onSuccess: (created) => {
      navigate(`/plans/${created.id}`, { replace: true });
    },
  });

  const updateMutation = useApiMutation({
    mutationFn: (data: Partial<Plan>) => api.plans.update(Number(id), data),
    onSuccess: async () => {
      await loadPlan();
    },
  });

  const deleteMutation = useApiMutation({
    mutationFn: () => api.plans.remove(Number(id)),
    onSuccess: () => {
      navigate('/plans');
    },
  });

  const loadPlan = useCallback(async () => {
    if (isNew) return;
    setLoading(true);
    try {
      const data = await api.plans.get(Number(id));
      setPlan(data);
    } finally {
      setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => {
    loadPlan();
  }, [loadPlan]);

  const startEditing = () => {
    if (!plan) return;
    startEdit(plan);
  };

  const save = async () => {
    const title = editValues.title ?? '';
    const body = editValues.body ?? '';
    const project = editValues.project ?? '';

    const titleError = validators.compose(validators.required, validators.maxLength(MAX_TITLE_LENGTH))(title);
    if (titleError) { notify(titleError === 'Required' ? 'Title is required.' : `Title must be ${MAX_TITLE_LENGTH} characters or fewer.`, 'error'); return; }

    const bodyError = validators.required(body);
    if (bodyError) { notify('Body is required.', 'error'); return; }

    setSaving(true);
    try {
      if (isNew) {
        await createMutation.mutateAsync({
          title,
          body,
          project: project || null,
        });
      } else {
        await updateMutation.mutateAsync({
          title,
          body,
          project: project || null,
        });
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!plan) return;
    await deleteMutation.mutateAsync();
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!isNew && !plan) return <div className="loading">Plan not found</div>;

  return (
    <div>
      <DetailPageHeader
        backTo={{ label: 'plans', path: '/plans' }}
        editing={editing}
        saving={saving}
        onEdit={startEditing}
        onSave={save}
        onCancel={cancelEdit}
        onDelete={plan ? handleDelete : undefined}
        onNavigateBack={() => navigate('/plans')}
        deleteConfirmMessage={plan ? `Delete plan "${plan.title}"?` : undefined}
        showActions={!isNew || editing}
      />

      {editing ? (
        <>
          <input
            style={{ ...styles.input, borderColor: editValues.title && editValues.title.length > MAX_TITLE_LENGTH ? 'var(--highlight)' : undefined }}
            value={editValues.title ?? ''}
            onChange={e => setEditValue('title', e.target.value)}
            placeholder="Plan title"
            maxLength={MAX_TITLE_LENGTH}
          />
          <FieldError maxLength={MAX_TITLE_LENGTH} currentLength={editValues.title?.length ?? 0} />
          <div style={{ marginBottom: 16 }}>
            <label style={styles.fieldLabel}>Project</label>
            <input
              style={styles.fieldInput}
              value={editValues.project ?? ''}
              onChange={e => setEditValue('project', e.target.value)}
              placeholder="Empty = no project"
            />
          </div>
          <div data-color-mode="dark">
            <MDEditor
              value={editValues.body ?? ''}
              onChange={val => setEditValue('body', val || '')}
              height={400}
            />
          </div>
        </>
      ) : (
        <>
          <h2 className="page-title" style={{ marginBottom: 8 }}>
            {plan!.title}
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
            <StatusBadge status={plan!.status} kind="plan" />
            {plan!.project && (
              <span className="tag tag-project">{plan!.project}</span>
            )}
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Updated {new Date(plan!.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
          <div className="card" style={{ position: 'relative' }}>
            <CopyButton text={plan!.body} style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }} />
            <div className="markdown-content">
              <ReactMarkdown>{plan!.body}</ReactMarkdown>
            </div>
          </div>

          {(plan!.feedback?.length ?? 0) > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="section-title">Feedback</div>
              {plan!.feedback!.map(fb => (
                <div key={fb.id} className="card" style={{ position: 'relative' }}>
                  <CopyButton text={fb.body} style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }} />
                  <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 8 }}>
                    {fb.source} · {new Date(fb.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </div>
                  <div className="markdown-content">
                    <ReactMarkdown>{fb.body}</ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
