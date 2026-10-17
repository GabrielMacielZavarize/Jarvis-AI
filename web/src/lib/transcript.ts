import type { ChatLine } from './types';

/**
 * Voice transcripts of the user arrive after Jarvis has already started answering
 * (Gemini transcribes the input late). Re-anchor each spoken line to the moment the
 * user actually started talking so the conversation reads in the right order.
 */
export function orderLines(lines: ChatLine[], arrival: Map<string, number>, voiceStarts: number[], now = Date.now()) {
  let previousSpoken = 0;
  const keyed = lines.map((line, index) => {
    if (!arrival.has(line.id)) arrival.set(line.id, now);
    const arrived = arrival.get(line.id) ?? now;
    let key = arrived;
    if (line.spoken) {
      const start = voiceStarts.find((ts) => ts > previousSpoken && ts <= arrived);
      if (start !== undefined) key = start;
      previousSpoken = arrived;
    }
    return { line, key, index };
  });
  keyed.sort((a, b) => a.key - b.key || a.index - b.index);
  return keyed.map((item) => item.line);
}
