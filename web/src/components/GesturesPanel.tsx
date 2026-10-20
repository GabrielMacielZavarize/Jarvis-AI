import { type FormEvent, useCallback, useEffect, useState } from 'react';
import { useClock } from '../hooks/useClock';
import {
  agoLabel,
  type BindingKind,
  editorValue,
  type GestureAction,
  gestureCommand,
  GESTURE_GLYPHS,
  KEY_PLACEHOLDERS,
  KIND_LABELS,
  liveFromReply,
  loadGestures,
  plainName,
  resetGesture,
  saveGesture,
  STATE_LABELS,
} from '../lib/gestures';
import { useHud } from '../lib/hudStore';
import type { CustomGesture, GestureCatalog } from '../lib/types';
import { Panel } from './Panel';

const EDITOR_KEY = 'jarvis.gestures.editor';

function loadEditorOpen(): boolean {
  try {
    return window.localStorage.getItem(EDITOR_KEY) === 'open';
  } catch {
    return false;
  }
}

interface Notice {
  text: string;
  ok: boolean;
}

/**
 * GST-18: the hand gestures at a glance and their settings. Live state and the last command come
 * from the engine; the buttons ask the agent (it owns the webcam); "Editar" changes what each free
 * gesture does, with the same refusals as the voice (closing, deleting and typing never go on a gesture).
 */
export function GesturesPanel({ connected }: { connected: boolean }) {
  const live = useHud((s) => s.gestures);
  const [catalog, setCatalog] = useState<GestureCatalog | null>(null);
  const [editorOpen, setEditorOpen] = useState(loadEditorOpen);
  const [busy, setBusy] = useState<GestureAction | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const now = useClock(live.last ? 1000 : 60_000);

  const refresh = useCallback(() => {
    loadGestures()
      .then(setCatalog)
      .catch((error: Error) => setNotice({ text: error.message, ok: false }));
  }, []);
  useEffect(refresh, [refresh]);

  // The engine only reports changes: ask for the current state when the link opens.
  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    gestureCommand('status')
      .then((reply) => {
        if (!cancelled) useHud.getState().setGestures(liveFromReply(useHud.getState().gestures, reply));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [connected]);

  const run = async (action: GestureAction) => {
    setBusy(action);
    setNotice(null);
    try {
      const reply = await gestureCommand(action);
      useHud.getState().setGestures(liveFromReply(useHud.getState().gestures, reply));
      setNotice({ text: reply.message, ok: reply.ok && !reply.error });
    } catch (error) {
      setNotice({ text: error instanceof Error ? error.message : String(error), ok: false });
    } finally {
      setBusy(null);
    }
  };

  const toggleEditor = () => {
    const next = !editorOpen;
    setEditorOpen(next);
    if (next) refresh();
    try {
      window.localStorage.setItem(EDITOR_KEY, next ? 'open' : 'closed');
    } catch {
      // Private windows may refuse storage; the editor still toggles.
    }
  };

  const running = live.state !== 'off' && live.state !== 'unknown';
  const disabled = !connected || busy !== null;
  const offline = catalog !== null && !catalog.enabled;
  const custom = catalog?.gestures.filter((gesture) => gesture.custom).length ?? 0;

  return (
    <Panel
      code="GST-18"
      title="Gestos"
      className="gestures"
      extra={
        <button
          type="button"
          className={`chip-btn ${editorOpen ? 'chip-btn--on' : ''}`}
          onClick={toggleEditor}
          aria-expanded={editorOpen}
          title="O que cada gesto livre faz"
        >
          {editorOpen ? 'Fechar' : 'Editar'}
        </button>
      }
    >
      <div className="gestures__status">
        <span className={`gestures__state gestures__state--${live.state}`}>
          <i className="led" /> {STATE_LABELS[live.state]}
          {live.panel && <small> · painel aberto</small>}
        </span>
        {live.holding && (
          <span className="gestures__holding" title={live.holding}>
            ✊ {live.holding}
            {live.aim && <b> → {live.aim}</b>}
          </span>
        )}
        {live.last && (
          <span className={`gestures__last ${live.last.ok ? '' : 'gestures__last--error'}`} title={live.last.text}>
            {live.last.ok ? '✓' : '✕'} {live.last.text}
            <small> · {agoLabel(live.last.at, now)}</small>
          </span>
        )}
      </div>

      <div className="gestures__controls" title={connected ? undefined : 'Abra o link: os gestos rodam junto com o Jarvis'}>
        <button type="button" className="chip-btn" disabled={disabled} onClick={() => void run(running ? 'off' : 'on')}>
          {busy === 'on' ? 'Abrindo a câmera…' : running ? 'Desligar' : 'Ligar'}
        </button>
        {live.state === 'idle' && (
          <button type="button" className="chip-btn" disabled={disabled} onClick={() => void run('arm')}>
            Armar
          </button>
        )}
        <button
          type="button"
          className={`chip-btn ${live.state === 'mouse' ? 'chip-btn--on' : ''}`}
          disabled={disabled}
          onClick={() => void run(live.state === 'mouse' ? 'mouse_off' : 'mouse_on')}
        >
          Mouse no ar
        </button>
        <button
          type="button"
          className={`chip-btn ${live.panel ? 'chip-btn--on' : ''}`}
          disabled={disabled}
          onClick={() => void run(live.panel ? 'panel_off' : 'panel_on')}
          title="Câmera e mapa das telas no canto do monitor"
        >
          Painel da câmera
        </button>
      </div>

      {offline && (
        <p className="gestures__hint">
          Os gestos estão desligados no servidor: ligue <code>JARVIS_ENABLE_GESTURES=true</code> no .env.
        </p>
      )}
      {notice && <p className={`gestures__notice ${notice.ok ? '' : 'gestures__notice--error'}`}>{notice.text}</p>}

      {editorOpen && catalog && (
        <GestureEditor
          catalog={catalog}
          onChange={(next) => {
            setCatalog(next);
            if (next.message) setNotice({ text: next.message, ok: true });
          }}
          onError={(text) => setNotice({ text, ok: false })}
        />
      )}
      {!editorOpen && catalog && (
        <p className="gestures__hint">
          {catalog.gestures.length} gestos livres{custom ? `, ${custom} personalizados` : ''} ·{' '}
          {catalog.calibrated ? 'calibrados para a sua mão' : 'calibração padrão'}
        </p>
      )}
    </Panel>
  );
}

function GestureEditor({
  catalog,
  onChange,
  onError,
}: {
  catalog: GestureCatalog;
  onChange: (catalog: GestureCatalog) => void;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [showFixed, setShowFixed] = useState(false);
  const anyCustom = catalog.gestures.some((gesture) => gesture.custom);

  const reset = (id: string | null) =>
    resetGesture(id)
      .then(onChange)
      .catch((error: Error) => onError(error.message));

  return (
    <div className="gestures__editor">
      <ul className="gestures__list">
        {catalog.gestures.map((gesture) => (
          <li key={gesture.id} className={`gesture-row ${gesture.custom ? 'gesture-row--custom' : ''}`}>
            <div className="gesture-row__head">
              <span className="gesture-row__glyph" aria-hidden>
                {GESTURE_GLYPHS[gesture.id] ?? '✋'}
              </span>
              <span className="gesture-row__name" title={gesture.how}>
                {plainName(gesture)}
              </span>
              <span className="gesture-row__label" title={gesture.custom ? `Padrão: ${gesture.default}` : 'Padrão'}>
                {gesture.label}
              </span>
              <button
                type="button"
                className="chip-btn"
                onClick={() => setEditing(editing === gesture.id ? null : gesture.id)}
                aria-expanded={editing === gesture.id}
              >
                {editing === gesture.id ? 'Cancelar' : 'Trocar'}
              </button>
            </div>
            {gesture.same_as.length > 0 && (
              <div className="gesture-row__warn">Faz o mesmo que {gesture.same_as.join(' e ')}.</div>
            )}
            {editing === gesture.id && (
              <BindingForm
                gesture={gesture}
                catalog={catalog}
                onSaved={(next) => {
                  setEditing(null);
                  onChange(next);
                }}
                onReset={() => {
                  setEditing(null);
                  void reset(gesture.id);
                }}
                onError={onError}
              />
            )}
          </li>
        ))}
      </ul>
      <div className="gestures__foot">
        <button type="button" className="chip-btn" onClick={() => setShowFixed(!showFixed)} aria-expanded={showFixed}>
          {showFixed ? 'Esconder' : 'Ver'} os {catalog.fixed.length} gestos fixos
        </button>
        <button type="button" className="chip-btn" disabled={!anyCustom} onClick={() => void reset(null)}>
          Restaurar todos
        </button>
      </div>
      {showFixed && (
        <dl className="gestures__fixed">
          {catalog.fixed.map((item) => (
            <div key={item.name}>
              <dt>{item.name}</dt>
              <dd>{item.what}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function BindingForm({
  gesture,
  catalog,
  onSaved,
  onReset,
  onError,
}: {
  gesture: CustomGesture;
  catalog: GestureCatalog;
  onSaved: (catalog: GestureCatalog) => void;
  onReset: () => void;
  onError: (message: string) => void;
}) {
  const start = editorValue(gesture.binding);
  const [kind, setKind] = useState<BindingKind>(start.kind);
  const [value, setValue] = useState(start.value);
  const [saving, setSaving] = useState(false);

  const changeKind = (next: BindingKind) => {
    setKind(next);
    // A value of another kind makes no sense (an action id is not an app name).
    setValue(next === start.kind ? start.value : next === 'action' ? (catalog.actions[0]?.id ?? '') : next === 'layout' ? (catalog.layouts[0] ?? '') : '');
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      onSaved(await saveGesture(gesture.id, kind, value));
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="binding-form" onSubmit={(event) => void submit(event)}>
      <p className="binding-form__how">{gesture.how}</p>
      <div className="binding-form__row">
        <select className="select" value={kind} onChange={(event) => changeKind(event.target.value as BindingKind)} aria-label="Tipo de ação">
          {(Object.keys(KIND_LABELS) as BindingKind[]).map((option) => (
            <option key={option} value={option}>
              {KIND_LABELS[option]}
            </option>
          ))}
        </select>
        {kind === 'action' && (
          <select className="select" value={value} onChange={(event) => setValue(event.target.value)} aria-label="Ação">
            {catalog.actions.map((action) => (
              <option key={action.id} value={action.id}>
                {action.label}
              </option>
            ))}
          </select>
        )}
        {kind === 'layout' &&
          (catalog.layouts.length > 0 ? (
            <select className="select" value={value} onChange={(event) => setValue(event.target.value)} aria-label="Layout">
              {catalog.layouts.map((layout) => (
                <option key={layout} value={layout}>
                  {layout}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="binding-form__input"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="trabalho (salve um: “salva esse layout como modo trabalho”)"
              aria-label="Layout"
            />
          ))}
        {(kind === 'app' || kind === 'site' || kind === 'keys') && (
          <input
            className="binding-form__input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={KEY_PLACEHOLDERS[kind]}
            aria-label={KIND_LABELS[kind]}
            maxLength={120}
          />
        )}
      </div>
      <div className="binding-form__row binding-form__row--actions">
        <button type="submit" className="chip-btn chip-btn--on" disabled={saving || (kind !== 'none' && !value.trim())}>
          {saving ? 'Salvando…' : 'Salvar'}
        </button>
        <button type="button" className="chip-btn" disabled={!gesture.custom} onClick={onReset} title={`Padrão: ${gesture.default}`}>
          Voltar ao padrão
        </button>
      </div>
    </form>
  );
}
