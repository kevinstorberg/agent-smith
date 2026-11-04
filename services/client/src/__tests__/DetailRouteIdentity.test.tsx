import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router';
import type { TextareaHTMLAttributes } from 'react';
import App from '../App';
import { api } from '../api';
import type {
  AuditEvent,
  EvalRunDetail,
  EvalSuite,
  HarnessItem,
  Plan,
  Proposal,
} from '../api';

vi.mock('@uiw/react-md-editor', () => ({
  default: ({
    value,
    onChange,
    textareaProps,
  }: {
    value?: string;
    onChange?: (value: string) => void;
    textareaProps?: TextareaHTMLAttributes<HTMLTextAreaElement>;
  }) => (
    <textarea
      {...textareaProps}
      value={value}
      onChange={(event) => onChange?.(event.target.value)}
    />
  ),
}));
vi.mock('../components/Sidebar', () => ({ Sidebar: () => null }));
vi.mock('../pages/HarnessIndexPage', () => ({
  HarnessIndexPage: () => <p>Harness list</p>,
}));
vi.mock('../pages/PlansIndexPage', () => ({
  PlansIndexPage: () => <p>Plan list</p>,
}));
vi.mock('../pages/ProposalsIndexPage', () => ({
  ProposalsIndexPage: () => <p>Proposal list</p>,
}));
vi.mock('../pages/EvalsPage', () => ({ EvalsPage: () => <p>Eval list</p> }));
vi.mock('../pages/EvalSuitesPage', () => ({
  EvalSuitesPage: () => <p>Suite list</p>,
}));

const timestamp = '2026-11-04T12:00:00Z';
function harness(id: number): HarnessItem {
  return {
    id,
    name: `Item ${id}`,
    project: null,
    agents: ['codex'],
    content: { body: `Body ${id}`, metadata: {} },
    sort_key: 0,
    enabled: true,
    version: id,
    created_at: timestamp,
    updated_at: timestamp,
    configs: [],
  };
}
function plan(id: number): Plan {
  return {
    id,
    title: `Plan ${id}`,
    body: `Body ${id}`,
    project: null,
    status: 'draft',
    created_at: timestamp,
    updated_at: timestamp,
  };
}
function audit(id: number): AuditEvent {
  return {
    id,
    agent: 'codex',
    tool_name: `Tool ${id}`,
    correlation_key: `key-${id}`,
    session_id: `session-${id}`,
    cwd: null,
    project: null,
    status: 'success',
    created_at: timestamp,
    completed_at: timestamp,
    duration_ms: 1,
  };
}
function proposal(id: number): Proposal {
  return {
    id,
    title: `Proposal ${id}`,
    target_kind: 'rule',
    action: 'create',
    proposed_item_id: id + 10,
    target_name: `rule_${id}`,
    project: null,
    target_id: null,
    base_version: null,
    rationale: `Rationale ${id}`,
    evidence: [],
    status: 'pending',
    applied_ref: null,
    created_at: timestamp,
    updated_at: timestamp,
    proposed_item: { content: { body: `Body ${id}`, metadata: {} } },
  };
}
function run(id: number): EvalRunDetail {
  return {
    id,
    scenario: `Run ${id}`,
    timestamp,
    eval_type: 'rules',
    subcategory: 'core',
    test_model: 'test',
    judge_model: 'judge',
    threshold: 0.7,
    results: [],
    eval_suite_id: null,
    created_at: timestamp,
    prompt: '',
    output: `Output ${id}`,
  };
}
function suite(id: number): EvalSuite {
  return {
    id,
    name: `Suite ${id}`,
    eval_type: 'rules',
    subcategory: 'core',
    judge_prompt: `Judge ${id}`,
    items: {},
    config: {},
    enabled: true,
    created_at: timestamp,
    updated_at: timestamp,
    scenarios: [
      {
        id: id * 10,
        suite_id: id,
        name: `Scenario ${id}`,
        prompt: `Prompt ${id}`,
        enabled: true,
        sort_key: 0,
        created_at: timestamp,
        updated_at: timestamp,
      },
    ],
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function Navigation() {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <input aria-label="Destination" />
      <button
        onClick={() =>
          navigate(
            (
              document.querySelector(
                '[aria-label="Destination"]',
              ) as HTMLInputElement
            ).value,
          )
        }
      >
        Go
      </button>
      <output aria-label="Current route">
        {location.pathname}
        {location.search}
        {location.hash}
      </output>
    </>
  );
}
function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Navigation />
    </MemoryRouter>,
  );
}
function go(path: string) {
  fireEvent.change(screen.getByLabelText('Destination'), {
    target: { value: path },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Go' }));
}
async function heading(name: string) {
  return screen.findByRole('heading', { name });
}
function expectRoute(path: string) {
  expect(screen.getByLabelText('Current route').textContent).toBe(path);
}
function nameField(path: string) {
  return path === '/eval-configs'
    ? screen.getByPlaceholderText('Suite name')
    : screen.getByLabelText(path === '/plans' ? 'Plan title' : 'Name');
}

function resource<T>(
  name: string,
  path: string,
  value: (id: number) => T,
  title: (id: number) => string,
  install: (pending: Promise<T>, fresh: T) => void,
) {
  return {
    name,
    path,
    title,
    pending() {
      const pending = deferred<T>();
      install(pending.promise, value(2));
      return {
        resolve: () => pending.resolve(value(1)),
        reject: () => pending.reject(new Error('Old read failed')),
      };
    },
  };
}
const resources = [
  resource(
    'harness',
    '/harness/rule',
    harness,
    (id) => `Item ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.harness.items.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
  resource(
    'plan',
    '/plans',
    plan,
    (id) => `Plan ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.plans.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
  resource(
    'audit',
    '/audit',
    audit,
    (id) => `codex · Tool ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.audit.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
  resource(
    'proposal',
    '/proposals',
    proposal,
    (id) => `Proposal ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.proposals.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
  resource(
    'eval',
    '/evals',
    run,
    (id) => `Run ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.evals.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
  resource(
    'suite',
    '/eval-configs',
    suite,
    (id) => `Suite ${id}`,
    (pending, fresh) =>
      vi
        .mocked(api.evalConfigs.suites.get)
        .mockReturnValueOnce(pending)
        .mockResolvedValue(fresh),
  ),
];

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.spyOn(api.harness, 'assignableAgents').mockResolvedValue({
    agents: ['codex'],
    virtual_agents: [],
  });
  vi.spyOn(api.harness.items, 'get').mockImplementation(async (_type, id) =>
    harness(id),
  );
  vi.spyOn(api.harness.items, 'history').mockResolvedValue([]);
  vi.spyOn(api.harness.items, 'updateContent').mockResolvedValue(harness(3));
  vi.spyOn(api.harness.items, 'updateMetadata').mockImplementation(
    async (_type, id) => harness(id),
  );
  vi.spyOn(api.plans, 'get').mockImplementation(async (id) => plan(id));
  vi.spyOn(api.plans, 'update').mockImplementation(async (id) => plan(id));
  vi.spyOn(api.audit, 'get').mockImplementation(async (id) => audit(id));
  vi.spyOn(api.proposals, 'get').mockImplementation(async (id) => proposal(id));
  vi.spyOn(api.proposals, 'approve').mockImplementation(async (id) => ({
    ...proposal(id),
    status: 'approved',
  }));
  vi.spyOn(api.evals, 'get').mockImplementation(async (id) => run(id));
  vi.spyOn(api.evalConfigs.suites, 'get').mockImplementation(async (id) =>
    suite(id),
  );
  vi.spyOn(api.evalConfigs.suites, 'update').mockImplementation(async (id) =>
    suite(id),
  );
});

describe('detail route resource identity', () => {
  it.each(resources)(
    'keeps $name B selected when the older A response arrives',
    async (resource) => {
      const old = resource.pending();
      renderRoute(`${resource.path}/1`);
      go(`${resource.path}/2`);
      await heading(resource.title(2));
      await act(async () => old.resolve());
      expect(await heading(resource.title(2))).toBeVisible();
      expect(
        screen.queryByRole('heading', { name: resource.title(1) }),
      ).not.toBeInTheDocument();
      expectRoute(`${resource.path}/2`);
      const destructive = deletions.find(
        (entry) => entry.path === resource.path,
      );
      if (destructive) {
        const pending = deferred<{ deleted: number }>();
        const remove = destructive.mock(pending.promise);
        fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0]);
        expect(remove.mock.calls[0]).toEqual(
          resource.name === 'harness' ? ['rule', 2] : [2],
        );
        expectRoute(`${resource.path}/2`);
        await act(async () => pending.resolve({ deleted: 1 }));
      }
    },
  );

  it.each(
    resources.filter((resource) =>
      ['audit', 'proposal', 'eval'].includes(resource.name),
    ),
  )('ignores a caught old $name failure after B loads', async (resource) => {
    const old = resource.pending();
    renderRoute(`${resource.path}/1`);
    go(`${resource.path}/2`);
    await heading(resource.title(2));
    await act(async () => old.reject());
    expect(await heading(resource.title(2))).toBeVisible();
    expect(screen.queryByText(/Old read failed/)).not.toBeInTheDocument();
    expectRoute(`${resource.path}/2`);
  });

  it('distinguishes harness types even when the numeric ID is unchanged', async () => {
    const old = deferred<HarnessItem>();
    vi.mocked(api.harness.items.get)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue({ ...harness(1), name: 'Skill 1' });
    renderRoute('/harness/rule/1');
    go('/harness/skill/1');
    await heading('Skill 1');
    await act(async () => old.resolve(harness(1)));
    expect(await heading('Skill 1')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'edited_skill' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.harness.items.updateMetadata).toHaveBeenCalledWith(
        'skill',
        1,
        expect.objectContaining({ name: 'edited_skill' }),
      ),
    );
    expectRoute('/harness/skill/1');
  });

  it.each(['resolve', 'reject'] as const)(
    'keeps B history when A history later %s',
    async (outcome) => {
      const old = deferred<HarnessItem[]>();
      vi.mocked(api.harness.items.history)
        .mockReturnValueOnce(old.promise)
        .mockResolvedValue([harness(2)]);
      renderRoute('/harness/rule/1');
      await heading('Item 1');
      go('/harness/rule/2');
      await heading('Item 2');
      const history = () =>
        within(
          screen.getByRole('heading', { name: 'Version History' })
            .nextElementSibling as HTMLElement,
        );
      await waitFor(() => expect(history().getByText('v2')).toBeVisible());
      await act(async () => {
        if (outcome === 'resolve') old.resolve([harness(101)]);
        else old.reject(new Error('Old history failed'));
      });
      expect(history().getByText('v2')).toBeVisible();
      expect(screen.queryByText('v101')).not.toBeInTheDocument();
    },
  );

  it('keeps the newest A lifetime when navigating A to B to A', async () => {
    const firstA = deferred<Plan>();
    vi.mocked(api.plans.get)
      .mockReturnValueOnce(firstA.promise)
      .mockResolvedValueOnce(plan(2))
      .mockResolvedValue({ ...plan(1), title: 'Fresh A' });
    renderRoute('/plans/1');
    go('/plans/2');
    await heading('Plan 2');
    go('/plans/1');
    await heading('Fresh A');
    await act(async () => firstA.resolve(plan(1)));
    expect(await heading('Fresh A')).toBeVisible();
    expectRoute('/plans/1');
  });

  it('resets harness edit/config state and saves B after leaving an A draft', async () => {
    renderRoute('/harness/rule/1');
    await heading('Item 1');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Draft A' },
    });
    go('/harness/rule/2');
    await heading('Item 2');
    expect(screen.queryByDisplayValue('Draft A')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'draft_b' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.harness.items.updateMetadata).toHaveBeenCalledWith(
        'rule',
        2,
        expect.objectContaining({ name: 'draft_b' }),
      ),
    );
    expectRoute('/harness/rule/2');
  });

  it('drops a harness version preview and configuration draft when the resource changes', async () => {
    vi.mocked(api.harness.items.history).mockResolvedValueOnce([harness(101)]);
    renderRoute('/harness/rule/1');
    await heading('Item 1');
    fireEvent.click(await screen.findByText('v101'));
    expect(screen.getByRole('button', { name: 'Restore v101' })).toBeVisible();
    go('/harness/rule/2');
    await heading('Item 2');
    expect(
      screen.queryByRole('button', { name: 'Restore v101' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '+ Add' }));
    expect(screen.getByText('New Configuration')).toBeVisible();
    go('/harness/rule/1');
    await heading('Item 1');
    expect(screen.queryByText('New Configuration')).not.toBeInTheDocument();
  });

  it.each(['/plans', '/eval-configs'])(
    'resets %s drafts between existing resources and new mode',
    async (path) => {
      renderRoute(`${path}/1`);
      const isPlan = path === '/plans';
      await heading(isPlan ? 'Plan 1' : 'Suite 1');
      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
      fireEvent.change(nameField(path), { target: { value: 'Draft A' } });
      go(`${path}/2`);
      await heading(isPlan ? 'Plan 2' : 'Suite 2');
      expect(screen.queryByDisplayValue('Draft A')).not.toBeInTheDocument();
      go(`${path}/new`);
      expect(nameField(path)).toHaveValue('');
      fireEvent.change(nameField(path), {
        target: { value: 'Unsaved new draft' },
      });
      go(`${path}/1`);
      await heading(isPlan ? 'Plan 1' : 'Suite 1');
      expect(
        screen.queryByDisplayValue('Unsaved new draft'),
      ).not.toBeInTheDocument();
    },
  );

  it.each(['/harness/rule', '/plans', '/eval-configs'])(
    'preserves the %s draft on query/hash-only navigation',
    async (path) => {
      renderRoute(`${path}/1`);
      await heading(
        path === '/plans'
          ? 'Plan 1'
          : path === '/eval-configs'
            ? 'Suite 1'
            : 'Item 1',
      );
      fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
      fireEvent.change(nameField(path), { target: { value: 'Current draft' } });
      go(`${path}/1?view=raw#editor`);
      expect(nameField(path)).toHaveValue('Current draft');
      expectRoute(`${path}/1?view=raw#editor`);
    },
  );

  it('reviews only B after an older proposal A arrives', async () => {
    const old = resources
      .find((resource) => resource.name === 'proposal')!
      .pending();
    renderRoute('/proposals/1');
    go('/proposals/2');
    await heading('Proposal 2');
    await act(async () => old.resolve());
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(api.proposals.approve).toHaveBeenCalledWith(2));
    expect(await heading('Proposal 2')).toBeVisible();
    expectRoute('/proposals/2');
  });

  const deletions = [
    {
      path: '/harness/rule',
      title: 'Item 1',
      mock: (promise: Promise<unknown>) =>
        vi
          .spyOn(api.harness.items, 'remove')
          .mockReturnValue(promise.then(() => undefined)),
    },
    {
      path: '/plans',
      title: 'Plan 1',
      mock: (promise: Promise<unknown>) =>
        vi
          .spyOn(api.plans, 'remove')
          .mockReturnValue(promise.then(() => undefined)),
    },
    {
      path: '/proposals',
      title: 'Proposal 1',
      mock: (promise: Promise<unknown>) =>
        vi
          .spyOn(api.proposals, 'remove')
          .mockReturnValue(promise.then(() => undefined)),
    },
    {
      path: '/evals',
      title: 'Run 1',
      mock: (promise: Promise<{ deleted: number }>) =>
        vi.spyOn(api.evals, 'remove').mockReturnValue(promise),
    },
    {
      path: '/eval-configs',
      title: 'Suite 1',
      mock: (promise: Promise<{ deleted: number }>) =>
        vi.spyOn(api.evalConfigs.suites, 'remove').mockReturnValue(promise),
    },
  ];
  it.each(deletions)(
    'does not leave B when an A delete finishes on $path',
    async (resource) => {
      const pending = deferred<{ deleted: number }>();
      const remove = resource.mock(pending.promise);
      renderRoute(`${resource.path}/1`);
      await heading(resource.title);
      fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0]);
      await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
      expect(remove.mock.calls[0]).toEqual(
        resource.path.startsWith('/harness') ? ['rule', 1] : [1],
      );
      go(`${resource.path}/2`);
      const title = resource.title.replace('1', '2');
      await heading(title);
      await act(async () => pending.resolve({ deleted: 1 }));
      expectRoute(`${resource.path}/2`);
      expect(await heading(title)).toBeVisible();
    },
  );

  it('keeps B selected when an A version save finishes, including its captured metadata target', async () => {
    const pending = deferred<HarnessItem>();
    vi.mocked(api.harness.items.updateContent).mockReturnValue(pending.promise);
    renderRoute('/harness/rule/1');
    await heading('Item 1');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'saved_a' },
    });
    fireEvent.change(screen.getByLabelText('Body'), {
      target: { value: 'Updated A body' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.harness.items.updateContent).toHaveBeenCalledWith(
        'rule',
        1,
        expect.objectContaining({ body: 'Updated A body' }),
      ),
    );
    go('/harness/rule/2');
    await heading('Item 2');
    await act(async () => pending.resolve(harness(3)));
    expect(api.harness.items.updateMetadata).toHaveBeenCalledWith(
      'rule',
      3,
      expect.objectContaining({ name: 'saved_a' }),
    );
    expectRoute('/harness/rule/2');
    expect(await heading('Item 2')).toBeVisible();
  });

  it('does not navigate after an old harness restore finishes', async () => {
    const pending = deferred<HarnessItem>();
    vi.mocked(api.harness.items.history).mockResolvedValueOnce([harness(101)]);
    vi.mocked(api.harness.items.updateContent).mockReturnValue(pending.promise);
    renderRoute('/harness/rule/1');
    await heading('Item 1');
    fireEvent.click(await screen.findByText('v101'));
    fireEvent.click(screen.getByRole('button', { name: 'Restore v101' }));
    expect(api.harness.items.updateContent).toHaveBeenCalledWith(
      'rule',
      1,
      harness(101).content,
    );
    go('/harness/rule/2');
    await heading('Item 2');
    await act(async () => pending.resolve(harness(3)));
    expectRoute('/harness/rule/2');
  });

  it('does not replace B with a pending A review result', async () => {
    const pending = deferred<Proposal>();
    vi.mocked(api.proposals.approve).mockReturnValue(pending.promise);
    renderRoute('/proposals/1');
    await heading('Proposal 1');
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(api.proposals.approve).toHaveBeenCalledWith(1);
    go('/proposals/2');
    await heading('Proposal 2');
    await act(async () =>
      pending.resolve({ ...proposal(1), status: 'approved' }),
    );
    expect(await heading('Proposal 2')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
    expectRoute('/proposals/2');
  });

  it.each(['/plans', '/eval-configs'])(
    'does not leave B when a pending creation finishes on %s',
    async (path) => {
      const pending = deferred<Plan & EvalSuite>();
      const create =
        path === '/plans'
          ? vi.spyOn(api.plans, 'create').mockReturnValue(pending.promise)
          : vi
              .spyOn(api.evalConfigs.suites, 'create')
              .mockReturnValue(pending.promise);
      const { container } = renderRoute(`${path}/new`);
      fireEvent.change(nameField(path), {
        target: { value: 'Submitted new resource' },
      });
      if (path === '/plans') {
        fireEvent.change(screen.getByLabelText('Plan content'), {
          target: { value: 'Submitted body' },
        });
      } else {
        const fields = container.querySelectorAll('.eval-suite-fields input');
        fireEvent.change(fields[0], { target: { value: 'rules' } });
        fireEvent.change(fields[1], { target: { value: 'core' } });
        fireEvent.change(container.querySelector('textarea')!, {
          target: { value: 'Submitted judge prompt' },
        });
      }
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      expect(create).toHaveBeenCalledTimes(1);
      expect(create.mock.calls[0][0]).toEqual(
        expect.objectContaining(
          path === '/plans'
            ? { title: 'Submitted new resource', body: 'Submitted body' }
            : {
                name: 'Submitted new resource',
                judge_prompt: 'Submitted judge prompt',
              },
        ),
      );
      go(`${path}/2`);
      await heading(path === '/plans' ? 'Plan 2' : 'Suite 2');
      await act(async () => pending.resolve({ ...plan(3), ...suite(3) }));
      expectRoute(`${path}/2`);
    },
  );

  it('clears A scenario drafts and creates only in suite B after navigation', async () => {
    const create = vi
      .spyOn(api.evalConfigs.scenarios, 'create')
      .mockResolvedValue({ ...suite(2).scenarios![0], id: 21, name: 'new_b' });
    renderRoute('/eval-configs/1');
    await heading('Suite 1');
    fireEvent.click(screen.getByRole('button', { name: '+ Add Scenario' }));
    fireEvent.change(screen.getByPlaceholderText('scenario_name'), {
      target: { value: 'draft_a' },
    });
    go('/eval-configs/2');
    await heading('Suite 2');
    expect(screen.queryByDisplayValue('draft_a')).not.toBeInTheDocument();
    expect(screen.queryByText('Scenario 1')).not.toBeInTheDocument();
    expect(screen.getByText('Scenario 2')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '+ Add Scenario' }));
    fireEvent.change(screen.getByPlaceholderText('scenario_name'), {
      target: { value: 'new_b' },
    });
    fireEvent.change(screen.getByPlaceholderText('Scenario prompt...'), {
      target: { value: 'Prompt B' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(2, {
        name: 'new_b',
        prompt: 'Prompt B',
        enabled: true,
      }),
    );
    expectRoute('/eval-configs/2');
  });
});
