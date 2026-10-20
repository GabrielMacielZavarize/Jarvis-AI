import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';
import { usePrefs } from '../lib/prefs';
import { themeInfo } from '../lib/themes';

/** Decorative memory addresses printed before each step. */
const ADDRESSES = ['0x7F3A', '0x1C04', '0xA9E2', '0x5B71', '0xD03F'];

/** Each protocol boots with its own lines and pace (lib/themes.ts). */
export function BootSequence({ onDone }: { onDone: () => void }) {
  const { theme } = usePrefs();
  const protocol = themeInfo(theme);
  const { steps, stepMs } = protocol.boot;
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (step >= steps.length) {
      const timeout = window.setTimeout(() => setVisible(false), 450);
      return () => window.clearTimeout(timeout);
    }
    const timeout = window.setTimeout(() => setStep((value) => value + 1), stepMs);
    return () => window.clearTimeout(timeout);
  }, [step, steps.length, stepMs]);

  const progress = Math.min(1, step / steps.length);
  const online = step >= steps.length;

  return (
    <AnimatePresence onExitComplete={onDone}>
      {visible && (
        <motion.div
          className={`boot ${online ? 'boot--online' : ''}`}
          role="status"
          aria-live="polite"
          onClick={() => setVisible(false)}
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: 1.04, filter: 'blur(8px)' }}
          transition={{ duration: 0.6 }}
        >
          <div className="boot__grid" aria-hidden />
          <div className="boot__inner">
            <svg className="boot__reactor" viewBox="0 0 120 120" aria-hidden>
              <circle className="boot__ring boot__ring--outer" cx="60" cy="60" r="56" />
              <circle className="boot__ring boot__ring--dash" cx="60" cy="60" r="48" />
              <circle
                className="boot__ring boot__ring--progress"
                cx="60"
                cy="60"
                r="40"
                pathLength={100}
                style={{ strokeDashoffset: 100 - progress * 100 }}
              />
              <path className="boot__tri" d="M60 37 79.9 71.5H40.1Z" />
              <circle className="boot__core" cx="60" cy="60" r="6.5" />
            </svg>
            <motion.h1
              className="boot__title"
              data-text={protocol.brand}
              initial={{ opacity: 0, letterSpacing: '0.9em' }}
              animate={{ opacity: 1, letterSpacing: '0.38em' }}
              transition={{ duration: 1.1, ease: 'easeOut' }}
            >
              {protocol.brand}
            </motion.h1>
            <div className="boot__subtitle">{protocol.tagline} · v2.0</div>
            <ul className="boot__lines">
              {steps.slice(0, step).map((text, index) => (
                <motion.li key={text} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}>
                  <span className="boot__addr">{ADDRESSES[index]}</span>
                  {text}…<span className="boot__ok">OK</span>
                </motion.li>
              ))}
            </ul>
            <div className="boot__meter">
              <div className="boot__bar">
                <i style={{ width: `${progress * 100}%` }} />
              </div>
              <span className="boot__pct">{String(Math.round(progress * 100)).padStart(3, '0')}%</span>
            </div>
            <div className="boot__skip">{online ? protocol.boot.online : 'Clique para pular'}</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
