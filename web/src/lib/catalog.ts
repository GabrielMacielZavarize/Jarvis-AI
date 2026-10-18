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
  { id: 'click_on_screen', code: 'MOU-20', label: 'Mouse & teclado', hint: '“Clica no botão de play.” · “Rola a página.”' },
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
  click_on_screen: 'Clique na tela',
  move_mouse: 'Movendo o cursor',
  type_text: 'Digitação',
  press_keys: 'Atalho de teclado',
  scroll: 'Rolagem',
  do_on_screen: 'Tarefa na tela',
  confirm_screen_action: 'Clique confirmado',
  cancel_screen_action: 'Clique cancelado',
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
