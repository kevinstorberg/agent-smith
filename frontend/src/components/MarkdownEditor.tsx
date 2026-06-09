import { lazy, Suspense } from 'react';

type MarkdownEditorProps = {
  value: string;
  onChange: (value?: string) => void;
  height?: number;
};

const MDEditor = lazy(() => import('@uiw/react-md-editor'));

export function MarkdownEditor(props: MarkdownEditorProps) {
  return (
    <Suspense fallback={<div className="loading">Loading editor...</div>}>
      <MDEditor {...props} />
    </Suspense>
  );
}
