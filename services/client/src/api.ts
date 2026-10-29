const BASE = '/api';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function parseError(res: Response): Promise<never> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  const message = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ? detail.map((e: any) => `${e.loc?.slice(-1)[0] ?? 'field'}: ${e.msg}`).join('; ')
      : `${res.status} ${res.statusText}`;
  throw new ApiError(message, res.status);
}

async function get<T>(path: string, params?: Record<string, string | string[]>): Promise<T> {
  const url = new URL(path, window.location.origin);
  url.pathname = BASE + path;
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (Array.isArray(v)) {
        v.filter(Boolean).forEach(item => url.searchParams.append(k, item));
      } else if (v) {
        url.searchParams.set(k, v);
      }
    });
  }
  const res = await fetch(url.toString());
  if (!res.ok) await parseError(res);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) await parseError(res);
  return res.json();
}

async function del<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'DELETE',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  if (!res.ok) await parseError(res);
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

export interface Paginated<T> {
  items: T[];
  total: number;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface AssignableAgents {
  agents: string[];
  virtual_agents: string[];
}

export interface HarnessConfig {
  id: number;
  device: string;
  repo: string;
  agents: string[];
  subagents: string[];
  enabled: boolean;
  exclude: boolean;
}

export interface HarnessItem {
  id: number;
  name: string;
  project: string | null;
  agents: string[];
  content?: { body: string; metadata: Record<string, unknown> };
  sort_key: number;
  enabled: boolean;
  clone_as_skill?: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  configs: HarnessConfig[];
}

export interface Rule {
  name: string;
  content: string;
}

export interface Skill {
  name: string;
  content: string;
  files: string[];
}

export interface McpServer {
  name: string;
  config: Record<string, unknown>;
}

export interface MemoryItem {
  from_meeting?: boolean;
  source_type?: string | null;
  source_id?: string | null;
  id: string;
  content: string;
  repo?: string;
  tags?: string[];
  created_at?: string;
  last_accessed_at?: string;
}

export interface MeetingSummary {
  id: string;
  provider: string;
  account_key: string;
  external_id: string;
  source_name: string;
  project: string | null;
  title: string | null;
  summary_text: string;
  summary_markdown: string | null;
  source_url: string;
  metadata: Record<string, unknown>;
  provider_created_at: string;
  provider_updated_at: string;
  meeting_start: string | null;
  meeting_end: string | null;
  revision: number;
  first_seen_at: string;
  updated_at: string;
}

export interface MeetingListParams extends PaginationParams {
  q?: string;
  source?: string;
  project?: string;
  after?: string;
  before?: string;
}

export interface TranscriptSegment {
  id: string;
  text: string;
  speaker: {
    name?: string | null;
    source?: string | null;
    attribution?: string | null;
    diarization_label?: string | null;
  };
  effective_speaker?: EffectiveSpeaker | null;
  start_time: string | null;
  end_time: string | null;
}

export interface EffectiveSpeaker {
  profile_id: string | null;
  display_name: string;
  email: string | null;
  source: 'manual_assignment' | 'speaker_email' | 'attendee_match' | 'speaker_label';
}

export interface MeetingTranscript extends Paginated<TranscriptSegment> {
  status: 'not_imported' | 'pending' | 'capturing' | 'ready' | 'unsupported' | 'unavailable' | 'failed' | 'deleted';
  offset: number;
  limit: number;
  error_type: string | null;
  captured_at: string | null;
}

export interface MeetingMemory {
  id: string;
  content: string;
  kind: 'fact' | 'decision' | 'commitment' | 'constraint' | 'preference' | 'lesson' | 'question';
  evidence: { segment_id: string; quote: string }[];
}

export interface MeetingGeneration {
  status: 'not_imported' | 'pending' | 'running' | 'done' | 'failed' | 'blocked';
  reason: string | null;
  error_type: string | null;
  progress?: {
    processed_units: number; total_units: number | null; staged_count: number; saved_count: number;
    attempts: number; next_attempt_at: string | null;
  };
}

export interface MeetingMemories extends MeetingGeneration {
  items: MeetingMemory[];
  updated_at: string | null;
}

export interface MeetingProfileSummary {
  id: string;
  display_name: string;
  email: string | null;
  revision: number;
}

export interface MeetingProfiles extends MeetingGeneration {
  items: MeetingProfileSummary[];
}

export interface MeetingParticipantInput {
  name: string;
  email?: string | null;
  profile_id?: string | null;
  speaker_key?: string | null;
}

export interface MeetingParticipants {
  revision: number;
  items: MeetingParticipantInput[];
  provider_participants: { name?: string; email?: string }[];
  speakers: { key: string; label: string; segment_count: number; source?: string | null; attribution?: string | null;
    sample?: string; assignment?: MeetingParticipantInput | null; effective_speaker?: EffectiveSpeaker | null }[];
  running: boolean;
  enrolled: boolean;
  stale_speaker_keys?: string[];
}

export interface ProfileClaimCorrection {
  action: 'correct' | 'reject';
  content: string | null;
  reason: string;
  corrected_at: string;
}

export interface ProfileClaim {
  id: string;
  category: 'driver' | 'priority' | 'communication' | 'decision_pattern' | 'perception' | 'interaction' | 'uncertainty' | 'strength' | 'development_area' | 'relationship' | 'role';
  epistemic: 'self_report' | 'observed' | 'inference';
  confidence: 'low' | 'medium' | 'high';
  content: string;
  rationale: string;
  target_id: string | null;
  target_name: string | null;
  evidence: { segment_id: string; quote: string }[];
  meeting_id: string;
  source_url: string;
  status: 'active' | 'corrected' | 'rejected';
  correction: ProfileClaimCorrection | null;
}

export interface ParticipantProfile extends MeetingProfileSummary {
  identity_scope: 'email' | 'meeting' | 'manual';
  deleted: boolean;
  claims: ProfileClaim[];
  updated_at: string;
  tags: string[];
  starred: boolean;
  aliases: Pick<ParticipantProfile, 'id' | 'display_name' | 'email' | 'identity_scope'>[];
  emails?: string[];
  nicknames?: string[];
  metadata?: ProfileMetadataFields;
  section_notes?: ProfileSectionNotes;
  relationships?: ProfileRelationship[];
}

export interface ProfileMetadataFields {
  gender?: string; marital_status?: string; company?: string; job_role?: string;
  start_date?: string; supervisor?: string; other?: string;
}

export interface ProfileSectionNotes { drivers?: string; strengths?: string; development_areas?: string }

export interface ProfileRelationship {
  id: string; subject_id: string; target_id: string; subject_name: string; target_name: string;
  label: string; notes: string; revision: number; dismissed: boolean; claims: ProfileClaim[];
  created_at: string; updated_at: string;
}

export interface MeetingVocabulary {
  id: string; term: string; definition: string; revision: number; created_at: string; updated_at: string;
}

export interface ProfileSummary extends Pick<ParticipantProfile, 'id' | 'display_name' | 'email' | 'identity_scope' | 'revision' | 'updated_at' | 'tags' | 'starred'> {
  created_at: string;
  claim_count: number;
  meeting_count: number;
  emails?: string[];
  nicknames?: string[];
  metadata?: ProfileMetadataFields;
}

export interface ProfileUpdateInput {
  expected_revision: number;
  display_name?: string;
  tags?: string[];
  starred?: boolean;
  metadata?: ProfileMetadataFields;
  nicknames?: string[];
  section_notes?: ProfileSectionNotes;
}

export interface ClaimCorrectionInput {
  expected_revision: number;
  action: 'correct' | 'reject';
  content?: string;
  reason: string;
}

export interface EvalRun {
  id: number;
  timestamp: string;
  eval_type: string;
  subcategory: string | null;
  scenario: string;
  test_model: string;
  judge_model: string;
  threshold: number;
  results?: { rule: string; score: number; reason: string }[];
  score_avg?: number;
  score_count?: number;
  eval_suite_id: number | null;
  created_at: string;
}

export interface EvalRunDetail extends EvalRun {
  prompt: string | null;
  output: string;
}

export interface PlanFeedback {
  id: number;
  plan_id: number;
  source: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface Plan {
  id: number;
  title: string;
  body: string;
  project: string | null;
  status: 'draft' | 'final';
  created_at: string;
  updated_at: string;
  feedback?: PlanFeedback[];
}

export interface JobConfig {
  id: number;
  job_id: number;
  device: string;
  repo: string;
  enabled: boolean;
  exclude: boolean;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: number;
  name: string;
  description: string | null;
  schedule_config: Record<string, number>;
  input_params: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
  configs?: JobConfig[];
}

export interface JobExecution {
  id: number;
  job_id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  result: Record<string, unknown>;
}

export interface JobRunResult {
  success: boolean;
  output: string;
  error: string;
  duration_seconds: number;
  exit_code: number | null;
}

export interface ProposalEvidence {
  source: 'plan' | 'memory';
  id: string;
  note: string;
}

export interface Proposal {
  id: number;
  target_kind: 'rule' | 'skill' | 'hook' | 'job';
  action: 'create' | 'update';
  proposed_item_id: number;
  target_name: string;
  project: string | null;
  target_id: number | null;
  base_version: number | null;
  title: string;
  rationale: string;
  evidence: ProposalEvidence[];
  status: 'pending' | 'approved' | 'rejected';
  applied_ref: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  // Present on GET /proposals/{id}: the proposed row and the live target for diffing.
  proposed_item?: (Partial<HarnessItem> & Partial<Job>) | null;
  current_target?: (Partial<HarnessItem> & Partial<Job>) | null;
}

export interface ProposalCounts {
  pending: number;
  approved: number;
  rejected: number;
}

export interface AuditEvent {
  id: number;
  correlation_key: string;
  agent: 'claude' | 'codex' | 'gemini';
  session_id: string;
  tool_name: string;
  cwd: string | null;
  project: string | null;
  status: 'pending' | 'success' | 'error';
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  // Present only on GET /audit/events/{id}: the full payloads.
  tool_input?: Record<string, unknown>;
  result?: unknown;
}

export interface AuditCounts {
  claude: number;
  codex: number;
  gemini: number;
}

export interface AuditFilters {
  agent?: string;
  tool_name?: string;
  session_id?: string;
  project?: string;
  status?: string;
}

export interface EvalSuite {
  id: number;
  name: string;
  eval_type: string;
  subcategory: string;
  judge_prompt: string;
  items: Record<string, unknown>;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  scenario_count?: number;
  scenarios?: EvalScenario[];
}

export interface EvalScenario {
  id: number;
  suite_id: number;
  name: string;
  prompt: string;
  enabled: boolean;
  sort_key: number;
  created_at: string;
  updated_at: string;
}

export interface ChartPoint {
  id: number;
  timestamp: string;
  scores: Record<string, number>;
}

export interface AverageChartPoint {
  id: number;
  timestamp: string;
  score: number;
}

export interface ChatRoom {
  id: number;
  topic: string;
  context: string;
  state: 'open' | 'closed';
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface ChatMessage {
  id: number;
  room_id: number;
  // Widened beyond user/claude/codex/gemini: AI participants post under
  // names configured in CHAT_MODEL_NAMES.
  author: string;
  body: string;
  created_at: string;
}

export interface ChatConfig {
  participants: string[];
}

export interface ChatRoomDetail {
  room: ChatRoom;
  messages: ChatMessage[];
  last_message_id: number;
  has_more: boolean;
}

function paginationToParams(p?: PaginationParams): Record<string, string> {
  const params: Record<string, string> = {};
  if (p?.limit !== undefined) params.limit = String(p.limit);
  if (p?.offset !== undefined) params.offset = String(p.offset);
  return params;
}

export const api = {
  harness: {
    assignableAgents: () => get<AssignableAgents>('/harness/agents/assignable'),
    rules: () => get<Rule[]>('/harness/rules'),
    skills: () => get<Skill[]>('/harness/skills'),
    mcp: () => get<McpServer[]>('/harness/mcp'),
    sync: () => post<{ success: boolean; stdout: string; stderr: string }>('/harness/sync', {}),
    unsync: () => post<{ success: boolean; removed: string[] }>('/harness/unsync', {}),
    items: {
      list: (type: string, params?: PaginationParams & { name?: string; project?: string }) => {
        const query = paginationToParams(params);
        if (params?.name) query.name = params.name;
        if (params?.project) query.project = params.project;
        return get<Paginated<HarnessItem>>(`/harness/items/${type}`, query);
      },
      get: (type: string, id: number) => get<HarnessItem>(`/harness/items/${type}/${id}`),
      create: (type: string, body: unknown) => post<HarnessItem>(`/harness/items/${type}`, body),
      updateContent: (type: string, id: number, content: unknown) =>
        put<HarnessItem>(`/harness/items/${type}/${id}/content`, { content }),
      updateMetadata: (type: string, id: number, body: unknown) =>
        patch<HarnessItem>(`/harness/items/${type}/${id}`, body),
      history: (type: string, id: number) => get<HarnessItem[]>(`/harness/items/${type}/${id}/history`),
      remove: (type: string, id: number) => del(`/harness/items/${type}/${id}`),
      configs: {
        add: (type: string, itemId: number, body: Partial<HarnessConfig>) =>
          post<{ id: number }>(`/harness/items/${type}/${itemId}/configs`, body),
        update: (type: string, itemId: number, configId: number, body: Partial<HarnessConfig>) =>
          patch<HarnessConfig[]>(`/harness/items/${type}/${itemId}/configs/${configId}`, body),
        remove: (type: string, itemId: number, configId: number) =>
          del(`/harness/items/${type}/${itemId}/configs/${configId}`),
      },
      reorder: (type: string, ids: number[]) => put<{ reordered: boolean }>(`/harness/items/${type}/reorder`, { ids }),
    },
  },
  meetings: {
    list: (params?: MeetingListParams) => get<Paginated<MeetingSummary>>('/meetings', {
      ...paginationToParams(params),
      ...(params?.q ? { q: params.q } : {}),
      ...(params?.source ? { source: params.source } : {}),
      ...(params?.project ? { project: params.project } : {}),
      ...(params?.after ? { after: params.after } : {}),
      ...(params?.before ? { before: params.before } : {}),
    }),
    get: (id: string) => get<MeetingSummary>(`/meetings/${encodeURIComponent(id)}`),
    transcript: (id: string, params?: PaginationParams) =>
      get<MeetingTranscript>(`/meetings/${encodeURIComponent(id)}/transcript`, paginationToParams(params)),
    deleteTranscript: (id: string) => del<{ deleted: boolean; id: string }>(`/meetings/${encodeURIComponent(id)}/transcript`),
    retryTranscript: (id: string) => post<{ success: boolean }>(`/meetings/${encodeURIComponent(id)}/transcript/retry`, {}),
    memories: (id: string) => get<MeetingMemories>(`/meetings/${encodeURIComponent(id)}/memories`),
    retryMemories: (id: string) => post<{ success: boolean }>(`/meetings/${encodeURIComponent(id)}/memories/retry`, {}),
    profiles: (id: string) => get<MeetingProfiles>(`/meetings/${encodeURIComponent(id)}/profiles`),
    retryProfiles: (id: string) => post<{ success: boolean }>(`/meetings/${encodeURIComponent(id)}/profiles/retry`, {}),
    participants: (id: string) => get<MeetingParticipants>(`/meetings/${encodeURIComponent(id)}/participants`),
    updateParticipants: (id: string, body: { expected_revision: number; participants: MeetingParticipantInput[] }) =>
      put<MeetingParticipants>(`/meetings/${encodeURIComponent(id)}/participants`, body),
    process: (id: string) => post<{ status: 'queued' | 'running' | 'done' }>(`/meetings/${encodeURIComponent(id)}/process`, {}),
    vocabulary: {
      list: () => get<Paginated<MeetingVocabulary>>('/meetings/vocabulary'),
      create: (body: { term: string; definition: string }) => post<MeetingVocabulary>('/meetings/vocabulary', body),
      update: (id: string, body: { expected_revision: number; term?: string; definition?: string }) => patch<MeetingVocabulary>(`/meetings/vocabulary/${encodeURIComponent(id)}`, body),
      remove: (id: string, expected_revision: number) => del<{ deleted: boolean; id: string }>(`/meetings/vocabulary/${encodeURIComponent(id)}`, { expected_revision }),
    },
  },
  profiles: {
    create: (body: { display_name: string; email?: string }) => post<ParticipantProfile>('/profiles', body),
    list: (params?: PaginationParams & { q?: string; tags?: string[]; starred?: boolean; sort?: string }) => get<Paginated<ProfileSummary>>('/profiles', {
      ...paginationToParams(params),
      ...(params?.q ? { q: params.q } : {}),
      ...(params?.tags?.length ? { tags: params.tags } : {}),
      ...(params?.starred !== undefined ? { starred: String(params.starred) } : {}),
      ...(params?.sort ? { sort: params.sort } : {}),
    }),
    get: (id: string) => get<ParticipantProfile>(`/profiles/${encodeURIComponent(id)}`),
    update: (id: string, body: ProfileUpdateInput) => patch<ParticipantProfile>(`/profiles/${encodeURIComponent(id)}`, body),
    merge: (id: string, body: { target_id: string; expected_revision: number; target_revision: number }) =>
      post<ParticipantProfile>(`/profiles/${encodeURIComponent(id)}/merge`, body),
    linkEmail: (id: string, body: { email: string; expected_revision: number }) =>
      post<ParticipantProfile>(`/profiles/${encodeURIComponent(id)}/aliases`, body),
    createRelationship: (id: string, body: { target_id: string; target_revision: number; expected_revision: number; label: string; notes: string }) =>
      post<ProfileRelationship>(`/profiles/${encodeURIComponent(id)}/relationships`, body),
    updateRelationship: (id: string, relationshipId: string, body: { expected_revision: number; label?: string; notes?: string }) =>
      patch<ProfileRelationship>(`/profiles/${encodeURIComponent(id)}/relationships/${encodeURIComponent(relationshipId)}`, body),
    removeRelationship: (id: string, relationshipId: string, expected_revision: number) =>
      del<{ deleted: boolean; id: string }>(`/profiles/${encodeURIComponent(id)}/relationships/${encodeURIComponent(relationshipId)}`, { expected_revision }),
    correctClaim: (id: string, claimId: string, body: ClaimCorrectionInput) =>
      post<ParticipantProfile>(`/profiles/${encodeURIComponent(id)}/claims/${encodeURIComponent(claimId)}`, body),
    remove: (id: string, expectedRevision: number) =>
      del<{ deleted: boolean; id: string }>(`/profiles/${encodeURIComponent(id)}`, { expected_revision: expectedRevision }),
  },
  memory: {
    search: (q: string, opts?: PaginationParams & { repo?: string; tags?: string[]; sort?: string; meeting_only?: boolean }) =>
      get<Paginated<MemoryItem>>('/memory/search', {
        q,
        ...(opts?.repo ? { repo: opts.repo } : {}),
        ...(opts?.tags && opts.tags.length ? { tags: opts.tags } : {}),
        ...(opts?.sort ? { sort: opts.sort } : {}),
        ...(opts?.meeting_only !== undefined ? { meeting_only: String(opts.meeting_only) } : {}),
        ...paginationToParams(opts),
      }),
    list: (opts?: PaginationParams & { repo?: string; tags?: string[]; sort?: string; meeting_only?: boolean }) =>
      get<Paginated<MemoryItem>>('/memory/list', {
        ...(opts?.repo ? { repo: opts.repo } : {}),
        ...(opts?.tags && opts.tags.length ? { tags: opts.tags } : {}),
        ...(opts?.sort ? { sort: opts.sort } : {}),
        ...(opts?.meeting_only !== undefined ? { meeting_only: String(opts.meeting_only) } : {}),
        ...paginationToParams(opts),
      }),
    get: (id: string) => get<MemoryItem>(`/memory/${id}`),
    update: (id: string, body: { content?: string; repo?: string; tags?: string[] }) =>
      put<MemoryItem>(`/memory/${id}`, body),
    remove: (id: string) => del<{ deleted: boolean }>(`/memory/${id}`),
  },
  evals: {
    list: (params?: Record<string, string>) =>
      get<Paginated<EvalRun>>('/evals', params),
    chart: (params?: Record<string, string>) =>
      get<ChartPoint[]>('/evals/chart', params),
    chartAverage: (params?: Record<string, string>) =>
      get<AverageChartPoint[]>('/evals/chart/average', params),
    categories: () => get<string[]>('/evals/categories'),
    subcategories: (params?: Record<string, string>) =>
      get<string[]>('/evals/subcategories', params),
    get: (id: number) => get<EvalRunDetail>(`/evals/${id}`),
    remove: (id: number) => del<{ deleted: number }>(`/evals/${id}`),
  },
  plans: {
    list: (pagination?: PaginationParams & { project?: string; status?: string }) =>
      get<Paginated<Plan>>('/plans', {
        ...(pagination?.project ? { project: pagination.project } : {}),
        ...(pagination?.status ? { status: pagination.status } : {}),
        ...paginationToParams(pagination),
      }),
    search: (q: string) => get<Plan[]>('/plans/search', { q }),
    get: (id: number) => get<Plan>(`/plans/${id}`),
    create: (body: { title: string; body: string; project?: string | null }) =>
      post<Plan>('/plans', body),
    update: (id: number, body: { title?: string; body?: string; project?: string | null }) =>
      put<Plan>(`/plans/${id}`, body),
    remove: (id: number) => del(`/plans/${id}`),
  },
  jobs: {
    list: (pagination?: PaginationParams) =>
      get<Paginated<Job>>('/jobs', paginationToParams(pagination)),
    get: (id: number) => get<Job>(`/jobs/${id}`),
    create: (body: { name: string; schedule_config: Record<string, number>; input_params?: Record<string, unknown>; description?: string | null; device_scope?: 'all_devices' | 'this_device' }) =>
      post<Job>('/jobs', body),
    update: (id: number, body: { name?: string; schedule_config?: Record<string, number>; input_params?: Record<string, unknown>; description?: string | null }) =>
      put<Job>(`/jobs/${id}`, body),
    remove: (id: number) => del(`/jobs/${id}`),
    runNow: (id: number) => post<JobRunResult>(`/jobs/${id}/run-now`, {}),
    executions: (id: number, pagination?: PaginationParams) =>
      get<Paginated<JobExecution>>(`/jobs/${id}/executions`, paginationToParams(pagination)),
    configs: {
      add: (jobId: number, body: Partial<JobConfig>) =>
        post<JobConfig[]>(`/jobs/${jobId}/configs`, body),
      update: (jobId: number, configId: number, body: Partial<JobConfig>) =>
        patch<JobConfig[]>(`/jobs/${jobId}/configs/${configId}`, body),
      remove: (jobId: number, configId: number) =>
        del(`/jobs/${jobId}/configs/${configId}`),
    },
  },
  proposals: {
    list: (status?: string, pagination?: PaginationParams) => {
      const params = paginationToParams(pagination);
      if (status) params.status = status;
      return get<Paginated<Proposal>>('/proposals', params);
    },
    counts: () => get<ProposalCounts>('/proposals/counts'),
    get: (id: number) => get<Proposal>(`/proposals/${id}`),
    approve: (id: number) => post<Proposal>(`/proposals/${id}/approve`, {}),
    reject: (id: number) => post<Proposal>(`/proposals/${id}/reject`, {}),
    remove: (id: number) => del(`/proposals/${id}`),
    generate: () => post<{ started: boolean; job_id: number }>('/proposals/generate', {}),
  },
  audit: {
    list: (filters?: AuditFilters, pagination?: PaginationParams) => {
      const params = paginationToParams(pagination);
      if (filters?.agent) params.agent = filters.agent;
      if (filters?.tool_name) params.tool_name = filters.tool_name;
      if (filters?.session_id) params.session_id = filters.session_id;
      if (filters?.project) params.project = filters.project;
      if (filters?.status) params.status = filters.status;
      return get<Paginated<AuditEvent>>('/audit/events', params);
    },
    counts: () => get<AuditCounts>('/audit/counts'),
    get: (id: number) => get<AuditEvent>(`/audit/events/${id}`),
  },
  chat: {
    list: () => get<Paginated<ChatRoom>>('/chat'),
    create: (body: { topic: string; context?: string }) => post<ChatRoom>('/chat', body),
    update: (id: number, body: { topic: string; context?: string }) =>
      patch<ChatRoom>(`/chat/${id}`, body),
    remove: (id: number) => del(`/chat/${id}`),
    get: (id: number, afterMessageId = 0) =>
      get<ChatRoomDetail>(`/chat/${id}`, { after_message_id: String(afterMessageId) }),
    postMessage: (id: number, body: string) =>
      post<ChatMessage>(`/chat/${id}/messages`, { body }),
    stop: (id: number) => post<ChatRoom>(`/chat/${id}/stop`, {}),
    config: () => get<ChatConfig>('/chat/config'),
  },
  evalConfigs: {
    suites: {
      list: (params?: Record<string, string>) =>
        get<Paginated<EvalSuite>>('/eval-configs/suites', params),
      get: (id: number) => get<EvalSuite>(`/eval-configs/suites/${id}`),
      create: (body: Partial<EvalSuite>) => post<EvalSuite>('/eval-configs/suites', body),
      update: (id: number, body: Partial<EvalSuite>) =>
        put<EvalSuite>(`/eval-configs/suites/${id}`, body),
      remove: (id: number) => del<{ deleted: number }>(`/eval-configs/suites/${id}`),
    },
    scenarios: {
      list: (suiteId: number, params?: Record<string, string>) =>
        get<EvalScenario[]>(`/eval-configs/suites/${suiteId}/scenarios`, params),
      get: (id: number) => get<EvalScenario>(`/eval-configs/scenarios/${id}`),
      create: (suiteId: number, body: { name: string; prompt: string; enabled?: boolean }) =>
        post<EvalScenario>(`/eval-configs/suites/${suiteId}/scenarios`, body),
      update: (id: number, body: Partial<EvalScenario>) =>
        put<EvalScenario>(`/eval-configs/scenarios/${id}`, body),
      remove: (id: number) => del<{ deleted: number }>(`/eval-configs/scenarios/${id}`),
    },
  },
};
