import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from 'react';
import { type Column, getPrefs, movePanel, type PanelId, setPrefs } from '../lib/prefs';

/** Movement before a press on a header turns into a drag (a click stays a click). */
const THRESHOLD_PX = 6;
/** Below this width the columns stack and there is nothing to rearrange. */
const DESKTOP = '(min-width: 1081px)';

export interface DropTarget {
  column: Column;
  index: number;
  /** Where the drop line is drawn (viewport pixels). */
  top: number;
  left: number;
  width: number;
}

/** Position in `column` for a panel dropped at height `y`, and where to draw the line. */
function dropTarget(id: PanelId, x: number, y: number): DropTarget | null {
  const column: Column = x < window.innerWidth / 2 ? 'left' : 'right';
  const container = document.querySelector<HTMLElement>(`.hud__${column}`);
  if (!container) return null;
  // Slots are display: contents, so the panel inside each one is measured; empty slots are skipped.
  const slots = [...container.querySelectorAll<HTMLElement>(':scope > [data-slot]')].filter((slot) => slot.dataset.slot !== id);
  const rects = slots.map((slot) => {
    const rect = slot.firstElementChild?.getBoundingClientRect();
    return rect && rect.height > 0 ? rect : null;
  });
  let index = 0;
  rects.forEach((rect, position) => {
    if (rect && rect.top + rect.height / 2 < y) index = position + 1;
  });
  const below = rects.slice(index).find((rect) => rect !== null);
  const above = [...rects.slice(0, index)].reverse().find((rect) => rect !== null);
  const box = container.getBoundingClientRect();
  const top = below ? below.top - 7 : above ? above.bottom + 7 : box.top;
  return { column, index, top, left: box.left, width: box.width };
}

/** Drag a panel by its header to the other column or another place in its own; the layout is saved. */
export function usePanelDrag() {
  const [dragging, setDragging] = useState<PanelId | null>(null);
  const [target, setTarget] = useState<DropTarget | null>(null);
  const press = useRef<{ id: PanelId; x: number; y: number; active: boolean } | null>(null);
  const latest = useRef<DropTarget | null>(null);

  const onPointerDown = useCallback(
    (id: PanelId) => (event: ReactPointerEvent) => {
      if (event.button !== 0 || !window.matchMedia(DESKTOP).matches) return;
      const element = event.target as HTMLElement;
      if (!element.closest('.panel__head') || element.closest('button, input, select, a, label')) return;
      // No text selection starting under the header while it moves.
      event.preventDefault();
      press.current = { id, x: event.clientX, y: event.clientY, active: false };
    },
    [],
  );

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const current = press.current;
      if (!current) return;
      if (!current.active) {
        if (Math.hypot(event.clientX - current.x, event.clientY - current.y) < THRESHOLD_PX) return;
        current.active = true;
        setDragging(current.id);
      }
      latest.current = dropTarget(current.id, event.clientX, event.clientY);
      setTarget(latest.current);
    };
    const onUp = () => {
      const current = press.current;
      press.current = null;
      if (current?.active && latest.current) {
        const { column, index } = latest.current;
        setPrefs({ layout: movePanel(getPrefs().layout, current.id, column, index) });
      }
      latest.current = null;
      setDragging(null);
      setTarget(null);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, []);

  return { dragging, target, onPointerDown };
}
