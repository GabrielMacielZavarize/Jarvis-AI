import type { CardDataMap, CardKind, JarvisMode } from './types';

/**
 * Scripted simulation used by "Modo demonstração": lets the HUD be explored
 * without LiveKit or model credentials. Every value here is fictional.
 */
export type DemoBeat =
  | { kind: 'mode'; mode: JarvisMode; ms: number }
  | { kind: 'agent'; text: string }
  | { kind: 'user'; text: string }
  | { kind: 'tool'; name: string; detail?: string; ms: number; hosts?: string[]; sources?: string[] }
  | { kind: 'card'; card: { [K in CardKind]: { kind: K; data: () => CardDataMap[K] } }[CardKind] };

const isoDay = (offset: number) => {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return date.toISOString().slice(0, 10);
};

export const DEMO_SCRIPT: DemoBeat[] = [
  { kind: 'mode', mode: 'connecting', ms: 1600 },
  { kind: 'agent', text: 'Boa noite, senhor. Todos os sistemas estão online. Em que posso ajudar?' },
  { kind: 'mode', mode: 'listening', ms: 900 },
  { kind: 'user', text: 'Jarvis, como está o tempo em São Paulo?' },
  { kind: 'tool', name: 'get_weather', detail: 'São Paulo', ms: 1900, hosts: ['geocoding-api.open-meteo.com', 'api.open-meteo.com'] },
  {
    kind: 'card',
    card: {
      kind: 'weather',
      data: () => ({
        location: 'São Paulo',
        country: 'Brasil',
        latitude: -23.55,
        longitude: -46.63,
        timezone: 'America/Sao_Paulo',
        current: { temperature: 24, feels_like: 25, humidity: 68, wind: 11, code: 2, label: 'Parcialmente nublado', is_day: 1 },
        daily: [
          { date: isoDay(0), code: 2, label: 'Parcialmente nublado', max: 27, min: 18, rain: 10 },
          { date: isoDay(1), code: 61, label: 'Chuva leve', max: 23, min: 17, rain: 70 },
          { date: isoDay(2), code: 80, label: 'Pancadas leves', max: 22, min: 16, rain: 60 },
          { date: isoDay(3), code: 1, label: 'Predominantemente limpo', max: 26, min: 15, rain: 5 },
          { date: isoDay(4), code: 0, label: 'Céu limpo', max: 29, min: 17, rain: 0 },
        ],
      }),
    },
  },
  {
    kind: 'agent',
    text: 'São Paulo marca 24 graus com céu parcialmente nublado, senhor. Leve um guarda-chuva amanhã; a previsão completa está no painel.',
  },
  { kind: 'mode', mode: 'listening', ms: 1000 },
  { kind: 'user', text: 'Rode um diagnóstico rápido do sistema.' },
  { kind: 'tool', name: 'run_diagnostics', ms: 1600 },
  {
    kind: 'card',
    card: {
      kind: 'diagnostics',
      data: () => ({
        hostname: 'MARK-L',
        os: 'Windows 11',
        cpu: { percent: 18.4, cores: 12, per_core: [22, 9, 31, 12, 6, 18, 27, 14, 8, 35, 11, 19], freq_mhz: 3600 },
        memory: { percent: 54.2, used_gb: 8.6, total_gb: 15.9 },
        disk: { mount: 'C:\\', percent: 61.8, used_gb: 293.4, total_gb: 474.8 },
        battery: { percent: 87, plugged: true },
        uptime_s: 3 * 3600 + 42 * 60,
        processes: 248,
        net: { sent_mb: 182.3, recv_mb: 1260.7 },
      }),
    },
  },
  { kind: 'agent', text: 'Diagnóstico concluído: CPU a 18 por cento e memória em 54. Nada que exija uma armadura nova.' },
  { kind: 'mode', mode: 'listening', ms: 900 },
  { kind: 'user', text: 'Coloque um timer de cinco minutos para o café.' },
  { kind: 'tool', name: 'set_timer', detail: 'café', ms: 700 },
  {
    kind: 'card',
    card: {
      kind: 'timer',
      data: () => ({ id: 'demo-cafe', label: 'café', duration_s: 300, ends_at: Date.now() + 300_000, status: 'running' }),
    },
  },
  { kind: 'agent', text: 'Timer de cinco minutos iniciado. O café, ao contrário do senhor, será pontual.' },
  { kind: 'mode', mode: 'listening', ms: 900 },
  { kind: 'user', text: 'Quais as últimas notícias de tecnologia?' },
  {
    kind: 'tool',
    name: 'search_news',
    detail: 'tecnologia',
    ms: 2400,
    hosts: ['duckduckgo.com'],
    sources: ['starkindustries.news', 'dailybugle.tech', 'avengersweekly.com', 'shield.gov.uk'],
  },
  {
    kind: 'card',
    card: {
      kind: 'news',
      data: () => ({
        topic: 'tecnologia',
        items: [
          { title: 'Reator arc compacto atinge novo recorde de eficiência', url: '', source: 'Stark Industries Newsroom', date: new Date(Date.now() - 42 * 60000).toISOString() },
          { title: 'Assistentes de voz passam a operar com latência abaixo de 300 ms', url: '', source: 'Daily Bugle Tech', date: new Date(Date.now() - 3 * 3600000).toISOString() },
          { title: 'Interfaces holográficas chegam aos escritórios', url: '', source: 'Avengers Weekly', date: new Date(Date.now() - 9 * 3600000).toISOString() },
        ],
      }),
    },
  },
  { kind: 'agent', text: 'Separei três manchetes no painel, senhor. A do reator arc parece promissora.' },
  { kind: 'mode', mode: 'listening', ms: 0 },
];

export function speakingMs(text: string) {
  return Math.max(1800, text.length * 58);
}
