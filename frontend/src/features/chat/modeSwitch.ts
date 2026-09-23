import type { SearchItem } from './clarify';

export const MODE_SWITCH_QUERY = '__mode_switch__';

const SWITCHABLE = new Set(['studio', 'docgen', 'director', 'kimi-k2.6', 'gpt-6-sol']);

export interface ModeSwitch {
  model: string;
  label: string;
  reason: string;
  accept: string;
  done: string;
}

export function modeSwitchFromSearch(search?: SearchItem[] | null): ModeSwitch | null {
  for (const item of search || []) {
    if (item?.query !== MODE_SWITCH_QUERY) continue;
    try {
      const parsed = JSON.parse(item.summary || '');
      const model = String(parsed?.model || '');
      const label = String(parsed?.label || '').trim();
      const reason = String(parsed?.reason || '').trim();
      const accept = String(parsed?.accept || '').trim();
      const done = String(parsed?.done || '').trim();
      if (!SWITCHABLE.has(model) || !label || !reason || !accept || !done) return null;
      return { model, label, reason, accept, done };
    } catch {
      return null;
    }
  }
  return null;
}
