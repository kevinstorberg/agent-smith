import { type ReactElement } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { NotificationProvider } from './context/NotificationContext';

interface ProvidersOptions extends RenderOptions {
  initialEntries?: string[];
}

export function renderWithProviders(ui: ReactElement, options: ProvidersOptions = {}) {
  const { initialEntries = ['/'], ...renderOptions } = options;
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <NotificationProvider>{ui}</NotificationProvider>
    </MemoryRouter>,
    renderOptions,
  );
}
