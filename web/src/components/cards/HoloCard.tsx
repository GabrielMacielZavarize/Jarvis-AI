import { motion } from 'motion/react';
import { forwardRef, type ReactNode } from 'react';

interface HoloCardProps {
  code: string;
  title: string;
  subtitle?: ReactNode;
  expanded?: boolean;
  onToggleExpand?: () => void;
  onClose: () => void;
  children: ReactNode;
}

/** Animated holographic projection used by every result card. */
export const HoloCard = forwardRef<HTMLElement, HoloCardProps>(function HoloCard(
  { code, title, subtitle, expanded = false, onToggleExpand, onClose, children },
  ref,
) {
  return (
    <motion.section
      ref={ref}
      layout
      className={`panel card ${expanded ? 'card--expanded' : ''}`}
      aria-label={title}
      initial={{ opacity: 0, x: expanded ? 0 : -36, rotateY: expanded ? 0 : 28, scale: 0.94, filter: 'blur(6px) brightness(2)' }}
      animate={{ opacity: 1, x: 0, rotateY: 0, scale: 1, filter: 'blur(0px) brightness(1)' }}
      exit={{ opacity: 0, x: expanded ? 0 : -28, scale: 0.96, filter: 'blur(4px)' }}
      transition={{ type: 'spring', stiffness: 170, damping: 22 }}
    >
      <header className="panel__head">
        <span className="panel__code">{code}</span>
        <h2 className="panel__title">{title}</h2>
        <div className="panel__extra">
          {subtitle}
          {onToggleExpand && (
            <button
              type="button"
              className="icon-btn"
              onClick={onToggleExpand}
              aria-label={expanded ? `Reduzir ${title}` : `Ampliar ${title}`}
            >
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
                {expanded ? <path d="M5 1v4H1M7 11V7h4" /> : <path d="M1 5V1h4M11 7v4H7" />}
              </svg>
            </button>
          )}
          <button type="button" className="icon-btn" onClick={onClose} aria-label={`Fechar ${title}`}>
            <svg width="10" height="10" viewBox="0 0 10 10" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <path d="M1 1l8 8M9 1L1 9" />
            </svg>
          </button>
        </div>
      </header>
      <div className="panel__body">{children}</div>
      <div className="card__scan" />
    </motion.section>
  );
});
