import { type ReactElement, type ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { NotificationProvider } from './context/NotificationContext';

interface ProvidersOptions extends RenderOptions {
  initialEntries?: string[];
}

export function renderWithProviders(ui: ReactElement, options: ProvidersOptions = {}) {
  const { initialEntries = ['/'], wrapper: AdditionalWrapper, ...renderOptions } = options;
  function Providers({ children }: { children: ReactNode }) {
    const content = <MemoryRouter initialEntries={initialEntries}>
      <NotificationProvider>{children}</NotificationProvider>
    </MemoryRouter>;
    return AdditionalWrapper ? <AdditionalWrapper>{content}</AdditionalWrapper> : content;
  }
  return render(ui, { ...renderOptions, wrapper: Providers });
}
