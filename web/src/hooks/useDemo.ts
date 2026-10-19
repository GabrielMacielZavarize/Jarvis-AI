import { useCallback, useEffect, useRef, useState } from 'react';
import { setSynthetic } from '../lib/audio';
import { TOOL_LABELS } from '../lib/catalog';
import { markToolResult } from '../lib/coreActivity';
import { DEMO_SCRIPT, speakingMs } from '../lib/demo';
import { useHud } from '../lib/hudStore';
import { playCue } from '../lib/sounds';
import type { ChatLine, JarvisMode } from '../lib/types';

const voice = { agentUntil: 0, userUntil: 0 };

function envelope(now: number, until: number, seed: number) {
  const left = until - now;
  if (left <= 0) return 0;
  const t = now / 1000;
  const fade = Math.min(1, left / 250);
  const syllables = Math.abs(Math.sin(t * (9 + seed))) * (0.55 + 0.45 * Math.sin(t * 2.3 + seed));
  return fade * (0.25 + 0.6 * syllables);
}

function syntheticLevels() {
  const now = performance.now();
  return { agent: envelope(now, voice.agentUntil, 0), user: envelope(now, voice.userUntil, 1.7) * 0.8 };
}

export interface DemoState {
  running: boolean;
  mode: JarvisMode;
  lines: ChatLine[];
  start: () => void;
  stop: () => void;
}

export function useDemo(): DemoState {
  const [running, setRunning] = useState(false);
  const [mode, setMode] = useState<JarvisMode>('standby');
  const [lines, setLines] = useState<ChatLine[]>([]);
  const abort = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setSynthetic(null);
    voice.agentUntil = voice.userUntil = 0;
    const hud = useHud.getState();
    hud.setActiveTool(null);
    hud.setDemo(false);
    hud.clearCards();
    hud.addLog('info', 'Simulação encerrada');
    setRunning(false);
    setMode('standby');
    setLines([]);
  }, []);

  const start = useCallback(() => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const { signal } = controller;
    const hud = useHud.getState();

    const wait = (ms: number) =>
      new Promise<void>((resolve, reject) => {
        const id = window.setTimeout(resolve, ms);
        signal.addEventListener('abort', () => {
          window.clearTimeout(id);
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    const addLine = (role: ChatLine['role'], text: string) =>
      setLines((prev) => [...prev, { id: `demo-${prev.length}`, role, text, ts: Date.now() }]);

    hud.clearCards();
    hud.setDemo(true);
    hud.addLog('warn', 'Modo simulação ativado — dados fictícios');
    setSynthetic(syntheticLevels);
    setLines([]);
    setRunning(true);

    const run = async () => {
      for (const beat of DEMO_SCRIPT) {
        switch (beat.kind) {
          case 'mode':
            setMode(beat.mode);
            if (beat.mode === 'connecting') hud.addLog('info', 'Estabelecendo link simulado…');
            await wait(beat.ms);
            break;
          case 'agent': {
            const ms = speakingMs(beat.text);
            setMode('speaking');
            addLine('agent', beat.text);
            voice.agentUntil = performance.now() + ms;
            await wait(ms);
            break;
          }
          case 'user': {
            const ms = speakingMs(beat.text) * 0.8;
            setMode('listening');
            hud.addVoiceStart(Date.now());
            voice.userUntil = performance.now() + ms;
            await wait(ms);
            addLine('user', beat.text);
            break;
          }
          case 'tool':
            setMode('thinking');
            hud.setActiveTool(beat.name, beat.detail);
            playCue('toolStart');
            hud.addLog('tool', `${TOOL_LABELS[beat.name] ?? beat.name}${beat.detail ? ` · ${beat.detail}` : ''}`);
            if (beat.hosts) hud.addLinks(beat.hosts, 'request');
            if (beat.sources) {
              await wait(beat.ms / 2);
              hud.addLinks(beat.sources, 'source');
              await wait(beat.ms / 2);
            } else {
              await wait(beat.ms);
            }
            break;
          case 'toast':
            hud.pushToast(beat.toast);
            playCue('notice');
            await wait(600);
            break;
          case 'card':
            hud.pushCard(beat.card.kind, beat.card.data() as never);
            hud.addLog('ok', `${TOOL_LABELS[useHud.getState().activeTool ?? ''] ?? 'Protocolo'} concluído`);
            hud.setActiveTool(null);
            markToolResult('done');
            playCue('toolDone');
            await wait(350);
            break;
        }
      }
    };

    run().catch((error: unknown) => {
      if ((error as DOMException)?.name !== 'AbortError') console.error(error);
    });
  }, []);

  useEffect(() => () => abort.current?.abort(), []);

  return { running, mode, lines, start, stop };
}
