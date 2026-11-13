import { AnimatePresence } from 'motion/react';
import * as m from 'motion/react-m';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { openEyeWith } from '../lib/eyeLink';
import { useHud } from '../lib/hudStore';
import { buildCommands, freeTextCommand, osintCommand, type PaletteCommand, type PaletteContext, searchCommands } from '../lib/palette';

/** Quantos comandos a lista mostra de cada vez (a busca estreita o resto). */
const MAX_SHOWN = 60;

interface CommandPaletteProps {
  /** Tudo o que os comandos precisam para rodar; montado pelo HUD a cada abertura. */
  context: Omit<PaletteContext, 'view' | 'cinema' | 'hasCards' | 'setView' | 'setCinema' | 'clearCards'>;
  /** ODD-42 ligado no servidor: um IP, domínio ou link digitado vira uma consulta. */
  osint: boolean;
}

/** Ctrl+K: busca em tudo o que o HUD faz e manda texto ao Jarvis sem tirar a mão do teclado. */
export function CommandPalette({ context, osint }: CommandPaletteProps) {
  const open = useHud((s) => s.palette);
  const setPalette = useHud((s) => s.setPalette);
  const view = useHud((s) => s.view);
  const cinema = useHud((s) => s.cinema);
  const hasCards = useHud((s) => s.cards.length > 0);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const full: PaletteContext = useMemo(
    () => ({
      ...context,
      view,
      cinema,
      hasCards,
      setView: useHud.getState().setView,
      setCinema: useHud.getState().setCinema,
      clearCards: useHud.getState().clearCards,
    }),
    [context, view, cinema, hasCards],
  );

  const results = useMemo(() => {
    if (!open) return [];
    const found = searchCommands(buildCommands(full), query);
    const free = freeTextCommand(full, query);
    // Com o link aberto, o texto digitado vai primeiro: é o que a pessoa quer na maioria das vezes
    // que nada casa de cara. Sem link ele fica no fim, só explicando por que não vai.
    const ordered = free ? (free.disabled ? [...found, free] : found.length > 0 && !found[0].disabled ? [...found, free] : [free, ...found]) : found;
    // Um IP, domínio ou link digitado é quase sempre para consultar: vai em primeiro.
    const lookup = osintCommand(query, osint, openEyeWith);
    return (lookup ? [lookup, ...ordered] : ordered).slice(0, MAX_SHOWN);
  }, [open, full, query, osint]);

  // O foco vai para o campo antes da próxima tecla: quem aperta Ctrl+K e já sai digitando não perde letra.
  useLayoutEffect(() => {
    if (!open) return;
    setQuery('');
    setCursor(0);
    input.current?.focus();
  }, [open]);

  // Se o foco escapar (um clique fora do campo), a próxima tecla o traz de volta.
  useEffect(() => {
    if (!open) return;
    const refocus = (event: KeyboardEvent) => {
      if (event.target !== input.current && !event.ctrlKey && !event.metaKey && !event.altKey) input.current?.focus();
    };
    window.addEventListener('keydown', refocus, true);
    return () => window.removeEventListener('keydown', refocus, true);
  }, [open]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  const run = (command: PaletteCommand | undefined) => {
    if (!command || command.disabled) return;
    setPalette(false);
    command.run();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setCursor((value) => Math.min(value + 1, Math.max(0, results.length - 1)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor((value) => Math.max(value - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      run(results[cursor]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setPalette(false);
    }
  };

  let lastGroup = '';
  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div
          className="palette"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.14 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPalette(false);
          }}
        >
          <m.div
            className="palette__box"
            role="dialog"
            aria-modal="true"
            aria-label="Paleta de comandos"
            initial={{ y: -14, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: -8 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
            onKeyDown={onKeyDown}
          >
            <div className="palette__search">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden>
                <circle cx="11" cy="11" r="6.5" />
                <path d="M16 16l5 5" />
              </svg>
              <input
                ref={input}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar um comando ou escrever ao Jarvis…"
                aria-label="Buscar um comando"
                role="combobox"
                aria-expanded="true"
                aria-controls="palette-list"
                aria-activedescendant={results[cursor] ? `palette-${results[cursor].id}` : undefined}
                maxLength={500}
                autoComplete="off"
                spellCheck={false}
              />
              <kbd>Esc</kbd>
            </div>
            <ul className="palette__list" id="palette-list" role="listbox" ref={list}>
              {results.length === 0 && <li className="palette__empty">Nada encontrado. Tente “persona”, “ajustes” ou o nome de um protocolo.</li>}
              {results.map((command, index) => {
                const header = command.group !== lastGroup ? command.group : null;
                lastGroup = command.group;
                return (
                  <li key={command.id} role="presentation">
                    {header && <div className="palette__group">{header}</div>}
                    <button
                      type="button"
                      id={`palette-${command.id}`}
                      role="option"
                      aria-selected={index === cursor}
                      aria-disabled={Boolean(command.disabled)}
                      data-active={index === cursor}
                      className={`palette__item ${command.disabled ? 'palette__item--off' : ''}`}
                      onMouseMove={() => setCursor(index)}
                      onClick={() => run(command)}
                    >
                      <span className="palette__label">{command.label}</span>
                      {(command.disabled ?? command.hint) && <span className="palette__hint">{command.disabled ?? command.hint}</span>}
                      {command.shortcut && !command.disabled && <kbd>{command.shortcut}</kbd>}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="palette__foot">
              <span>
                <kbd>↑</kbd>
                <kbd>↓</kbd> navegar
              </span>
              <span>
                <kbd>Enter</kbd> executar
              </span>
              <span>
                <kbd>Ctrl</kbd>
                <kbd>K</kbd> abrir de qualquer lugar
              </span>
            </div>
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
