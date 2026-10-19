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
  { id: 'set_timer', code: 'TMR-06', label: 'Timers', hint: '“Timer de 10 minutos pro café.” · “Quanto falta?”' },
  { id: 'show_on_hud', code: 'HUD-07', label: 'Painéis no HUD', hint: '“Mostre os passos no painel.” · “Feche essa aba.”' },
  { id: 'play_youtube', code: 'MED-08', label: 'YouTube & streaming', hint: '“Toque lo-fi no YouTube.”' },
  { id: 'open_app', code: 'PC-09', label: 'Apps do computador', hint: '“Abra o Spotify.” · “Feche o Discord.”' },
  { id: 'browser_tab', code: 'WEB-10', label: 'Sites & abas', hint: '“Feche a aba do YouTube.”' },
  { id: 'set_volume', code: 'AUD-11', label: 'Volume & mídia', hint: '“Volume em 30%.” · “Pausa.”' },
  { id: 'manage_window', code: 'JAN-13', label: 'Janelas & monitores', hint: '“Joga as Configurações na tela 3.”' },
  { id: 'look_at_screen', code: 'VIS-14', label: 'Leitura de tela', hint: '“O que tem no PhpStorm?”' },
  { id: 'draft_email', code: 'COM-12', label: 'Email seguro', hint: '“Escreva um email para…”' },
  { id: 'search_apps', code: 'APP-15', label: 'Instalar apps', hint: '“Instala o VLC pra mim.”' },
  { id: 'check_microphone', code: 'MIC-16', label: 'Microfone', hint: '“Qual microfone está conectado?”' },
  { id: 'end_session', code: 'PWR-17', label: 'Encerrar sessão', hint: '“Tchau, Jarvis.” · “Pode desligar.”' },
  { id: 'change_voice', code: 'VOZ-30', label: 'Voz do Jarvis', hint: '“Troca sua voz para Orus.” · “Quais vozes você tem?”' },
  { id: 'look_at_camera', code: 'CAM-19', label: 'Câmera', hint: '“O que você está vendo?” · “Mostra a câmera.”' },
  { id: 'click_on_screen', code: 'MOU-20', label: 'Mouse & teclado', hint: '“Clica no botão de play.” · “Rola a página.”' },
  { id: 'explain_screen', code: 'TEL-31', label: 'Assistente de tela', hint: '“Explica esse erro.” · “Copia a correção.”' },
  { id: 'start_dictation', code: 'DIT-29', label: 'Modo ditado', hint: '“Jarvis, modo ditado.” · “Escreve aqui: chego em 10 minutos.”' },
  { id: 'remember', code: 'MEM-23', label: 'Memória', hint: '“Lembra que eu prefiro lo-fi.” · “O que você sabe sobre mim?”' },
  { id: 'run_routine', code: 'ROT-24', label: 'Rotinas', hint: '“Bom dia, Jarvis.” · “Modo foco.” · “Todo dia útil às 8h roda o bom dia.”' },
  { id: 'get_agenda', code: 'AGD-27', label: 'Google Agenda', hint: '“O que eu tenho hoje?” · “Marca dentista sexta às 15h.”' },
];

export const TOOL_LABELS: Record<string, string> = {
  get_weather: 'Varredura meteorológica',
  search_web: 'Pesquisa na rede',
  search_news: 'Feed de notícias',
  get_current_time: 'Sincronização temporal',
  run_diagnostics: 'Diagnóstico do sistema',
  set_timer: 'Cronômetro',
  get_timers: 'Consulta de timers',
  check_microphone: 'Microfone',
  end_session: 'Encerrando sessão',
  change_voice: 'Módulo de voz',
  remember: 'Gravando memória',
  recall: 'Consulta de memória',
  forget: 'Apagando memória',
  list_routines: 'Rotinas salvas',
  run_routine: 'Executando rotina',
  confirm_routine_step: 'Passo confirmado',
  save_routine: 'Gravando rotina',
  delete_routine: 'Apagando rotina',
  schedule_routine: 'Agendando rotina',
  show_on_hud: 'Projeção no HUD',
  check_email_address: 'Conferência de endereço',
  draft_email: 'Rascunho de email',
  confirm_email_send: 'Transmissão de email',
  cancel_pending_email: 'Cancelamento de email',
  search_apps: 'Busca de aplicativos',
  prepare_app_install: 'Preparando instalação',
  confirm_app_install: 'Instalação de app',
  cancel_app_install: 'Cancelamento de instalação',
  manage_hud_panels: 'Painéis do HUD',
  manage_window: 'Janelas',
  look_at_screen: 'Leitura de tela',
  explain_screen: 'Assistente de tela',
  copy_fix: 'Copiando a correção',
  save_shortcut: 'Atalho salvo',
  open_website: 'Abrindo site',
  play_youtube: 'YouTube',
  open_streaming: 'Streaming',
  open_app: 'Abrindo app',
  close_app: 'Fechando app',
  browser_tab: 'Abas do navegador',
  media_control: 'Controle de mídia',
  set_volume: 'Volume',
  open_folder: 'Pasta',
  lock_computer: 'Bloqueio de tela',
  take_screenshot: 'Captura de tela',
  look_at_camera: 'Visão pela câmera',
  camera_view: 'Câmera',
  click_on_screen: 'Clique na tela',
  move_mouse: 'Movendo o cursor',
  type_text: 'Digitação',
  press_keys: 'Atalho de teclado',
  scroll: 'Rolagem',
  do_on_screen: 'Tarefa na tela',
  confirm_screen_action: 'Clique confirmado',
  cancel_screen_action: 'Clique cancelado',
  start_dictation: 'Modo ditado',
  write_here: 'Escrevendo no campo',
  get_agenda: 'Consulta da agenda',
  next_meeting: 'Próxima reunião',
  prepare_calendar_event: 'Preparando evento',
  prepare_calendar_update: 'Preparando alteração',
  prepare_calendar_delete: 'Preparando exclusão',
  confirm_calendar_change: 'Gravando na agenda',
  cancel_calendar_change: 'Mudança cancelada',
};

/** Protocol code of every agent tool, as in the README table. */
const PROTOCOL_TOOLS: Record<string, string[]> = {
  'WX-01': ['get_weather'],
  'NET-02': ['search_web'],
  'NWS-03': ['search_news'],
  'CHR-04': ['get_current_time'],
  'SYS-05': ['run_diagnostics'],
  'TMR-06': ['set_timer', 'get_timers'],
  'HUD-07': ['show_on_hud', 'manage_hud_panels'],
  'MED-08': ['play_youtube', 'open_streaming', 'media_control'],
  'PC-09': ['open_app', 'close_app', 'open_folder', 'lock_computer', 'take_screenshot'],
  'WEB-10': ['open_website', 'browser_tab', 'save_shortcut'],
  'AUD-11': ['set_volume'],
  'COM-12': ['check_email_address', 'draft_email', 'confirm_email_send', 'cancel_pending_email'],
  'JAN-13': ['manage_window', 'manage_screens'],
  'VIS-14': ['look_at_screen'],
  'APP-15': ['search_apps', 'prepare_app_install', 'confirm_app_install', 'cancel_app_install'],
  'MIC-16': ['check_microphone'],
  'PWR-17': ['end_session'],
  'GST-18': ['gesture_control', 'gesture_shortcuts'],
  'CAM-19': ['look_at_camera', 'camera_view'],
  'MOU-20': [
    'click_on_screen',
    'move_mouse',
    'type_text',
    'press_keys',
    'scroll',
    'do_on_screen',
    'confirm_screen_action',
    'cancel_screen_action',
  ],
  'LAY-21': ['manage_layouts', 'arrange_windows'],
  'MEM-23': ['remember', 'recall', 'forget'],
  'ROT-24': ['run_routine', 'list_routines', 'save_routine', 'delete_routine', 'schedule_routine', 'confirm_routine_step'],
  'PRS-25': ['presence_control'],
  'AGD-27': [
    'get_agenda',
    'next_meeting',
    'prepare_calendar_event',
    'prepare_calendar_update',
    'prepare_calendar_delete',
    'confirm_calendar_change',
    'cancel_calendar_change',
  ],
  'PRO-28': ['set_reminder', 'list_reminders', 'cancel_reminder', 'configure_alerts'],
  'DIT-29': ['start_dictation', 'write_here'],
  'VOZ-30': ['change_voice'],
  'TEL-31': ['explain_screen', 'copy_fix'],
};

const TOOL_CODES = new Map(
  Object.entries(PROTOCOL_TOOLS).flatMap(([code, tools]) => tools.map((tool) => [tool, code] as const)),
);

/** "get_weather" → "WX-01"; unknown tools get a generic code. */
export function toolCode(name: string): string {
  return TOOL_CODES.get(name) ?? 'PRT';
}

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
