import { useLayoutEffect, useRef, useState } from 'react';
import type { DragStart, DropResult } from '@hello-pangea/dnd';
import {
  api,
  type ActionItemEpic,
  type ActionItemEpicCreate,
  type ActionItemEpicGroup,
  type ActionItemEpicReference,
  type ActionItemFilters,
  type ActionItemGroupedPage,
  type ActionItemQueueRoot,
  type ActionItemRow,
} from '../api';
import { usePagination, type PaginationOptions } from './usePagination';
import { usePolling } from './usePolling';
import { useActionItemWrites } from './useActionItemWrites';
import {
  projectTargets,
  useActionItemProjectDrag,
  type ProjectDragSnapshot,
} from './useActionItemProjectDrag';

export const queueIdentity = (root: ActionItemQueueRoot) =>
  root.kind === 'item' ? `item:${root.item.id}` : `epic:${root.epic.id}`;
export const epicReference = (
  epic: ActionItemEpic,
): ActionItemEpicReference => ({
  id: epic.id,
  expected_revision: epic.revision,
  cohort: epic.cohort,
});
const reference = (root: ActionItemQueueRoot) =>
  root.kind === 'item'
    ? {
        kind: 'item' as const,
        id: root.item.id,
        expected_revision: root.item.revision,
      }
    : { kind: 'epic' as const, ...epicReference(root.epic) };
const rootSignature = (roots: ActionItemQueueRoot[]) =>
  JSON.stringify(
    roots.map((root) =>
      root.kind === 'item'
        ? [root.kind, root.item.id, root.item.revision, root.position]
        : [
            root.kind,
            root.epic.id,
            root.epic.revision,
            root.epic.cohort,
            root.epic.position,
          ],
    ),
  );
const childSignature = (group: ActionItemEpicGroup) =>
  JSON.stringify(
    group.children.map((child) => [
      child.item.id,
      child.item.revision,
      child.position,
    ]),
  );
interface GroupDrag extends ProjectDragSnapshot {
  roots: ActionItemQueueRoot[];
  items: ActionItemRow[];
  view: string;
  signature: string;
  itemId?: string;
  parent?: ActionItemEpicGroup;
}

export function useActionItemGroupedQueue({
  filters,
  criteria,
  viewKey,
  reorderableView,
  criteriaPending,
  pagination,
}: {
  filters: ActionItemFilters;
  criteria: string;
  viewKey: string;
  reorderableView: boolean;
  criteriaPending: boolean;
  pagination: PaginationOptions;
}) {
  const [snapshot, setSnapshot] = useState<GroupDrag | null>(null);
  const drag = useRef<GroupDrag | null>(null);
  const projectTabsRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [showing, setShowing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [created, setCreated] = useState<ActionItemEpic | null>(null);
  const [closed, setClosed] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<{ id: number; view: string } | null>(
    null,
  );
  const list = usePagination<ActionItemQueueRoot>(
    (limit, offset) => api.actionItemQueue.list({ ...filters, limit, offset }),
    [criteria],
    10,
    pagination,
  );
  const view = JSON.stringify([viewKey, list.limit, list.offset]);
  const readable =
    list.dataCurrent && !criteriaPending && !list.loading && !list.error;
  const signature = rootSignature(list.items);
  const current = useRef({ view, signature, readable, items: list.items });
  useLayoutEffect(() => {
    current.current = { view, signature, readable, items: list.items };
  });
  function canWrite() {
    return readable && !drag.current && !writes.writing.current;
  }
  const writes = useActionItemWrites({
    refresh: list.refresh,
    view,
    paused: Boolean(snapshot),
    canStart: canWrite,
    onError: setReviewError,
    onFinish: () => setSnapshot(null),
  });
  const busy = writes.busy;
  const freezeControls = Boolean(snapshot) || busy || editing || showing;
  const canAct = () => canWrite() && !editing && !showing;
  const roots = snapshot?.roots ?? list.items;
  const flatten = (items: ActionItemQueueRoot[]) =>
    items.flatMap((root) => (root.kind === 'item' ? [root] : root.children));
  function locate(item: ActionItemRow) {
    for (const root of list.items) {
      if (
        root.kind === 'item' &&
        root.item.id === item.id &&
        root.item.revision === item.revision
      )
        return { entry: root, parent: undefined };
      if (root.kind === 'epic') {
        const entry = root.children.find(
          (child) =>
            child.item.id === item.id && child.item.revision === item.revision,
        );
        if (entry) return { entry, parent: root };
      }
    }
    return null;
  }
  function rememberFocus() {
    const focused = document.activeElement;
    writes.focus.current = {
      handle: focused instanceof HTMLButtonElement ? focused : null,
      view,
      fallback:
        focused instanceof HTMLElement
          ? (focused.closest<HTMLElement>('.action-items-container') ??
            undefined)
          : undefined,
    };
  }
  async function rowWrite(
    item: ActionItemRow,
    operation: () => Promise<unknown>,
    message: string,
  ) {
    if (!canWrite() || !locate(item)) return;
    if (!snapshot) rememberFocus();
    setReviewError(null);
    return Boolean(
      await writes.runWrite(operation, message, { pendingId: item.id }),
    );
  }
  async function changeStatus(item: ActionItemRow) {
    await rowWrite(
      item,
      () =>
        api.actionItems.update(item.id, {
          expected_revision: item.revision,
          status: item.status === 'open' ? 'completed' : 'open',
        }),
      'Could not update this action item.',
    );
  }
  async function removeItem(item: ActionItemRow) {
    await rowWrite(
      item,
      () => api.actionItems.remove(item.id, item.revision),
      'Could not delete this action item.',
    );
  }
  async function setEpic(
    item: ActionItemRow,
    destination: ActionItemEpic | null,
  ) {
    const located = locate(item);
    if (!located) return;
    const success = await rowWrite(
      item,
      () =>
        api.actionItemQueue.setEpic(item.id, {
          expected_revision: item.revision,
          expected_parent: located.parent
            ? epicReference(located.parent.epic)
            : null,
          destination: destination ? epicReference(destination) : null,
        }),
      'Could not move this action item to the Epic.',
    );
    if (success && destination)
      setClosed((previous) => {
        const next = new Set(previous);
        next.delete(destination.id);
        return next;
      });
    return Boolean(success);
  }
  function membership(item: ActionItemRow) {
    const located = locate(item);
    if (!located)
      throw new Error('The list changed. Refresh before grouping this item.');
    return {
      expected_revision: item.revision,
      expected_parent: located.parent
        ? epicReference(located.parent.epic)
        : null,
    };
  }
  async function createEpic(payload: ActionItemEpicCreate) {
    setReviewError(null);
    const result = await writes.runWrite(
      () => api.actionItemEpics.create(payload),
      'Could not create this Epic.',
      { order: true },
    );
    if (result && writes.mounted.current) {
      setCreated(result.value);
      setClosed((previous) => {
        const next = new Set(previous);
        next.delete(result.value.id);
        return next;
      });
    }
    return Boolean(result);
  }
  async function showCreated(onLocated: (position: number) => void) {
    if (!created || !canAct() || showing) return;
    const capturedView = view;
    setShowing(true);
    try {
      const catalog = await api.actionItemEpics.list();
      if (!writes.mounted.current || current.current.view !== capturedView)
        return;
      const epic = catalog.items.find((item) => item.id === created.id);
      if (!epic || !Number.isSafeInteger(epic.position) || epic.position <= 0)
        throw new Error('This Epic is no longer available. Refresh the list.');
      onLocated(epic.position);
    } catch (failure) {
      if (writes.mounted.current && current.current.view === capturedView)
        setReviewError(
          failure instanceof Error
            ? failure.message
            : 'Could not locate this Epic.',
        );
    } finally {
      if (writes.mounted.current) setShowing(false);
    }
  }
  async function renameEpic(epic: ActionItemEpic, title: string) {
    setReviewError(null);
    rememberFocus();
    return Boolean(
      await writes.runWrite(
        () =>
          api.actionItemEpics.rename(epic.id, {
            title,
            expected_revision: epic.revision,
          }),
        'Could not rename this Epic.',
        { pendingId: -epic.id },
      ),
    );
  }
  async function removeEpic(epic: ActionItemEpic) {
    if (!canAct()) return;
    setReviewError(null);
    rememberFocus();
    const removed = await writes.runWrite(
      () =>
        api.actionItemEpics.remove(epic.id, {
          expected_revision: epic.revision,
          cohort: epic.cohort,
        }),
      'Could not remove this Epic.',
      { pendingId: -epic.id },
    );
    if (removed && writes.mounted.current)
      setCreated((current) => (current?.id === epic.id ? null : current));
  }
  function canMoveRoot(root: ActionItemQueueRoot, edge: 'top' | 'bottom') {
    const index = list.items.findIndex(
      (row) => queueIdentity(row) === queueIdentity(root),
    );
    return (
      canAct() &&
      reorderableView &&
      index >= 0 &&
      (edge === 'top'
        ? list.offset + index > 0
        : list.offset + index < list.total - 1)
    );
  }
  function canMoveToEdge(item: ActionItemRow, edge: 'top' | 'bottom') {
    const located = locate(item);
    if (!located || item.status !== 'open' || !canAct() || !reorderableView)
      return false;
    if (!located.parent) return canMoveRoot(located.entry, edge);
    const index = located.parent.children.indexOf(located.entry);
    return edge === 'top'
      ? index > 0
      : index < located.parent.children.length - 1;
  }
  async function moveRoot(root: ActionItemQueueRoot, edge: 'top' | 'bottom') {
    if (!canMoveRoot(root, edge)) return;
    rememberFocus();
    setReviewError(null);
    const captured = current.current;
    await writes.runWrite(
      async () => {
        const boundary = await api.actionItemQueue.list({
          ...filters,
          sort: edge === 'top' ? 'manual' : 'manual_desc',
          limit: 1,
          offset: 0,
        });
        if (
          !writes.mounted.current ||
          current.current.view !== captured.view ||
          current.current.signature !== captured.signature ||
          !current.current.readable
        )
          return;
        const anchor = boundary.items[0];
        if (!anchor)
          throw new Error(
            'The list changed. Refresh before moving this entry.',
          );
        if (queueIdentity(anchor) === queueIdentity(root)) return;
        await api.actionItemQueue.move({
          source: reference(root),
          ...(edge === 'top'
            ? { before: reference(anchor) }
            : { after: reference(anchor) }),
        });
      },
      'Could not save this order.',
      { order: true },
    );
  }
  async function moveToEdge(item: ActionItemRow, edge: 'top' | 'bottom') {
    const located = locate(item);
    if (!located || !canMoveToEdge(item, edge)) return;
    if (!located.parent) {
      await moveRoot(located.entry, edge);
      return;
    }
    const parent = located.parent;
    const anchor =
      edge === 'top' ? parent.children[0] : parent.children.at(-1)!;
    rememberFocus();
    setReviewError(null);
    await writes.runWrite(
      () =>
        api.actionItemQueue.move({
          source: reference(located.entry),
          parent: epicReference(parent.epic),
          ...(edge === 'top'
            ? { before: reference(anchor) }
            : { after: reference(anchor) }),
        }),
      'Could not save this order.',
      { order: true },
    );
  }
  function startDrag(start?: DragStart) {
    if (!canAct()) return;
    const parent =
      !start || start.source.droppableId === 'action-items'
        ? undefined
        : list.items.find(
            (root): root is ActionItemEpicGroup =>
              root.kind === 'epic' &&
              `epic:${root.epic.id}` === start.source.droppableId,
          );
    const selected = parent
      ? parent.children[start?.source.index ?? 0]
      : list.items[start?.source.index ?? 0];
    if (!selected || (start && queueIdentity(selected) !== start.draggableId))
      return;
    rememberFocus();
    setExpanded(null);
    const captured: GroupDrag = {
      roots: list.items,
      items: flatten(list.items).map((entry) => entry.item),
      view,
      signature,
      itemId: start?.draggableId,
      parent,
      ...(selected.kind === 'item'
        ? {
            projects: projectTargets(projectTabsRef.current),
            project: null,
            mode: start?.mode ?? 'FLUID',
          }
        : {}),
    };
    drag.current = captured;
    setSnapshot(captured);
  }
  async function endDrag(result: DropResult) {
    const captured = drag.current;
    drag.current = null;
    if (!captured || !writes.mounted.current) return;
    const liveParent = captured.parent
      ? current.current.items.find(
          (root): root is ActionItemEpicGroup =>
            root.kind === 'epic' && root.epic.id === captured.parent!.epic.id,
        )
      : undefined;
    const sameChildren =
      !captured.parent ||
      Boolean(
        liveParent &&
        childSignature(captured.parent) === childSignature(liveParent),
      );
    const targets = projectTargets(projectTabsRef.current);
    const sameProjects =
      !captured.projects ||
      (captured.projects.length === targets.length &&
        captured.projects.every(
          (target, index) =>
            target.button === targets[index].button &&
            target.id === targets[index].id &&
            target.name === targets[index].name,
        ));
    if (
      captured.view !== current.current.view ||
      captured.signature !== current.current.signature ||
      !sameProjects ||
      !sameChildren ||
      !current.current.readable ||
      result.reason === 'CANCEL'
    ) {
      setSnapshot(null);
      if (result.reason !== 'CANCEL')
        await list.refresh({ showLoading: false });
      return;
    }
    const siblings = captured.parent?.children ?? captured.roots;
    const source = siblings[result.source.index];
    if (
      !source ||
      queueIdentity(source) !== result.draggableId ||
      (captured.itemId && captured.itemId !== result.draggableId)
    ) {
      setSnapshot(null);
      return;
    }
    if (captured.project && source.kind === 'item') {
      const target = captured.projects?.find(
        (project) => project.name === captured.project,
      );
      if (target && source.item.project !== target.name) {
        if (writes.focus.current) writes.focus.current.fallback = target.button;
        await rowWrite(
          source.item,
          () =>
            api.actionItems.update(source.item.id, {
              expected_revision: source.item.revision,
              project: target.name,
            }),
          'Could not move this action item to the project.',
        );
      } else setSnapshot(null);
      return;
    }
    const destination = result.destination;
    if (
      !reorderableView ||
      !destination ||
      result.source.droppableId !== destination.droppableId ||
      result.source.index === destination.index ||
      destination.index < 0 ||
      destination.index >= siblings.length
    ) {
      setSnapshot(null);
      return;
    }
    const reordered = [...siblings];
    reordered.splice(result.source.index, 1);
    reordered.splice(destination.index, 0, source);
    const next = reordered[destination.index + 1];
    const previous = reordered[destination.index - 1];
    setSnapshot({
      ...captured,
      roots: captured.parent
        ? captured.roots.map((root) =>
            root.kind === 'epic' && root.epic.id === captured.parent!.epic.id
              ? { ...root, children: reordered as typeof root.children }
              : root,
          )
        : reordered,
    });
    setReviewError(null);
    await writes.runWrite(
      () =>
        api.actionItemQueue.move({
          source: reference(source),
          ...(captured.parent
            ? { parent: epicReference(captured.parent.epic) }
            : {}),
          ...(next
            ? { before: reference(next) }
            : { after: reference(previous) }),
        }),
      'Could not save this order.',
      { order: true },
    );
  }
  useActionItemProjectDrag({
    enabled: true,
    drag,
    setSnapshot,
    projectTabsRef,
  });
  usePolling(() => list.refresh({ showLoading: false }), {
    enabled: !snapshot && !busy && !editing && !showing,
  });
  return {
    ...list,
    matchingCount:
      (list.result as ActionItemGroupedPage | null)?.matching_count ?? 0,
    roots,
    source: api.actionItems,
    view,
    criteriaPending,
    snapshot,
    busy,
    savingOrder: writes.savingOrder,
    pendingId: writes.pendingId,
    freezeControls,
    reorderableView,
    projectAssignment: true,
    projectTabsRef,
    canDrag: readable && !busy && !editing && !showing,
    dragSurfaceEnabled: readable && !editing && !showing,
    startDrag,
    endDrag,
    changeStatus,
    removeItem,
    deletionEnabled: true,
    canRemove: canAct,
    canAct,
    canSubmit: () => canWrite() && !showing,
    expandedId: expanded?.view === view ? expanded.id : null,
    setExpanded,
    canMoveToEdge,
    moveToEdge,
    canMoveRoot,
    moveRoot,
    reviewError,
    setReviewError,
    created,
    setCreated,
    editing,
    setEditing,
    createEpic,
    showCreated,
    renameEpic,
    removeEpic,
    setEpic,
    membership,
    parentId: (item: ActionItemRow) => locate(item)?.parent?.epic.id ?? null,
    isOpen: (id: number) => !closed.has(id),
    toggle: (id: number) => {
      if (freezeControls) return;
      setClosed((previous) => {
        const next = new Set(previous);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    displayed: flatten(roots).map((entry) => entry.item),
  };
}
export type ActionItemGroupedQueue = ReturnType<
  typeof useActionItemGroupedQueue
>;
