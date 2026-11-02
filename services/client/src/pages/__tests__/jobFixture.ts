import type { Job } from '../../api';

export const jobFixture: Job = {
  id: 42, name: 'Meeting imports', schedule_enabled: true,
  description: 'Import accessible meeting notes.', schedule_config: { minutes: 15 },
  input_params: { graph_type: 'meeting_ingest', graph_inputs: {}, timeout: 600 }, version: 1,
  created_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z',
  configs: [{ id: 1, job_id: 42, device: '*', repo: '*', enabled: true, exclude: false,
    created_at: '2026-11-02T12:00:00Z', updated_at: '2026-11-02T12:00:00Z' }],
};
