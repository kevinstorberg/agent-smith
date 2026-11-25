import {
  useLayoutEffect,
  type RefObject,
  type Dispatch,
  type SetStateAction,
} from 'react';
import type { DragStart } from '@hello-pangea/dnd';
import type {
  ActionItemEpic,
  ActionItemQueueRoot,
  ActionItemEntryReference,
} from '../api';

export interface RootOrderTarget {
  element: HTMLElement;
  anchor: ActionItemEntryReference;
  edge: 'before' | 'after';
  label: string;
}

export interface EpicTarget {
  epic: ActionItemEpic | null;
  element: HTMLElement;
}

export function epicTargets(
  container: HTMLElement | null,
  roots: ActionItemQueueRoot[],
): EpicTarget[] {
  return Array.from(
    container?.querySelectorAll<HTMLElement>('[data-epic-drop-target]') ?? [],
  ).flatMap<EpicTarget>((element) => {
    const id = element.dataset.epicDropTarget;
    if (id === 'none') return [{ epic: null, element }];
    const root = roots.find(
      (entry) => entry.kind === 'epic' && String(entry.epic.id) === id,
    );
    return root?.kind === 'epic' ? [{ epic: root.epic, element }] : [];
  });
}

export interface ProjectTarget {
  id: string;
  name: string;
  button: HTMLButtonElement;
}

export function projectTargets(tabs: HTMLDivElement | null): ProjectTarget[] {
  return Array.from(
    tabs?.querySelectorAll<HTMLButtonElement>('button[data-project-id]') ?? [],
    (button) => ({
      id: button.dataset.projectId!,
      name: button.dataset.projectName!,
      button,
    }),
  );
}

function atPoint(element: HTMLElement, x: number, y: number) {
  const bounds = element.getBoundingClientRect();
  return (
    element.isConnected &&
    bounds.width > 0 &&
    bounds.height > 0 &&
    x >= bounds.left &&
    x < bounds.right &&
    y >= bounds.top &&
    y < bounds.bottom
  );
}

function projectAtPoint(
  tabs: HTMLDivElement | null,
  targets: ProjectTarget[],
  x: number,
  y: number,
) {
  const strip = tabs?.getBoundingClientRect();
  if (
    !strip ||
    x < strip.left ||
    x > strip.right ||
    y < strip.top ||
    y > strip.bottom
  )
    return null;
  return (
    targets.find(({ button }) => {
      const rect = button.getBoundingClientRect();
      return (
        button.isConnected &&
        rect.width > 0 &&
        rect.height > 0 &&
        x >= rect.left &&
        x <= rect.right &&
        y >= rect.top &&
        y <= rect.bottom
      );
    })?.name ?? null
  );
}

export interface ProjectDragSnapshot {
  projects?: ProjectTarget[];
  project?: string | null;
  mode?: DragStart['mode'];
  epics?: EpicTarget[];
  epicTarget?: EpicTarget | null;
  rootOrders?: RootOrderTarget[];
  rootOrderTarget?: RootOrderTarget | null;
}
export function useActionItemProjectDrag<T extends ProjectDragSnapshot>({
  enabled,
  drag,
  setSnapshot,
  projectTabsRef,
}: {
  enabled: boolean;
  drag: RefObject<T | null>;
  setSnapshot: Dispatch<SetStateAction<T | null>>;
  projectTabsRef: RefObject<HTMLDivElement | null>;
}) {
  useLayoutEffect(() => {
    if (!enabled) return;
    let lastPointer: { x: number; y: number } | null = null;
    function selectTarget(
      selection:
        | {
            project: string | null;
            epicTarget?: never;
            rootOrderTarget?: never;
          }
        | {
            epicTarget: EpicTarget | null;
            project?: never;
            rootOrderTarget?: never;
          }
        | {
            rootOrderTarget: RootOrderTarget;
            project?: never;
            epicTarget?: never;
          },
    ) {
      const current = drag.current;
      const next = {
        project: null,
        epicTarget: null,
        rootOrderTarget: null,
        ...selection,
      };
      if (
        !current ||
        ((current.project ?? null) === next.project &&
          (current.epicTarget ?? null) === next.epicTarget &&
          (current.rootOrderTarget ?? null) === next.rootOrderTarget)
      )
        return;
      drag.current = { ...current, ...next };
      setSnapshot(drag.current);
    }
    function pointer(x: number, y: number) {
      lastPointer = { x, y };
      const captured = drag.current;
      if (captured?.mode !== 'FLUID') return;
      const project = projectAtPoint(
        projectTabsRef.current,
        captured.projects ?? [],
        x,
        y,
      );
      if (project || !captured.epics) {
        selectTarget({ project });
        return;
      }
      const epic = captured.epics.find(({ element }) => atPoint(element, x, y));
      if (epic) {
        selectTarget({ epicTarget: epic });
        return;
      }
      const rootOrder = captured.rootOrders?.find(({ element }) =>
        atPoint(element, x, y),
      );
      if (rootOrder) {
        selectTarget({ rootOrderTarget: rootOrder });
        return;
      }
      selectTarget({ epicTarget: null });
    }
    const mouse = (event: MouseEvent) => pointer(event.clientX, event.clientY);
    const scroll = () => {
      if (lastPointer) pointer(lastPointer.x, lastPointer.y);
    };
    const touch = (event: TouchEvent) => {
      const point = event.changedTouches[0];
      if (point) pointer(point.clientX, point.clientY);
    };
    function keyboard(event: KeyboardEvent) {
      const captured = drag.current;
      if (captured?.mode !== 'SNAP') return;
      if (['ArrowUp', 'ArrowDown', 'Escape'].includes(event.key)) {
        selectTarget({ project: null });
        return;
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      if (event.shiftKey) {
        const targets = captured.epics ?? [];
        if (!targets.length) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        const previous = targets.indexOf(captured.epicTarget!);
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const next =
          previous === -1
            ? direction === 1
              ? 0
              : targets.length - 1
            : (previous + direction + targets.length) % targets.length;
        selectTarget({ epicTarget: targets[next] });
        targets[next].element.scrollIntoView?.({
          block: 'nearest',
          inline: 'nearest',
        });
        return;
      }
      const targets = captured.projects ?? [];
      if (!targets.length) return;
      const previous = targets.findIndex(
        ({ name }) => name === captured.project,
      );
      const next =
        previous === -1
          ? event.key === 'ArrowRight'
            ? 0
            : targets.length - 1
          : (previous +
              (event.key === 'ArrowRight' ? 1 : -1) +
              targets.length) %
            targets.length;
      selectTarget({ project: targets[next].name });
      targets[next].button.scrollIntoView?.({
        block: 'nearest',
        inline: 'nearest',
      });
    }
    // Register before the SDK installs its active gesture listeners.
    window.addEventListener('mousemove', mouse, {
      capture: true,
      passive: true,
    });
    window.addEventListener('mouseup', mouse, { capture: true, passive: true });
    window.addEventListener('touchmove', touch, {
      capture: true,
      passive: true,
    });
    window.addEventListener('touchend', touch, {
      capture: true,
      passive: true,
    });
    window.addEventListener('keydown', keyboard, true);
    window.addEventListener('scroll', scroll, true);
    return () => {
      window.removeEventListener('mousemove', mouse, true);
      window.removeEventListener('mouseup', mouse, true);
      window.removeEventListener('touchmove', touch, true);
      window.removeEventListener('touchend', touch, true);
      window.removeEventListener('keydown', keyboard, true);
      window.removeEventListener('scroll', scroll, true);
    };
  }, [enabled, drag, projectTabsRef, setSnapshot]);
}
