import { describe, expect, it } from 'vitest';
import { orderLines } from './transcript';
import type { ChatLine } from './types';

const agent = (id: string, text = id): ChatLine => ({ id, role: 'agent', text, ts: 0 });
const spoken = (id: string, text = id): ChatLine => ({ id, role: 'user', text, ts: 0, spoken: true });
const typed = (id: string, text = id): ChatLine => ({ id, role: 'user', text, ts: 0 });

function replay(events: { at: number; lines: ChatLine[] }[], voiceStarts: number[]) {
  const arrival = new Map<string, number>();
  let result: ChatLine[] = [];
  for (const event of events) result = orderLines(event.lines, arrival, voiceStarts, event.at);
  return result.map((line) => line.id);
}

describe('orderLines', () => {
  it('moves a late voice transcript back before the reply it triggered', () => {
    const ids = replay(
      [
        { at: 100, lines: [agent('greeting')] },
        // user starts talking at 200; Jarvis answers at 900; the transcript lands at 1200
        { at: 900, lines: [agent('greeting'), agent('answer')] },
        { at: 1200, lines: [agent('greeting'), agent('answer'), spoken('question')] },
      ],
      [200],
    );
    expect(ids).toEqual(['greeting', 'question', 'answer']);
  });

  it('keeps several turns in order', () => {
    const ids = replay(
      [
        { at: 900, lines: [agent('a1')] },
        { at: 1200, lines: [agent('a1'), spoken('q1')] },
        { at: 2900, lines: [agent('a1'), spoken('q1'), agent('a2')] },
        { at: 3100, lines: [agent('a1'), spoken('q1'), agent('a2'), spoken('q2')] },
      ],
      [200, 2000],
    );
    expect(ids).toEqual(['q1', 'a1', 'q2', 'a2']);
  });

  it('leaves typed messages and transcripts without voice data where they arrived', () => {
    const ids = replay(
      [
        { at: 100, lines: [agent('hello')] },
        { at: 500, lines: [agent('hello'), typed('typed')] },
        { at: 800, lines: [agent('hello'), typed('typed'), agent('reply')] },
        { at: 900, lines: [agent('hello'), typed('typed'), agent('reply'), spoken('late')] },
      ],
      [],
    );
    expect(ids).toEqual(['hello', 'typed', 'reply', 'late']);
  });

  it('remembers first arrival so streaming updates do not move a line', () => {
    const arrival = new Map<string, number>();
    orderLines([agent('a')], arrival, [], 100);
    orderLines([agent('a', 'a, now longer'), agent('b')], arrival, [], 500);
    expect(arrival.get('a')).toBe(100);
  });
});
