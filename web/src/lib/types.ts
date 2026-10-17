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
  | 'screen';

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
  status: 'draft' | 'sent' | 'cancelled';
  to: string;
  cc?: string | null;
  subject?: string;
  preview?: string;
  code?: string;
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

export type HudPanelAction = 'list' | 'close' | 'close_all' | 'expand' | 'collapse';

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
  home?: { name: string; latitude: number; longitude: number } | null;
  errors: string[];
}
