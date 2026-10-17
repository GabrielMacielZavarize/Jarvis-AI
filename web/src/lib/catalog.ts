import type { JarvisMode } from './types';

export interface ProtocolInfo {
  id: string;
  code: string;
  label: string;
  hint: string;
}

/** Tools exposed by the Python agent, in the same order as tools.build_tools(). */
export const PROTOCOLS: ProtocolInfo[] = [
  { id: 'get_weather', code: 'WX-01', label: 'Clima & previsão', hint: '“Como está o tempo em Lisboa?”' },
  { id: 'search_web', code: 'NET-02', label: 'Pesquisa web', hint: '“Pesquise sobre fusão nuclear.”' },
  { id: 'search_news', code: 'NWS-03', label: 'Notícias', hint: '“Últimas notícias de tecnologia.”' },
  { id: 'get_current_time', code: 'CHR-04', label: 'Relógio mundial', hint: '“Que horas são em Tóquio?”' },
  { id: 'run_diagnostics', code: 'SYS-05', label: 'Diagnóstico', hint: '“Rode um diagnóstico do sistema.”' },
  { id: 'set_timer', code: 'TMR-06', label: 'Timers', hint: '“Timer de 10 minutos pro café.”' },
  { id: 'show_on_hud', code: 'HUD-07', label: 'Painéis no HUD', hint: '“Mostre os passos no painel.”' },
  { id: 'draft_email', code: 'COM-08', label: 'Email seguro', hint: '“Escreva um email para…”' },
];

export const TOOL_LABELS: Record<string, string> = {
  get_weather: 'Varredura meteorológica',
  search_web: 'Pesquisa na rede',
  search_news: 'Feed de notícias',
  get_current_time: 'Sincronização temporal',
  run_diagnostics: 'Diagnóstico do sistema',
  set_timer: 'Cronômetro',
  show_on_hud: 'Projeção no HUD',
  draft_email: 'Rascunho de email',
  confirm_email_send: 'Transmissão de email',
  cancel_pending_email: 'Cancelamento de email',
};

export const MODE_LABELS: Record<JarvisMode, string> = {
  offline: 'Offline',
  standby: 'Em espera',
  connecting: 'Estabelecendo link',
  listening: 'Ouvindo',
  thinking: 'Processando',
  speaking: 'Respondendo',
  error: 'Falha no link',
};

export const BACKEND_LABELS: Record<string, string> = {
  'gemini-realtime': 'Gemini Live',
  'openai-realtime': 'OpenAI Realtime',
  'openai-compatible-pipeline': 'Pipeline OpenAI',
};
