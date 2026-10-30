export interface DetailPageHeaderProps {
  backTo: { label: string; path: string };
  editing: boolean;
  saving: boolean;
  onEdit?: () => void;
  onSave?: () => void;
  onCancel?: () => void;
  onDelete?: () => void;
  onNavigateBack?: () => void;
  deleteConfirmMessage?: string;
  showActions?: boolean;
  disabled?: boolean;
  saveDisabled?: boolean;
}

/**
 * Reusable header component for detail pages.
 * Handles back navigation and edit/save/cancel/delete actions.
 */
export function DetailPageHeader({
  backTo,
  editing,
  saving,
  onEdit,
  onSave,
  onCancel,
  onDelete,
  onNavigateBack,
  deleteConfirmMessage,
  showActions = true,
  disabled = false,
  saveDisabled = false,
}: DetailPageHeaderProps) {
  const handleDelete = () => {
    if (deleteConfirmMessage && !confirm(deleteConfirmMessage)) {
      return;
    }
    onDelete?.();
  };

  const handleBack = () => {
    if (onNavigateBack) {
      onNavigateBack();
    } else {
      window.history.back();
    }
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
      <button
        style={{
          color: 'var(--text-muted)',
          cursor: 'pointer',
          fontSize: 'var(--font-base)',
          background: 'none',
          border: 'none',
          fontFamily: 'var(--font)',
          textDecoration: 'underline',
        }}
        onClick={handleBack}
      >
        &larr; Back to {backTo.label}
      </button>
      {showActions && (
        <div style={{ display: 'flex', gap: 8 }}>
          {!editing && (
            <>
              <button className="btn" onClick={onEdit} disabled={disabled}>
                Edit
              </button>
              {onDelete && (
                <button
                  className="btn btn-danger"
                  onClick={handleDelete}
                  disabled={disabled}
                >
                  Delete
                </button>
              )}
            </>
          )}
          {editing && (
            <>
              <button
                className="btn"
                onClick={onSave}
                disabled={saving || disabled || saveDisabled}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button className="btn" onClick={onCancel} disabled={saving || disabled}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
