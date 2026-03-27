import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import MDEditor from '@uiw/react-md-editor';
import { api } from '../api';
import type { Plan } from '../api';

const styles = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  } as React.CSSProperties,
  backLink: {
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 13,
    background: 'none',
    border: 'none',
    fontFamily: 'var(--font)',
    textDecoration: 'underline',
  } as React.CSSProperties,
  btn: {
    background: 'var(--accent)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '6px 14px',
    cursor: 'pointer',
    fontSize: 13,
    fontFamily: 'var(--font)',
  } as React.CSSProperties,
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
  const isNew = id === 'new' || !id;

  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(!isNew);
  const [editing, setEditing] = useState(isNew);
  const [saving, setSaving] = useState(false);

  const [editTitle, setEditTitle] = useState('');
  const [editProject, setEditProject] = useState('');
  const [editBody, setEditBody] = useState('');

  const loadPlan = useCallback(async () => {
    if (isNew) return;
    setLoading(true);
    try {
      const data = await api.plans.get(Number(id));
      setPlan(data);
      setEditTitle(data.title);
      setEditProject(data.project || '');
      setEditBody(data.body);
    } finally {
      setLoading(false);
    }
  }, [id, isNew]);

  useEffect(() => {
    loadPlan();
  }, [loadPlan]);

  const startEditing = () => {
    if (!plan) return;
    setEditTitle(plan.title);
    setEditProject(plan.project || '');
    setEditBody(plan.body);
    setEditing(true);
  };

  const cancelEditing = () => {
    if (isNew) {
      navigate('/plans');
      return;
    }
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.plans.create({
          title: editTitle,
          body: editBody,
          project: editProject || null,
        });
        navigate(`/plans/${created.id}`, { replace: true });
      } else {
        await api.plans.update(Number(id), {
          title: editTitle,
          body: editBody,
          project: editProject || null,
        });
        setEditing(false);
        await loadPlan();
      }
    } catch (err) {
      alert(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="loading">Loading...</div>;
  if (!isNew && !plan) return <div className="loading">Plan not found</div>;

  return (
    <div>
      <div style={styles.header}>
        <button style={styles.backLink} onClick={() => navigate('/plans')}>
          &larr; Back to plans
        </button>
        <div style={{ display: 'flex', gap: 8 }}>
          {!editing && (
            <button style={styles.btn} onClick={startEditing}>Edit</button>
          )}
          {editing && (
            <>
              <button style={{ ...styles.btn, opacity: saving ? 0.5 : 1 }} onClick={save} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button style={styles.btn} onClick={cancelEditing}>Cancel</button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <>
          <input
            style={{ ...styles.input, marginBottom: 12 }}
            value={editTitle}
            onChange={e => setEditTitle(e.target.value)}
            placeholder="Plan title"
          />
          <div style={{ marginBottom: 16 }}>
            <label style={styles.fieldLabel}>Project</label>
            <input
              style={styles.fieldInput}
              value={editProject}
              onChange={e => setEditProject(e.target.value)}
              placeholder="Empty = no project"
            />
          </div>
          <div data-color-mode="dark">
            <MDEditor
              value={editBody}
              onChange={val => setEditBody(val || '')}
              height={400}
            />
          </div>
        </>
      ) : (
        <>
          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>
            {plan!.title}
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
            {plan!.project && (
              <span className="tag tag-project">{plan!.project}</span>
            )}
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              Updated {new Date(plan!.updated_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
          <div className="card">
            <div className="markdown-content">
              <ReactMarkdown>{plan!.body}</ReactMarkdown>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
