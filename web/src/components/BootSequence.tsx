import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

const STEPS = [
  'Inicializando núcleo neural',
  'Calibrando matriz holográfica',
  'Carregando protocolos de voz',
  'Sincronizando sensores ambientais',
  'Verificando integridade dos sistemas',
];

const STEP_MS = 380;

export function BootSequence({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (step >= STEPS.length) {
      const timeout = window.setTimeout(() => setVisible(false), 450);
      return () => window.clearTimeout(timeout);
    }
    const timeout = window.setTimeout(() => setStep((value) => value + 1), STEP_MS);
    return () => window.clearTimeout(timeout);
  }, [step]);

  const progress = Math.min(1, step / STEPS.length);

  return (
    <AnimatePresence onExitComplete={onDone}>
      {visible && (
        <motion.div
          className="boot"
          role="status"
          aria-live="polite"
          onClick={() => setVisible(false)}
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, filter: 'blur(6px)' }}
          transition={{ duration: 0.6 }}
        >
          <div className="boot__inner">
            <motion.h1
              className="boot__title"
              initial={{ opacity: 0, letterSpacing: '0.9em' }}
              animate={{ opacity: 1, letterSpacing: '0.38em' }}
              transition={{ duration: 1.1, ease: 'easeOut' }}
            >
              J.A.R.V.I.S.
            </motion.h1>
            <div className="boot__subtitle">Just A Rather Very Intelligent System · v2.0</div>
            <ul className="boot__lines">
              {STEPS.slice(0, step).map((text) => (
                <motion.li key={text} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}>
                  &gt; {text}… <span>OK</span>
                </motion.li>
              ))}
            </ul>
            <div className="boot__bar">
              <i style={{ width: `${progress * 100}%` }} />
            </div>
            <div className="boot__skip">Clique para pular</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
