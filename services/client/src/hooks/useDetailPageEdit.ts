import { useState, useCallback } from 'react';

export interface UseDetailPageEditOptions<T> {
  initialData?: T | null;
  isNew?: boolean;
  onCancel?: () => void;
}

export interface UseDetailPageEditReturn<T> {
  editing: boolean;
  saving: boolean;
  editValues: Partial<T>;
  setEditValue: <K extends keyof T>(key: K, value: T[K]) => void;
  setEditValues: (values: Partial<T>) => void;
  startEditing: (data?: T) => void;
  cancelEditing: () => void;
  setSaving: (saving: boolean) => void;
  resetToInitial: (data: T) => void;
}

/**
 * Hook for managing edit/view mode state in detail pages.
 * Provides unified state management for editing, saving, and field updates.
 *
 * @example
 * const { editing, editValues, setEditValue, startEditing, save } = useDetailPageEdit({
 *   initialData: item,
 *   isNew: false,
 * });
 */
export function useDetailPageEdit<T extends object>(
  options: UseDetailPageEditOptions<T> = {}
): UseDetailPageEditReturn<T> {
  const { initialData, isNew = false, onCancel } = options;

  const [editing, setEditing] = useState(isNew);
  const [saving, setSaving] = useState(false);
  const [editValues, setEditValues] = useState<Partial<T>>({});

  const setEditValue = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setEditValues(prev => ({ ...prev, [key]: value }));
  }, []);

  const startEditing = useCallback((data?: T) => {
    const sourceData = data || initialData;
    if (sourceData) {
      setEditValues({ ...sourceData });
    }
    setEditing(true);
  }, [initialData]);

  const cancelEditing = useCallback(() => {
    if (isNew && onCancel) {
      onCancel();
      return;
    }
    setEditing(false);
    // Reset to initial data on cancel
    if (initialData) {
      setEditValues({ ...initialData });
    }
  }, [isNew, onCancel, initialData]);

  const resetToInitial = useCallback((data: T) => {
    setEditValues({ ...data });
  }, []);

  return {
    editing,
    saving,
    editValues,
    setEditValue,
    setEditValues,
    startEditing,
    cancelEditing,
    setSaving,
    resetToInitial,
  };
}
