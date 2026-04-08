import { useState } from 'react';

interface CopyButtonProps {
  text: string;
  style?: React.CSSProperties;
}

export function CopyButton({ text, style }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      onClick={e => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      style={{
        padding: '4px 10px',
        fontSize: 'var(--font-sm)',
        minWidth: 64,
        background: 'var(--surface-hover)',
        color: 'var(--text-muted)',
        border: '1px solid var(--surface-elevated)',
        borderRadius: 'var(--radius)',
        cursor: 'pointer',
        ...style,
      }}
      onFocus={e => {
        e.currentTarget.style.outline = '2px solid var(--info)';
        e.currentTarget.style.outlineOffset = '2px';
      }}
      onBlur={e => {
        e.currentTarget.style.outline = 'none';
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
