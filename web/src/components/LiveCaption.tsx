import { useEffect, useMemo, useState } from 'react';
import { usePrefs } from '../lib/prefs';
import type { ChatLine } from '../lib/types';

/** About the pace of Jarvis's voice, so the words keep up with the audio. */
const WORD_MS = 330;
/** Further behind than this (a transcript that arrived at once), it catches up faster. */
const CATCH_UP_WORDS = 6;
/** Words kept on screen: the tail of the sentence, about two lines. */
const TAIL_WORDS = 22;
/** The caption stays this long after Jarvis stops talking. */
const LINGER_MS = 4000;

/** Jarvis's words under the core while he speaks, appearing one by one like film subtitles. */
export function LiveCaption({ lines, speaking }: { lines: ChatLine[]; speaking: boolean }) {
  const { captions } = usePrefs();
  const line = useMemo(() => [...lines].reverse().find((item) => item.role === 'agent') ?? null, [lines]);
  const words = useMemo(() => line?.text.split(/\s+/).filter(Boolean) ?? [], [line?.text]);
  const [shown, setShown] = useState(0);
  const [lingering, setLingering] = useState(false);

  useEffect(() => setShown(0), [line?.id]);

  useEffect(() => {
    if (shown >= words.length) return;
    const behind = words.length - shown;
    const fast = behind > CATCH_UP_WORDS;
    const timer = window.setTimeout(
      () => setShown((count) => Math.min(words.length, count + (fast ? 2 : 1))),
      fast ? WORD_MS / 3 : WORD_MS,
    );
    return () => window.clearTimeout(timer);
  }, [shown, words.length]);

  useEffect(() => {
    if (speaking) {
      setLingering(true);
      return;
    }
    const timer = window.setTimeout(() => setLingering(false), LINGER_MS);
    return () => window.clearTimeout(timer);
  }, [speaking, line?.id]);

  if (!captions || !line || !lingering || shown === 0) return null;
  const start = Math.max(0, shown - TAIL_WORDS);

  return (
    <p className="caption" aria-hidden>
      {start > 0 && <span className="caption__more">…</span>}
      {words.slice(start, shown).map((word, index) => (
        <span key={start + index}>{word} </span>
      ))}
    </p>
  );
}
