import { weatherGlyph } from '../../lib/format';

/** Line-art weather icon in the HUD style. */
export function WeatherGlyph({ code, isDay = 1, small = false }: { code: number; isDay?: number; small?: boolean }) {
  const kind = weatherGlyph(code, isDay);
  const cloud = <path d="M15 34h18a7 7 0 0 0 0-14 10 10 0 0 0-19-2 8 8 0 0 0 1 16z" />;

  return (
    <svg className={`glyph ${small ? 'glyph--sm' : ''}`} viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      {kind === 'sun' && (
        <>
          <circle cx="24" cy="24" r="8" />
          {Array.from({ length: 8 }, (_, i) => {
            const a = (i * Math.PI) / 4;
            return (
              <line
                key={i}
                x1={24 + Math.cos(a) * 13}
                y1={24 + Math.sin(a) * 13}
                x2={24 + Math.cos(a) * 18}
                y2={24 + Math.sin(a) * 18}
              />
            );
          })}
        </>
      )}
      {kind === 'moon' && <path d="M30 10a14 14 0 1 0 8 22A12 12 0 0 1 30 10z" />}
      {kind === 'cloud' && (
        <>
          <circle cx="30" cy="15" r="6" strokeDasharray="2 3" />
          {cloud}
        </>
      )}
      {kind === 'fog' && (
        <>
          {cloud}
          <path d="M10 40h28M14 44h20" />
        </>
      )}
      {kind === 'rain' && (
        <>
          {cloud}
          <path d="M18 38l-2 5M25 38l-2 5M32 38l-2 5" />
        </>
      )}
      {kind === 'storm' && (
        <>
          {cloud}
          <path d="M25 35l-4 7h6l-4 6" />
        </>
      )}
      {kind === 'snow' && (
        <>
          {cloud}
          <path d="M18 40h0M25 42h0M32 40h0" strokeWidth="3" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}
