import type { ReactNode } from 'react';

interface PanelProps {
  code: string;
  title: string;
  extra?: ReactNode;
  className?: string;
  bodyClassName?: string;
  footer?: ReactNode;
  children: ReactNode;
}

/** Chamfered holographic frame shared by every HUD panel. */
export function Panel({ code, title, extra, className = '', bodyClassName = '', footer, children }: PanelProps) {
  return (
    <section className={`panel ${className}`} aria-label={title}>
      <header className="panel__head">
        <span className="panel__code">{code}</span>
        <h2 className="panel__title">{title}</h2>
        {extra && <div className="panel__extra">{extra}</div>}
      </header>
      <div className={`panel__body ${bodyClassName}`}>{children}</div>
      {footer}
    </section>
  );
}
