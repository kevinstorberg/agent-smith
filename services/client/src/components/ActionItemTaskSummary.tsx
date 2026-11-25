import type { ReactNode } from 'react';
import type { ActionItemRow } from '../api';
import './actionItemTaskSummary.css';

export function ActionItemTitleText({
  children,
  emphasized = true,
}: {
  children: ReactNode;
  emphasized?: boolean;
}) {
  return (
    <span className={emphasized ? 'action-item-task-title' : undefined}>
      {children}
    </span>
  );
}

export function ActionItemTopics({
  item,
  showProject = true,
  quiet = false,
}: {
  item: Pick<ActionItemRow, 'project' | 'tags'>;
  showProject?: boolean;
  quiet?: boolean;
}) {
  return (
    <span className={quiet ? 'action-item-task-topics' : undefined}>
      {showProject && item.project && (
        <span className="tag tag-project">{item.project}</span>
      )}
      {item.tags.map((tag) => (
        <span className="tag" key={tag}>
          {tag}
        </span>
      ))}
    </span>
  );
}
