interface Props {
  error?: string | null;
  maxLength?: number;
  currentLength?: number;
}

export function FieldError({ error, maxLength, currentLength }: Props) {
  const nearLimit = maxLength && currentLength && currentLength > maxLength * 0.8;
  const overLimit = maxLength && currentLength && currentLength > maxLength;

  if (!error && !nearLimit) return null;

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
      {error ? (
        <span style={{ fontSize: 'var(--font-xs)', color: 'var(--highlight)' }}>{error}</span>
      ) : <span />}
      {maxLength && currentLength !== undefined && nearLimit && (
        <span style={{ fontSize: 'var(--font-xs)', color: overLimit ? 'var(--highlight)' : 'var(--text-muted)' }}>
          {currentLength} / {maxLength}
        </span>
      )}
    </div>
  );
}
