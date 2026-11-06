import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '../../test-utils';
import { AuditIndexPage } from '../AuditIndexPage';
import { ProposalsIndexPage } from '../ProposalsIndexPage';
import { EvalSuitesPage } from '../EvalSuitesPage';
import { api } from '../../api';
import {
  defaultView,
  mergeViewCookie,
  readViewCookie,
} from '../../utils/viewPreferences';

vi.mock('../../api', () => ({
  api: {
    audit: { list: vi.fn(), counts: vi.fn() },
    proposals: {
      list: vi.fn(),
      counts: vi.fn(),
      generate: vi.fn(),
      approve: vi.fn(),
      reject: vi.fn(),
    },
    evalConfigs: { suites: { list: vi.fn(), update: vi.fn() } },
  },
}));
beforeEach(() => {
  document.cookie = 'agent-smith.ui.v1=; Path=/; Max-Age=0';
  vi.clearAllMocks();
  vi.mocked(api.audit.list).mockResolvedValue({ items: [], total: 100 });
  vi.mocked(api.audit.counts).mockResolvedValue({
    claude: 0,
    codex: 0,
    gemini: 0,
  });
  vi.mocked(api.proposals.list).mockResolvedValue({ items: [], total: 100 });
  vi.mocked(api.proposals.counts).mockResolvedValue({
    pending: 0,
    approved: 0,
    rejected: 0,
  });
  vi.mocked(api.evalConfigs.suites.list).mockResolvedValue({
    items: [],
    total: 100,
  });
});

const otherView = () =>
  mergeViewCookie('', 'jobs', { ...defaultView('jobs'), q: 'keep jobs' });
const cases = [
  {
    name: 'Audit',
    view: <AuditIndexPage />,
    route: '/audit',
    list: api.audit.list,
    cookie: () =>
      mergeViewCookie(otherView(), 'audit', {
        ...defaultView('audit'),
        q: 'Read',
        project: 'repo',
        agent: 'codex',
        status: 'error',
        sort: 'duration',
        limit: 25,
        offset: 50,
      }),
    expected: [
      {
        q: 'Read',
        project: 'repo',
        agent: 'codex',
        status: 'error',
        sort: 'duration',
      },
      { limit: 25, offset: 50 },
    ],
    sortLabel: 'Sort',
    nextSort: 'oldest',
    updatedExpected: [
      {
        q: 'Read',
        project: 'repo',
        agent: 'codex',
        status: 'error',
        sort: 'oldest',
      },
      { limit: 25, offset: 0 },
    ],
  },
  {
    name: 'Proposals',
    view: <ProposalsIndexPage />,
    route: '/proposals',
    list: api.proposals.list,
    cookie: () =>
      mergeViewCookie(otherView(), 'proposals', {
        ...defaultView('proposals'),
        q: 'review',
        status: 'approved',
        sort: 'oldest',
        limit: 25,
        offset: 50,
      }),
    expected: [
      'approved',
      { q: 'review', sort: 'oldest', limit: 25, offset: 50 },
    ],
    sortLabel: 'Sort proposals',
    nextSort: 'newest',
    updatedExpected: [
      'approved',
      { q: 'review', sort: 'newest', limit: 25, offset: 0 },
    ],
  },
  {
    name: 'Eval suites',
    view: <EvalSuitesPage />,
    route: '/eval-configs',
    list: api.evalConfigs.suites.list,
    cookie: () =>
      mergeViewCookie(otherView(), 'evalSuites', {
        ...defaultView('evalSuites'),
        q: 'quality',
        enabled: 'false',
        sort: 'updated',
        limit: 25,
        offset: 50,
      }),
    expected: [
      {
        q: 'quality',
        enabled: 'false',
        enabled_only: 'false',
        sort: 'updated',
        limit: '25',
        offset: '50',
      },
    ],
    sortLabel: 'Sort eval suites',
    nextSort: 'name',
    updatedExpected: [
      {
        q: 'quality',
        enabled: 'false',
        enabled_only: 'false',
        sort: 'name',
        limit: '25',
        offset: '0',
      },
    ],
  },
];

describe('Operations preference consumers', () => {
  it.each(cases)(
    'restores $name criteria and page before the first request and updates only that view',
    async ({
      view,
      route,
      list,
      cookie,
      expected,
      sortLabel,
      nextSort,
      updatedExpected,
    }) => {
      document.cookie = cookie();
      renderWithProviders(view, { initialEntries: [route] });
      await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
      expect(list).toHaveBeenCalledWith(...expected);
      fireEvent.change(screen.getByRole('combobox', { name: sortLabel }), {
        target: { value: nextSort },
      });
      await waitFor(() =>
        expect(list).toHaveBeenLastCalledWith(...updatedExpected),
      );
      expect(
        readViewCookie(document.cookie).find((entry) => entry.key === 'jobs'),
      ).toEqual({ key: 'jobs', values: { q: 'keep jobs' } });
      expect(readViewCookie(document.cookie)[0].values).toMatchObject({
        limit: 25,
      });
    },
  );
});
