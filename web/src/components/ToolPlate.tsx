import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useRef, useState } from 'react';
import { TOOL_LABELS, toolCode } from '../lib/catalog';
import { lastToolResult } from '../lib/coreActivity';
import { useHud } from '../lib/hudStore';

/** How long a finished protocol stays on screen with its result. */
const RESULT_MS = 1800;

interface PlateTool {
  name: string;
  detail: string | null;
}

interface FinishedTool extends PlateTool {
  ok: boolean;
}

/** Lower third over the core: the protocol running right now and, for a moment, how it ended. */
export function ToolPlate() {
  const activeTool = useHud((s) => s.activeTool);
  const detail = useHud((s) => s.activeToolDetail);
  const running = useRef<PlateTool | null>(null);
  const [finished, setFinished] = useState<FinishedTool | null>(null);

  useEffect(() => {
    if (activeTool) {
      running.current = { name: activeTool, detail };
      setFinished(null);
      return;
    }
    const last = running.current;
    running.current = null;
    if (!last) return;
    // The simulation marks the result right after clearing the tool, so it is read after the commit.
    const endedAt = Date.now();
    const result = lastToolResult();
    setFinished({ ...last, ok: !result || result.at < endedAt - 1000 || result.ok });
    const timer = window.setTimeout(() => setFinished(null), RESULT_MS);
    return () => window.clearTimeout(timer);
  }, [activeTool, detail]);

  const shown: PlateTool | null = activeTool ? { name: activeTool, detail } : finished;
  const state = activeTool ? 'running' : finished?.ok === false ? 'error' : 'done';

  return (
    <AnimatePresence>
      {shown && (
        <motion.div
          key="plate"
          className={`tool-plate tool-plate--${state}`}
          role="status"
          aria-live="polite"
          initial={{ opacity: 0, y: 10, filter: 'blur(4px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, y: -8, filter: 'blur(4px)' }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        >
          <span className="tool-plate__code">{toolCode(shown.name)}</span>
          <span className="tool-plate__label">{TOOL_LABELS[shown.name] ?? shown.name}</span>
          <span className="tool-plate__state">
            {state === 'running' ? 'Executando' : state === 'done' ? '✓ Concluído' : '✕ Falhou'}
          </span>
          {shown.detail && <span className="tool-plate__detail">{shown.detail}</span>}
          <i className="tool-plate__bar" aria-hidden />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
