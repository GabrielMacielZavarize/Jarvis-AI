import { AnimatePresence, motion } from 'motion/react';
import { useEffect } from 'react';
import { useHud } from '../lib/hudStore';
import type { Toast } from '../lib/types';

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useHud((s) => s.dismissToast);

  useEffect(() => {
    if (!toast.ttl) return;
    const timer = window.setTimeout(() => dismiss(toast.id), Math.max(0, toast.createdAt + toast.ttl - Date.now()));
    return () => window.clearTimeout(timer);
  }, [toast, dismiss]);

  return (
    <motion.li
      layout
      className={`toast toast--${toast.level}`}
      role={toast.level === 'critical' ? 'alert' : 'status'}
      initial={{ opacity: 0, x: 60, filter: 'blur(4px) brightness(2)' }}
      animate={{ opacity: 1, x: 0, filter: 'blur(0px) brightness(1)' }}
      exit={{ opacity: 0, x: 40, filter: 'blur(3px)' }}
      transition={{ type: 'spring', stiffness: 220, damping: 24 }}
    >
      <button type="button" className="toast__body" onClick={() => dismiss(toast.id)} title="Dispensar">
        <span className="toast__head">
          {toast.code && <span className="toast__code">{toast.code}</span>}
          <strong>{toast.title}</strong>
        </span>
        {toast.message && <span className="toast__message">{toast.message}</span>}
      </button>
      {toast.ttl > 0 && <i className="toast__timer" style={{ animationDuration: `${toast.ttl}ms` }} aria-hidden />}
    </motion.li>
  );
}

/** Holographic notifications on the right edge: notices, finished timers, model switches. */
export function Toasts() {
  const toasts = useHud((s) => s.toasts);
  return (
    <ol className="toasts" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} />
        ))}
      </AnimatePresence>
    </ol>
  );
}
