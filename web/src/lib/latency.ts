/** Response time of each turn (end of the user's speech → Jarvis's first word), for the Sistema panel. */

export interface LatencyStats {
  last: number;
  average: number;
  samples: number[];
}

/** Turns averaged in the panel. */
export const LATENCY_WINDOW = 10;

export function addLatency(stats: LatencyStats | null, seconds: number): LatencyStats {
  const samples = [...(stats?.samples ?? []), seconds].slice(-LATENCY_WINDOW);
  const average = samples.reduce((sum, value) => sum + value, 0) / samples.length;
  return { last: seconds, average, samples };
}

/** Up to 1.5 s feels instant in a voice chat; past 3 s it feels stuck. */
export function latencyTone(seconds: number): 'ok' | 'warn' | 'slow' {
  if (seconds <= 1.5) return 'ok';
  return seconds <= 3 ? 'warn' : 'slow';
}

/** 1.234 → "1,2 s". */
export function formatSeconds(seconds: number): string {
  return `${seconds.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`;
}
