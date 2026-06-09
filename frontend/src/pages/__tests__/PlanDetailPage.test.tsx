import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, act } from '@testing-library/react';
import { renderWithProviders } from '../../test-utils';
import { PlanDetailPage } from '../PlanDetailPage';

vi.mock('@uiw/react-md-editor', () => ({
  default: (props: any) => (
    <textarea
      data-testid="md-editor"
      value={props.value}
      onChange={(e: any) => props.onChange?.(e.target.value)}
    />
  ),
}));

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}));

vi.mock('remark-gfm', () => ({ default: {} }));

const mockNavigate = vi.fn();
let mockParams: Record<string, string> = {};

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useParams: () => mockParams,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../../api', () => ({
  api: {
    plans: {
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

import { api } from '../../api';

const mockGet = api.plans.get as ReturnType<typeof vi.fn>;
const mockCreate = api.plans.create as ReturnType<typeof vi.fn>;
const mockUpdate = api.plans.update as ReturnType<typeof vi.fn>;
const mockRemove = api.plans.remove as ReturnType<typeof vi.fn>;

const fakePlan = {
  id: 42,
  title: 'Test Plan',
  body: '# Hello',
  project: 'my-project',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  mockParams = { id: '42' };
  mockGet.mockResolvedValue(fakePlan);
  mockCreate.mockResolvedValue({ ...fakePlan, id: 99 });
  mockUpdate.mockResolvedValue(fakePlan);
  mockRemove.mockResolvedValue(undefined);
});

describe('PlanDetailPage', () => {
  describe('create mode', () => {
    beforeEach(() => {
      mockParams = { id: 'new' };
    });

    it('starts in editing mode for new plans', async () => {
      renderWithProviders(<PlanDetailPage />);

      expect(screen.getByPlaceholderText('Plan title')).toBeInTheDocument();
      expect(await screen.findByTestId('md-editor')).toBeInTheDocument();
      expect(screen.getByText('Save')).toBeInTheDocument();
      expect(screen.getByText('Cancel')).toBeInTheDocument();
    });

    it('navigates back when cancel is clicked on new plan', () => {
      renderWithProviders(<PlanDetailPage />);

      fireEvent.click(screen.getByText('Cancel'));
      expect(mockNavigate).toHaveBeenCalledWith('/plans');
    });

    it('validates title is required before saving', async () => {
      renderWithProviders(<PlanDetailPage />);

      const editor = screen.getByTestId('md-editor');
      fireEvent.change(editor, { target: { value: 'Some body' } });

      fireEvent.click(screen.getByText('Save'));

      // Validation prevents API call
      expect(mockCreate).not.toHaveBeenCalled();
    });

    it('validates body is required before saving', async () => {
      renderWithProviders(<PlanDetailPage />);

      const titleInput = screen.getByPlaceholderText('Plan title');
      fireEvent.change(titleInput, { target: { value: 'My Title' } });

      fireEvent.click(screen.getByText('Save'));

      // Validation prevents API call
      expect(mockCreate).not.toHaveBeenCalled();
    });

    it('calls create API and navigates on successful save', async () => {
      renderWithProviders(<PlanDetailPage />);

      fireEvent.change(screen.getByPlaceholderText('Plan title'), {
        target: { value: 'New Plan Title' },
      });
      fireEvent.change(screen.getByTestId('md-editor'), {
        target: { value: 'Plan body content' },
      });

      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(mockCreate).toHaveBeenCalledWith({
          title: 'New Plan Title',
          body: 'Plan body content',
          project: null,
        });
      });

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/plans/99', { replace: true });
      });
    });
  });

  describe('view mode', () => {
    it('loads and displays plan data', async () => {
      renderWithProviders(<PlanDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Test Plan')).toBeInTheDocument();
      });

      expect(await screen.findByTestId('markdown')).toHaveTextContent('# Hello');
      expect(screen.getByText('my-project')).toBeInTheDocument();
      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Delete')).toBeInTheDocument();
    });

    it('shows loading then content once data loads', async () => {
      // Verify the loading -> loaded transition
      let resolveGet: (value: any) => void;
      mockGet.mockReturnValue(new Promise((resolve) => { resolveGet = resolve; }));

      renderWithProviders(<PlanDetailPage />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();

      await act(async () => {
        resolveGet!(fakePlan);
      });

      await waitFor(() => {
        expect(screen.getByText('Test Plan')).toBeInTheDocument();
      });
    });

    it('enters edit mode when Edit button is clicked', async () => {
      renderWithProviders(<PlanDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Edit')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Edit'));

      expect(screen.getByPlaceholderText('Plan title')).toHaveValue('Test Plan');
      expect(screen.getByTestId('md-editor')).toHaveValue('# Hello');
    });

    it('calls update API on save in edit mode', async () => {
      renderWithProviders(<PlanDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Edit')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Edit'));

      fireEvent.change(screen.getByPlaceholderText('Plan title'), {
        target: { value: 'Updated Title' },
      });

      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(mockUpdate).toHaveBeenCalledWith(42, {
          title: 'Updated Title',
          body: '# Hello',
          project: 'my-project',
        });
      });
    });

    it('confirms before deleting', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

      renderWithProviders(<PlanDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Delete')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Delete'));

      await waitFor(() => {
        expect(confirmSpy).toHaveBeenCalledWith('Delete plan "Test Plan"?');
        expect(mockRemove).toHaveBeenCalledWith(42);
      });

      confirmSpy.mockRestore();
    });

    it('does not delete when confirm is cancelled', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

      renderWithProviders(<PlanDetailPage />);

      await waitFor(() => {
        expect(screen.getByText('Delete')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Delete'));

      expect(confirmSpy).toHaveBeenCalled();
      expect(mockRemove).not.toHaveBeenCalled();

      confirmSpy.mockRestore();
    });
  });
});
