import { createContext, useContext } from 'react';
import type { StudioCanvasSource } from './DesignCanvas';

export const CanvasNavigation = createContext<((source: StudioCanvasSource) => void) | null>(null);
export const useCanvasNavigation = () => useContext(CanvasNavigation);

const KEY = 'bt-chat-canvas-visibility';

export function canvasVisibility(): Record<string, boolean> {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(KEY) || '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter((row): row is [string, boolean] => typeof row[1] === 'boolean'));
  } catch { return {}; }
}

export function rememberCanvasVisibility(current: Record<string, boolean>, id: string, open: boolean): Record<string, boolean> {
  const next = { ...current };
  delete next[id];
  next[id] = open;
  const bounded = Object.fromEntries(Object.entries(next).slice(-100));
  try { sessionStorage.setItem(KEY, JSON.stringify(bounded)); } catch { /* Private mode keeps the in-memory choice. */ }
  return bounded;
}
