import type { GeoPoint } from './types';

/**
 * Approximate locations for the hosts Jarvis talks to, used only to draw the
 * connections on the 3D globe. These are well-known HQ/datacenter regions or a
 * country guess from the domain — a visualisation, not a traceroute.
 */
const PLACES = {
  saoPaulo: { name: 'São Paulo', lat: -23.55, lon: -46.63 },
  rio: { name: 'Rio de Janeiro', lat: -22.91, lon: -43.17 },
  ashburn: { name: 'Virgínia, EUA', lat: 39.04, lon: -77.49 },
  iowa: { name: 'Iowa, EUA', lat: 41.26, lon: -95.86 },
  mountainView: { name: 'Califórnia, EUA', lat: 37.39, lon: -122.08 },
  sanFrancisco: { name: 'São Francisco, EUA', lat: 37.77, lon: -122.42 },
  losGatos: { name: 'Los Gatos, EUA', lat: 37.24, lon: -121.97 },
  seattle: { name: 'Seattle, EUA', lat: 47.61, lon: -122.33 },
  burbank: { name: 'Burbank, EUA', lat: 34.18, lon: -118.31 },
  newYork: { name: 'Nova York, EUA', lat: 40.71, lon: -74.0 },
  dallas: { name: 'Dallas, EUA', lat: 32.78, lon: -96.8 },
  toronto: { name: 'Toronto', lat: 43.65, lon: -79.38 },
  mexico: { name: 'Cidade do México', lat: 19.43, lon: -99.13 },
  buenosAires: { name: 'Buenos Aires', lat: -34.6, lon: -58.38 },
  santiago: { name: 'Santiago', lat: -33.45, lon: -70.67 },
  bogota: { name: 'Bogotá', lat: 4.71, lon: -74.07 },
  frankfurt: { name: 'Frankfurt', lat: 50.11, lon: 8.68 },
  amsterdam: { name: 'Amsterdã', lat: 52.37, lon: 4.9 },
  london: { name: 'Londres', lat: 51.51, lon: -0.13 },
  paris: { name: 'Paris', lat: 48.86, lon: 2.35 },
  madrid: { name: 'Madri', lat: 40.42, lon: -3.7 },
  lisbon: { name: 'Lisboa', lat: 38.72, lon: -9.14 },
  milan: { name: 'Milão', lat: 45.46, lon: 9.19 },
  dublin: { name: 'Dublin', lat: 53.35, lon: -6.26 },
  stockholm: { name: 'Estocolmo', lat: 59.33, lon: 18.07 },
  tokyo: { name: 'Tóquio', lat: 35.68, lon: 139.69 },
  seoul: { name: 'Seul', lat: 37.57, lon: 126.98 },
  singapore: { name: 'Singapura', lat: 1.35, lon: 103.82 },
  mumbai: { name: 'Mumbai', lat: 19.08, lon: 72.88 },
  sydney: { name: 'Sydney', lat: -33.87, lon: 151.21 },
  menloPark: { name: 'Menlo Park, EUA', lat: 37.45, lon: -122.18 },
} satisfies Record<string, GeoPoint>;

const KNOWN_HOSTS: [suffix: string, place: GeoPoint][] = [
  ['open-meteo.com', PLACES.frankfurt],
  ['duckduckgo.com', PLACES.ashburn],
  ['googleapis.com', PLACES.iowa],
  ['gemini.google.com', PLACES.iowa],
  ['google.com', PLACES.mountainView],
  ['youtube.com', PLACES.mountainView],
  ['youtu.be', PLACES.mountainView],
  ['ytimg.com', PLACES.mountainView],
  ['livekit.cloud', PLACES.saoPaulo],
  ['openai.com', PLACES.sanFrancisco],
  ['netflix.com', PLACES.losGatos],
  ['spotify.com', PLACES.stockholm],
  ['twitch.tv', PLACES.sanFrancisco],
  ['globo.com', PLACES.rio],
  ['disneyplus.com', PLACES.burbank],
  ['max.com', PLACES.newYork],
  ['primevideo.com', PLACES.seattle],
  ['amazon.com', PLACES.seattle],
  ['crunchyroll.com', PLACES.sanFrancisco],
  ['deezer.com', PLACES.paris],
  ['wikipedia.org', PLACES.ashburn],
  ['github.com', PLACES.sanFrancisco],
  ['microsoft.com', PLACES.seattle],
  ['bing.com', PLACES.seattle],
  ['reddit.com', PLACES.sanFrancisco],
  ['x.com', PLACES.sanFrancisco],
  ['twitter.com', PLACES.sanFrancisco],
  ['instagram.com', PLACES.menloPark],
  ['facebook.com', PLACES.menloPark],
];

const TLD_PLACES: Record<string, GeoPoint> = {
  br: PLACES.saoPaulo,
  pt: PLACES.lisbon,
  es: PLACES.madrid,
  uk: PLACES.london,
  de: PLACES.frankfurt,
  fr: PLACES.paris,
  it: PLACES.milan,
  nl: PLACES.amsterdam,
  ie: PLACES.dublin,
  se: PLACES.stockholm,
  jp: PLACES.tokyo,
  kr: PLACES.seoul,
  in: PLACES.mumbai,
  au: PLACES.sydney,
  ca: PLACES.toronto,
  mx: PLACES.mexico,
  ar: PLACES.buenosAires,
  cl: PLACES.santiago,
  co: PLACES.bogota,
  sg: PLACES.singapore,
};

const GENERIC_HUBS = [PLACES.ashburn, PLACES.sanFrancisco, PLACES.dallas, PLACES.newYork, PLACES.frankfurt, PLACES.amsterdam, PLACES.london];

export const DEFAULT_HOME: GeoPoint = PLACES.saoPaulo;

function hash(text: string) {
  let value = 2166136261;
  for (let i = 0; i < text.length; i++) value = Math.imul(value ^ text.charCodeAt(i), 16777619);
  return value >>> 0;
}

/** Where to draw a host on the globe (stable per host, slightly jittered). */
export function locateHost(rawHost: string): GeoPoint {
  const host = rawHost.toLowerCase().replace(/^www\./, '');
  const seed = hash(host);
  const jitter = (shift: number) => (((seed >>> shift) & 0xff) / 255 - 0.5) * 2.4;

  const known = KNOWN_HOSTS.find(([suffix]) => host === suffix || host.endsWith(`.${suffix}`));
  const base = known?.[1] ?? TLD_PLACES[host.split('.').pop() ?? ''] ?? GENERIC_HUBS[seed % GENERIC_HUBS.length];
  return { name: base.name, lat: base.lat + jitter(0), lon: base.lon + jitter(8) };
}

/** Best guess of the user's location when JARVIS_HOME_CITY is not set. */
export function homeFromTimezone(): GeoPoint {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone ?? '';
  const byZone: Record<string, GeoPoint> = {
    'America/Sao_Paulo': PLACES.saoPaulo,
    'America/Argentina/Buenos_Aires': PLACES.buenosAires,
    'America/Santiago': PLACES.santiago,
    'America/Bogota': PLACES.bogota,
    'America/Mexico_City': PLACES.mexico,
    'America/New_York': PLACES.newYork,
    'America/Los_Angeles': PLACES.sanFrancisco,
    'Europe/Lisbon': PLACES.lisbon,
    'Europe/Madrid': PLACES.madrid,
    'Europe/London': PLACES.london,
    'Europe/Paris': PLACES.paris,
    'Europe/Berlin': PLACES.frankfurt,
    'Asia/Tokyo': PLACES.tokyo,
  };
  return byZone[zone] ?? DEFAULT_HOME;
}
