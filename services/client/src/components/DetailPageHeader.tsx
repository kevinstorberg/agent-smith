import { Link } from 'react-router';

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

  return (
    <div className="detail-page-header">
      {onNavigateBack ? <button type="button" className="detail-back" onClick={onNavigateBack}>
        &larr; Back to {backTo.label}
      </button> : <Link className="detail-back" to={backTo.path}>&larr; Back to {backTo.label}</Link>}
      {showActions && (
        <div className="detail-page-actions">
          {!editing && (
            <>
              <button type="button" className="btn" onClick={onEdit} disabled={disabled}>
                Edit
              </button>
              {onDelete && (
                <button
                  className="btn btn-danger"
                  type="button"
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
                type="button"
                className="btn btn-primary"
                onClick={onSave}
                disabled={saving || disabled || saveDisabled}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button type="button" className="btn" onClick={onCancel} disabled={saving || disabled}>
                Cancel
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
