import { fireEvent, screen } from '@testing-library/react';

function triggerFor(name: string) {
  const epic = /^Move Epic (.+) to (?:top|bottom)$/.exec(name);
  if (epic) return `Actions for Epic ${epic[1]}`;
  if (name === 'New project' || name === 'Delete project')
    return 'Project options';
  const item =
    /^(?:Edit|Delete) (.+)$/.exec(name) ??
    /^Move (.+) (?:to|out of) Epic$/.exec(name) ??
    /^Move (.+) to (?:top|bottom)(?: of (?:Epic|matching list))?$/.exec(name);
  if (!item) throw new Error(`No action disclosure for ${name}`);
  return `More actions for ${item[1]}`;
}

export function actionButton(name: string): HTMLElement {
  const trigger = screen.getByRole('button', {
    name: triggerFor(name),
  });
  if (
    !trigger.hasAttribute('disabled') &&
    trigger.getAttribute('aria-expanded') === 'false'
  ) {
    fireEvent.click(trigger);
  }
  return screen.getByRole('button', { name, hidden: true });
}

export async function findActionButton(name: string): Promise<HTMLElement> {
  await screen.findByRole('button', { name: triggerFor(name) });
  return actionButton(name);
}

export function showFilters() {
  const trigger = screen.getByRole('button', { name: /^More filters/ });
  if (trigger.getAttribute('aria-expanded') === 'false')
    fireEvent.click(trigger);
}

export function filterCheckbox(name: string): HTMLElement {
  showFilters();
  return screen.getByRole('checkbox', { name, hidden: true });
}

export async function findFilterCheckbox(name: string): Promise<HTMLElement> {
  await screen.findByRole('button', { name: /^More filters/ });
  return filterCheckbox(name);
}
