import { lazy, Suspense } from 'react';

type MarkdownPreviewProps = {
  children: string;
};

const MarkdownPreviewImpl = lazy(() =>
  import('./MarkdownPreviewImpl').then((module) => ({ default: module.MarkdownPreviewImpl })),
);

export function MarkdownPreview({ children }: MarkdownPreviewProps) {
  return (
    <Suspense fallback={<div className="loading">Loading preview...</div>}>
      <MarkdownPreviewImpl>{children}</MarkdownPreviewImpl>
    </Suspense>
  );
}
