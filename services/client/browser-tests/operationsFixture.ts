import type {
  AuditEvent,
  EvalRun,
  EvalScenario,
  EvalSuite,
  Job,
  Proposal,
} from '../src/api';

const stamp = '2026-11-03T12:00:00Z';
export const reviewTitle =
  'Review release ownership, security decisions, and next steps with engineering and product teams';

export function jobFixture(): Job {
  return {
    id: 1,
    name: 'Release job',
    description: null,
    schedule_enabled: true,
    schedule_config: { hours: 1 },
    input_params: {},
    version: 1,
    created_at: stamp,
    updated_at: stamp,
  };
}

export function auditFixture(): AuditEvent {
  return {
    id: 1,
    agent: 'claude',
    tool_name: 'mcp__release_review__capture_context',
    session_id: 'session_identifier_'.repeat(10),
    correlation_key: 'correlation_identifier_'.repeat(10),
    cwd: `/Users/example/${'release_context_'.repeat(8)}`,
    project: 'release_context_and_ownership',
    status: 'success',
    created_at: stamp,
    completed_at: stamp,
    duration_ms: 1200,
    tool_input: { context: 'release_context_'.repeat(20) },
    result: { captured: true },
  };
}

export function proposalFixture(): Proposal {
  return {
    id: 1,
    target_kind: 'rule',
    action: 'create',
    proposed_item_id: 2,
    target_name: 'release_review_context',
    project: 'browser-fixture',
    target_id: null,
    base_version: null,
    title: reviewTitle,
    rationale: reviewTitle,
    evidence: [],
    status: 'pending',
    applied_ref: null,
    created_at: stamp,
    updated_at: stamp,
    proposed_item: {
      name: 'release_review_context',
      content: { body: 'release_context_'.repeat(30), metadata: {} },
    },
  };
}

export function runFixture(): EvalRun {
  return {
    id: 1,
    timestamp: stamp,
    created_at: stamp,
    eval_type: 'rules',
    subcategory: 'release',
    scenario: reviewTitle,
    test_model: 'release_review_model_with_context',
    judge_model: 'judge-model',
    threshold: 7,
    score_avg: 8,
    score_count: 2,
    eval_suite_id: 1,
  };
}

export function suiteFixture(): EvalSuite {
  return {
    id: 1,
    name: 'release_review_with_extended_context',
    eval_type: 'rules',
    subcategory: 'release',
    judge_prompt: reviewTitle,
    items: { release_context: 'identifier_'.repeat(30) },
    config: { release_context: 'identifier_'.repeat(30) },
    enabled: true,
    created_at: stamp,
    updated_at: stamp,
    scenario_count: 1,
  };
}

export function scenarioFixture(): EvalScenario {
  return {
    id: 1,
    suite_id: 1,
    name: 'release_review_with_extended_context',
    prompt: `${reviewTitle}\n${'release_context_'.repeat(30)}`,
    enabled: true,
    sort_key: 1,
    created_at: stamp,
    updated_at: stamp,
  };
}
