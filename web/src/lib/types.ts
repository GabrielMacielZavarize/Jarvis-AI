export type JarvisMode =
  | 'offline'
  | 'standby'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'error';

export type CardKind =
  | 'weather'
  | 'search'
  | 'news'
  | 'time'
  | 'diagnostics'
  | 'timer'
  | 'note'
  | 'email'
  | 'media'
  | 'screen'
  | 'install'
  | 'camera'
  | 'pointer';

export interface WeatherDay {
  date: string;
  code: number;
  label: string;
  max: number;
  min: number;
  rain?: number | null;
}

export interface WeatherData {
  location: string;
  country?: string | null;
  latitude: number;
  longitude: number;
  timezone?: string | null;
  current: {
    temperature: number;
    feels_like?: number | null;
    humidity: number;
    wind: number;
    code: number;
    label: string;
    is_day?: number;
  };
  daily: WeatherDay[];
}

export interface SearchData {
  query: string;
  results: { title: string; url: string; snippet: string }[];
}

export interface NewsData {
  topic: string;
  items: {
    title: string;
    url: string;
    source?: string;
    date?: string | null;
    snippet?: string;
    image?: string | null;
  }[];
}

export interface TimeData {
  location: string;
  timezone: string;
  iso: string;
  utc_offset: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface DiagnosticsData {
  hostname: string;
  os: string;
  cpu: { percent: number; cores: number; per_core: number[]; freq_mhz?: number | null };
  memory: { percent: number; used_gb: number; total_gb: number };
  disk: { mount: string; percent: number; used_gb: number; total_gb: number };
  battery?: { percent: number; plugged: boolean } | null;
  uptime_s: number;
  processes: number;
  top?: { name: string; cpu: number; mem_mb: number }[];
  net?: { sent_mb: number; recv_mb: number } | null;
}

export interface TimerData {
  id: string;
  label: string;
  duration_s?: number;
  ends_at?: number;
  status: 'running' | 'done';
}

export interface NoteData {
  title: string;
  content: string;
}

export interface EmailData {
  /** address = dictated address assembled by check_email_address, waiting for the user's OK. */
  status: 'address' | 'draft' | 'sent' | 'cancelled';
  to: string;
  cc?: string | null;
  subject?: string;
  preview?: string;
  code?: string;
  /** Only for status "address": whether it is in JARVIS_ALLOWED_EMAILS, and the closest one if not. */
  allowed?: boolean;
  suggestion?: string | null;
}

export interface InstallPackage {
  name: string;
  id: string;
  version?: string | null;
  source: 'winget' | 'msstore';
  match?: string | null;
}

export interface InstallData {
  status: 'results' | 'pending' | 'installing' | 'installed' | 'failed' | 'cancelled';
  query?: string;
  candidates?: InstallPackage[];
  package?: InstallPackage;
  code?: string;
  message?: string;
}

export interface MediaData {
  service: string;
  title: string;
  url: string;
  channel?: string;
  thumbnail?: string;
}

export interface ScreenData {
  url: string;
  label: string;
  takenAt: number;
}

/** Webcam panel: always the live feed; `snapshot` is the frame Jarvis analysed (look_at_camera). */
export interface CameraData {
  snapshot?: string | null;
  takenAt?: number | null;
  question?: string | null;
}

/** GET /api/camera/state: the webcam owned by the HUD server (camera.CameraHub). */
export interface CameraState {
  enabled: boolean;
  /** Device open (or opening): the webcam light is on. */
  active: boolean;
  /** Frames are arriving. */
  streaming: boolean;
  /** Feeds, snapshots and gesture readers currently holding the camera. */
  users: number;
  pinned: boolean;
  device: string | null;
  backend: string | null;
  width: number | null;
  height: number | null;
  fps: number;
  since: number | null;
  error: string | null;
}

export interface PointerLogEntry {
  ts: number;
  text: string;
  level: 'ok' | 'info' | 'warn' | 'error';
}

/** A mouse/keyboard action (MOU-20): what Jarvis clicked/typed, with the print and the target drawn. */
export interface PointerData {
  action_id: string;
  /** pending = waiting for "confirmar clique <código>"; running = a step of do_on_screen. */
  status: 'done' | 'running' | 'pending' | 'refused' | 'notfound' | 'stopped' | 'error' | 'cancelled';
  action: string;
  message: string;
  target?: string | null;
  label?: string | null;
  screen?: string | null;
  code?: string | null;
  step?: number | null;
  steps?: number | null;
  log: PointerLogEntry[];
  /** Blob URL of the annotated print, attached in the browser from the jarvis.pointer stream. */
  image?: string | null;
}

export type HudPanelAction = 'list' | 'close' | 'close_all' | 'expand' | 'collapse';

/** What the agent can ask the HUD over the `jarvis.hud` RPC. */
export type HudRequest =
  | { action: HudPanelAction; targets: string[] }
  | { action: 'mic' }
  | { action: 'end_session' };

/** A panel as the user sees it: the agent gets the same title that is shown on screen. */
export interface PanelInfo {
  id: string;
  kind: CardKind;
  title: string;
  detail: string;
  expanded: boolean;
}

export interface PanelCommandResult {
  /** Panels still open, newest first. */
  open: PanelInfo[];
  /** Panels the command really closed/expanded/collapsed. */
  changed: PanelInfo[];
  /** Requested panels that matched nothing on screen. */
  unmatched: string[];
}

/** Microphone the browser captures from, reported to the agent ("qual microfone está conectado?"). */
export interface MicReport {
  label: string | null;
  device_id: string;
  is_default: boolean;
  enabled: boolean;
  /** Seconds since the browser last received sound from it (null: never in this session). */
  signal_s: number | null;
  /** Seconds since the agent last detected the user's voice (null: never). */
  heard_s: number | null;
  available: string[];
}

export interface CardDataMap {
  weather: WeatherData;
  search: SearchData;
  news: NewsData;
  time: TimeData;
  diagnostics: DiagnosticsData;
  timer: TimerData;
  note: NoteData;
  email: EmailData;
  media: MediaData;
  screen: ScreenData;
  install: InstallData;
  camera: CameraData;
  pointer: PointerData;
}

export type HudCard = {
  [K in CardKind]: { id: string; kind: K; data: CardDataMap[K]; createdAt: number };
}[CardKind];

export type ToolStatus = 'running' | 'done' | 'error';

export type HudEvent =
  | { type: 'tool'; name: string; status: ToolStatus; detail?: string | null; ts: number }
  | { type: 'voice'; state: 'speaking'; ts: number }
  | { type: 'net'; hosts: string[]; kind: LinkKind; ts: number }
  | { type: 'hud'; action: 'close' | 'clear'; kinds: CardKind[]; ts: number }
  | { [K in CardKind]: { type: 'card'; kind: K; data: CardDataMap[K]; ts: number } }[CardKind];

export type LinkKind = 'request' | 'source' | 'model' | 'link';

/** A connection drawn on the 3D globe. */
export interface NetLink {
  id: string;
  host: string;
  label: string;
  lat: number;
  lon: number;
  kind: LinkKind;
  createdAt: number;
  ttl: number;
}

export interface GeoPoint {
  name: string;
  lat: number;
  lon: number;
}

export type LogLevel = 'info' | 'tool' | 'ok' | 'warn' | 'error';

export interface LogEntry {
  id: string;
  ts: number;
  level: LogLevel;
  text: string;
}

export interface ChatLine {
  id: string;
  role: 'user' | 'agent';
  text: string;
  ts: number;
  /** True for transcripts of the user's voice (they arrive late and get re-ordered). */
  spoken?: boolean;
}

export interface ServerStatus {
  version: string;
  ready: boolean;
  backend?: string;
  model?: string;
  livekit_configured: boolean;
  email_enabled?: boolean;
  tools?: string[];
  pc_control?: boolean;
  app_install?: boolean;
  camera?: boolean;
  computer_use?: boolean;
  home?: { name: string; latitude: number; longitude: number } | null;
  errors: string[];
}
