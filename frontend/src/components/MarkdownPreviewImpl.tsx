import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type MarkdownPreviewImplProps = {
  children: string;
};

export function MarkdownPreviewImpl({ children }: MarkdownPreviewImplProps) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>;
}
