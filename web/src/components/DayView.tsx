import { useEffect } from 'react';
import { useBriefing, useSpeed, useTasks } from '../lib/day';
import type { ServerStatus } from '../lib/types';
import { Panel } from './Panel';
import { Workspace } from './Workspace';
import { FocusBody, QuotesBody, SpeedBody, TasksBody } from './cards/DayCards';

const EMPTY_TASKS = { tasks: [], notes: [], open: 0, overdue: 0, due_today: 0, done_today: 0 };

/**
 * Dia a dia: o que se usa todo dia sem precisar pedir por voz. Tarefas e notas (TAR-43), a sessão
 * de foco (FOC-47), as cotações (COT-44) e o teste da internet (RED-45).
 */
export function DayView({ server, local }: { server: ServerStatus | null; local: boolean }) {
  const enabled = server?.day ?? false;
  const tasks = useTasks((s) => s.data);
  const loadTasks = useTasks((s) => s.load);
  const speed = useSpeed();
  const loadSpeed = speed.load;
  const briefing = useBriefing(enabled);

  useEffect(() => {
    if (!enabled) return;
    void loadTasks();
    void loadSpeed();
  }, [enabled, loadTasks, loadSpeed]);

  return (
    <Workspace view="day">
      <div className="workspace__col">
        <Panel code="TAR-43" title="Tarefas">
          {!server ? (
            <div className="notice">
              <strong>Servidor offline.</strong> As tarefas ficam no PC: rode <code>python jarvis.py</code>.
            </div>
          ) : !enabled ? (
            <div className="notice">
              <strong>Dia a dia desligado.</strong> Tire o <code>JARVIS_ENABLE_DAY=false</code> do <code>.env</code> para ligar.
            </div>
          ) : (
            <TasksBody data={tasks ?? EMPTY_TASKS} />
          )}
        </Panel>
      </div>
      <div className="workspace__col">
        <Panel code="FOC-47" title="Foco">
          <FocusBody />
        </Panel>
        <Panel code="COT-44" title="Cotações" extra={briefing?.quotes[0]?.at ? <span>{briefing.quotes[0].at.slice(11, 16)}</span> : undefined}>
          {briefing && briefing.quotes.length > 0 ? (
            <QuotesBody data={{ items: briefing.quotes, conversion: null }} />
          ) : (
            <p className="day__empty" role="status">{enabled ? 'Buscando as cotações… Se não aparecerem, o serviço não respondeu.' : 'Desligado no .env.'}</p>
          )}
          <p className="osint__note">Por voz: “quanto está o dólar?”, “quanto dá 150 dólares em reais?”, “10 milhas em quilômetros”.</p>
        </Panel>
      </div>
      <div className="workspace__col">
        <Panel
          code="RED-45"
          title="Rede"
          extra={
            local ? (
              <button type="button" className="chip-btn" disabled={!enabled || speed.running} onClick={() => void speed.test()}>
                {speed.running ? 'Medindo…' : 'Medir agora'}
              </button>
            ) : undefined
          }
        >
          {speed.running && <p className="day__empty" role="status">Medindo latência, download e upload. Leva uns 15 segundos.</p>}
          {!speed.running && <SpeedBody data={speed.data ?? { last: null, verdict: null, history: [] }} />}
          {speed.error && (
            <div className="notice" role="alert">
              {speed.error}
            </div>
          )}
        </Panel>
      </div>
    </Workspace>
  );
}
