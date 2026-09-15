export type DialogueTick = {
  id: string;
  label: string;
};

export type DialogueJumpFn = (id: string) => void;

export const MIN_DIALOGUE_QUESTIONS = 2;

export function snippetQuestion(text: string, max = 108) {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1).trimEnd()}…`;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function messageOffset(scroller: HTMLElement, id: string) {
  const el = scroller.querySelector<HTMLElement>(`[data-dialogue-id="${id}"]`);
  if (!el) return 0;
  const root = scroller.getBoundingClientRect();
  const box = el.getBoundingClientRect();
  return box.top - root.top + scroller.scrollTop;
}

export function scrollToQuestion(scroller: HTMLElement, id: string, instant: boolean) {
  const target = messageOffset(scroller, id) - 88;
  const max = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
  const end = clamp(target, 0, max);
  if (instant) {
    scroller.scrollTop = end;
    return;
  }
  const start = scroller.scrollTop;
  const dist = end - start;
  if (Math.abs(dist) < 2) return;
  const duration = clamp(380 + Math.abs(dist) * 0.18, 420, 720);
  const t0 = performance.now();
  const step = (now: number) => {
    const t = clamp((now - t0) / duration, 0, 1);
    const k = 1 - (1 - t) ** 4;
    scroller.scrollTop = start + dist * k;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
