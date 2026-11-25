import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import './actionDisclosure.css';

export function ActionDisclosure({
  label,
  children,
  disabled = false,
  dismissible = true,
  resetKey,
  triggerContent,
  triggerRef,
}: {
  label: string;
  children: ReactNode | ((close: () => void) => ReactNode);
  disabled?: boolean;
  dismissible?: boolean;
  resetKey?: string | number;
  triggerContent?: ReactNode;
  triggerRef?: RefObject<HTMLButtonElement | null>;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const ownTrigger = useRef<HTMLButtonElement>(null);
  const trigger = triggerRef ?? ownTrigger;
  const previousKey = useRef(resetKey);
  const id = useId();
  const close = useCallback(
    (restoreFocus = true) => {
      if (!dismissible || !open) return;
      setOpen(false);
      const target = document.getElementById(`${id}-trigger`);
      if (
        restoreFocus &&
        target instanceof HTMLButtonElement &&
        !target.disabled &&
        (document.activeElement === document.body ||
          target.parentElement?.contains(document.activeElement))
      )
        target.focus({ preventScroll: true });
    },
    [dismissible, id, open],
  );
  const position = useCallback(() => {
    if (!panel.current || !trigger.current) return;
    const anchor = trigger.current.getBoundingClientRect();
    const bounds = panel.current.getBoundingClientRect();
    const margin = 8;
    const left = Math.max(
      margin,
      Math.min(
        anchor.right - bounds.width,
        window.innerWidth - bounds.width - margin,
      ),
    );
    const below = anchor.bottom + 6;
    const preferred =
      below + bounds.height <= window.innerHeight - margin
        ? below
        : anchor.top - bounds.height - 6;
    const top = Math.max(
      margin,
      Math.min(preferred, window.innerHeight - bounds.height - margin),
    );
    panel.current.style.left = `${left}px`;
    panel.current.style.top = `${top}px`;
  }, [trigger]);

  useLayoutEffect(() => {
    if (!dismissible) return;
    if (open && (previousKey.current !== resetKey || disabled)) close();
    previousKey.current = resetKey;
  }, [close, disabled, dismissible, open, resetKey]);

  useLayoutEffect(() => {
    if (!open) return;
    position();
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(position);
    if (panel.current) observer?.observe(panel.current);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
    };
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !container.current?.contains(event.target)
      )
        close();
    }
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [close, open]);

  return (
    <div
      ref={container}
      className="action-disclosure"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === 'Escape' && open && dismissible) {
          event.preventDefault();
          close();
        }
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) close(false);
      }}
    >
      <button
        ref={trigger}
        id={`${id}-trigger`}
        type="button"
        className={`btn btn-sm action-disclosure-trigger${triggerContent === undefined ? ' action-disclosure-icon' : ''}`}
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        title={label}
        disabled={disabled}
        onClick={() => {
          if (open) close();
          else setOpen(true);
        }}
      >
        {triggerContent ?? <span aria-hidden="true">⋯</span>}
      </button>
      <div
        id={id}
        ref={panel}
        className="action-disclosure-panel"
        role="group"
        aria-label={label}
        hidden={!open}
      >
        {typeof children === 'function' ? children(() => close()) : children}
      </div>
    </div>
  );
}
