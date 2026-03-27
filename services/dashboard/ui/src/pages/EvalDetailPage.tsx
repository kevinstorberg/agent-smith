import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import type { EvalRunDetail } from '../api';

export function EvalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<EvalRunDetail | null>(null);
  const [outputOpen, setOutputOpen] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.evals.get(Number(id)).then(setRun).catch(() => setRun(null));
  }, [id]);

  if (!run) {
    return <div className="loading">Loading...</div>;
  }

  const avgScore = run.results.length
    ? run.results.reduce((sum, r) => sum + r.score, 0) / run.results.length
    : 0;
  const passCount = run.results.filter(r => r.score >= run.threshold).length;
  const failCount = run.results.length - passCount;

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <a
          onClick={() => navigate('/evals')}
          style={{ color: 'var(--text-muted)', cursor: 'pointer', fontSize: 13 }}
        >
          &larr; Back to Evals
        </a>
      </div>

      <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
        {run.scenario}
      </h2>
      <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 20 }}>
        {new Date(run.timestamp).toLocaleString()}
      </p>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
        <span className="tag">
          {run.eval_type}{run.subcategory ? ` / ${run.subcategory}` : ''}
        </span>
        <span className="tag">model: {run.test_model}</span>
        <span className="tag">judge: {run.judge_model}</span>
        <span className="tag">threshold: {run.threshold}</span>
      </div>

      <div className="card" style={{ marginBottom: 24, display: 'flex', gap: 32, alignItems: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: avgScore >= run.threshold ? 'var(--success)' : 'var(--highlight)' }}>
            {avgScore.toFixed(2)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Average Score</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: 'var(--success)' }}>{passCount}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Passed</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: failCount > 0 ? 'var(--highlight)' : 'var(--text-muted)' }}>{failCount}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Failed</div>
        </div>
      </div>

      <h3 className="section-title" style={{ marginBottom: 12 }}>Results</h3>
      {run.results.map(r => (
        <div key={r.rule} className="card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span
              className={`score-badge ${r.score >= run.threshold ? 'pass' : 'fail'}`}
              style={{ fontSize: 16, fontWeight: 600 }}
            >
              {r.score.toFixed(2)}
            </span>
            <span style={{ fontSize: 15, fontWeight: 500 }}>{r.rule}</span>
          </div>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.6, margin: 0 }}>
            {r.reason}
          </p>
        </div>
      ))}

      <div style={{ marginTop: 32 }}>
        <h3
          className="section-title"
          style={{ marginBottom: 12, cursor: 'pointer', userSelect: 'none' }}
          onClick={() => setOutputOpen(!outputOpen)}
        >
          Agent Output {outputOpen ? '▾' : '▸'}
        </h3>
        {outputOpen && (
          <div className="card markdown-content" style={{ fontSize: 13, lineHeight: 1.7 }}>
            <ReactMarkdown>{run.output}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
