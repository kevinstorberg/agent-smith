interface Props {
  id?: string;
  error?: string | null;
  maxLength?: number;
  currentLength?: number;
}

export function FieldError({ id, error, maxLength, currentLength }: Props) {
  const nearLimit = maxLength && currentLength && currentLength > maxLength * 0.8;
  const overLimit = maxLength && currentLength && currentLength > maxLength;

  if (!error && !nearLimit) return null;

  return (
    <div id={id} className="field-feedback">
      {error ? (
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--danger-text)' }}>{error}</span>
      ) : <span />}
      {maxLength && currentLength !== undefined && nearLimit && (
        <span style={{ fontSize: 'var(--font-xs)', color: overLimit ? 'var(--danger-text)' : 'var(--text-muted)' }}>
          {currentLength} / {maxLength}
        </span>
      )}
    </div>
  );
}
