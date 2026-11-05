export const MAX_DUE_WINDOW_HOURS = 168;

export interface DeadlineDraft {
  original: string | null;
  initialLocal: string;
  local: string;
  timeZone: string;
}

function timeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function localInput(date: Date) {
  const parts = [
    date.getFullYear(),
    date.getMonth() + 1,
    date.getDate(),
    date.getHours(),
    date.getMinutes(),
  ];
  return `${String(parts[0]).padStart(4, '0')}-${String(parts[1]).padStart(2, '0')}-${String(parts[2]).padStart(2, '0')}T${String(parts[3]).padStart(2, '0')}:${String(parts[4]).padStart(2, '0')}`;
}

export function deadlineDraft(original: string | null = null): DeadlineDraft {
  const local = original ? localInput(new Date(original)) : '';
  return { original, initialLocal: local, local, timeZone: timeZone() };
}

export function changeDeadline(
  draft: DeadlineDraft,
  local: string,
): DeadlineDraft {
  return { ...draft, local, timeZone: timeZone() };
}

export function deadlineValue(draft: DeadlineDraft): string | null {
  // Untouched values retain sub-minute precision and their capture-time local representation.
  if (draft.local === draft.initialLocal) return draft.original;
  if (!draft.local) return null;
  if (draft.timeZone !== timeZone())
    throw new Error(
      'Your time zone changed while editing. Re-enter the due date and time before saving.',
    );
  const date = new Date(draft.local);
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.local) ||
    Number(draft.local.slice(0, 4)) < 1 ||
    !Number.isFinite(date.getTime()) ||
    localInput(date) !== draft.local ||
    date.getUTCFullYear() < 1 ||
    date.getUTCFullYear() > 9999
  ) {
    throw new Error(
      'Enter a valid local date and time. This time may not exist because the clocks change.',
    );
  }
  return date.toISOString();
}

export function deadlineFields(draft: DeadlineDraft): {
  due_at?: string | null;
} {
  const value = deadlineValue(draft);
  return value !== null || draft.original !== null ? { due_at: value } : {};
}
