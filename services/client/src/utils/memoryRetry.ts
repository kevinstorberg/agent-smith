import type { MeetingAnalysisReceipt } from '../api';

export const MEMORY_RESTART_HELP = 'Restart from the beginning using the saved Granola summary.';

export function hasUnfinishedMemory(receipt: MeetingAnalysisReceipt): boolean {
  return receipt.items.some(item => item.stages.memory && item.stages.memory.status !== 'done');
}

export function analysisRetryLabel(receipt: MeetingAnalysisReceipt): string {
  if (!hasUnfinishedMemory(receipt)) return 'Resume unfinished analysis';
  return receipt.items.some(item => item.stages.profile && item.stages.profile.status !== 'done')
    ? 'Retry unfinished analysis' : 'Retry memory generation';
}
