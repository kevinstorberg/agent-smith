import type { JobRunResult } from '../api';

export function personaOutcome(result: JobRunResult, assessmentOnly = false): { message: string; failed: boolean } {
  if (!result.success) return { message: 'Persona update failed. Open the execution for details.', failed: true };
  try {
    const output = JSON.parse(result.output);
    const assessment = output.assessments;
    if (assessment?.outcome === 'failed') return { message: 'Assessment update failed. Open the execution for details.', failed: true };
    if (assessment?.outcome === 'continued') return { message: 'Assessment progress saved. Run again or let scheduled runs continue the remaining work.', failed: false };
    if (assessment?.outcome === 'done') return { message: `Updated ${assessment.profiles ?? 0} profile assessment${assessment.profiles === 1 ? '' : 's'}. Changes are saved in History.`, failed: false };
    if (assessmentOnly && assessment?.outcome === 'idle') return { message: 'No assessment changes were needed. Human edits remain protected.', failed: false };
    const report = output.profiles;
    if (report?.outcome === 'continued') return { message: 'Progress saved. Run again or let scheduled runs continue the remaining work.', failed: false };
    if (report?.outcome === 'done') return { message: `Reviewed one meeting and updated ${report.profiles ?? 0} profiles.`, failed: false };
    if (report?.outcome === 'idle' || assessment?.outcome === 'idle') return { message: 'No unreviewed meeting transcripts or assessment updates are ready for this job.', failed: false };
  } catch { /* Older jobs may return plain text. */ }
  return { message: 'Persona run finished. Open the execution to review its result.', failed: false };
}
