import {
  useLayoutEffect,
  type RefObject,
  type Dispatch,
  type SetStateAction,
} from 'react';
import type { DragStart } from '@hello-pangea/dnd';

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
    function selectProject(project: string | null) {
      if (!drag.current || drag.current.project === project) return;
      drag.current = { ...drag.current, project };
      setSnapshot(drag.current);
    }
    function pointer(x: number, y: number) {
      const captured = drag.current;
      if (captured?.mode !== 'FLUID') return;
      selectProject(
        projectAtPoint(projectTabsRef.current, captured.projects ?? [], x, y),
      );
    }
    const mouse = (event: MouseEvent) => pointer(event.clientX, event.clientY);
    const touch = (event: TouchEvent) => {
      const point = event.changedTouches[0];
      if (point) pointer(point.clientX, point.clientY);
    };
    function keyboard(event: KeyboardEvent) {
      const captured = drag.current;
      if (captured?.mode !== 'SNAP') return;
      if (['ArrowUp', 'ArrowDown', 'Escape'].includes(event.key)) {
        selectProject(null);
        return;
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
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
      selectProject(targets[next].name);
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
    return () => {
      window.removeEventListener('mousemove', mouse, true);
      window.removeEventListener('mouseup', mouse, true);
      window.removeEventListener('touchmove', touch, true);
      window.removeEventListener('touchend', touch, true);
      window.removeEventListener('keydown', keyboard, true);
    };
  }, [enabled, drag, projectTabsRef, setSnapshot]);
}
