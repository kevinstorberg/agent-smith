import { fireEvent, waitFor, within } from '@testing-library/react';
import { expect } from 'vitest';

export function openEpicPicker(trigger: HTMLElement) {
  if (trigger.getAttribute('aria-expanded') !== 'true')
    fireEvent.click(trigger);
  const panel = document.getElementById(
    trigger.getAttribute('aria-controls') ?? '',
  );
  if (!panel || trigger.getAttribute('aria-expanded') !== 'true')
    throw new Error('Epic picker is unavailable');
  return panel;
}

export function chooseEpic(trigger: HTMLElement, value: string) {
  const panel = openEpicPicker(trigger);
  const choices = Array.from(
    panel.querySelectorAll<HTMLButtonElement>('button[value]'),
  ).filter((button) => button.value === value);
  if (choices.length !== 1)
    throw new Error(`Expected one displayed Epic choice for ${value}`);
  fireEvent.click(choices[0]);
}

export async function findEpicChoice(trigger: HTMLElement, name: string) {
  await waitFor(() => expect(trigger).toBeEnabled());
  return within(openEpicPicker(trigger)).findByRole('button', {
    name,
  });
}

export function expectEpicSelection(trigger: HTMLElement, label: string) {
  expect(trigger.querySelector('span:first-child')?.textContent).toBe(label);
}
