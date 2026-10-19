/**
 * VOZ-30: what the 3D core shows besides the voice — "pensando" (the model is working on a reply)
 * and "executando" (a tool reported by the agent is running) — plus a short flash when a tool ends.
 */
import type { JarvisMode, ToolStatus } from './types';

export type CoreActivity = 'idle' | 'thinking' | 'executing';

const OFFLINE_MODES: ReadonlySet<JarvisMode> = new Set(['offline', 'standby', 'error']);
export const FLASH_MS = 900;

export function coreActivity(mode: JarvisMode, activeTool: string | null): CoreActivity {
  if (OFFLINE_MODES.has(mode)) return 'idle';
  if (activeTool) return 'executing';
  return mode === 'thinking' ? 'thinking' : 'idle';
}

export interface ToolResult {
  ok: boolean;
  at: number;
}

let lastResult: ToolResult | null = null;

/** Called for each "tool" event that is not "running" (done or error). */
export function markToolResult(status: Exclude<ToolStatus, 'running'>, at = Date.now()) {
  lastResult = { ok: status === 'done', at };
}

export function lastToolResult(): ToolResult | null {
  return lastResult;
}

/** 1 right when a tool ends, fading to 0 after FLASH_MS. */
export function flashLevel(result: ToolResult | null, now: number): number {
  if (!result) return 0;
  const elapsed = now - result.at;
  if (elapsed < 0 || elapsed >= FLASH_MS) return 0;
  return 1 - elapsed / FLASH_MS;
}
