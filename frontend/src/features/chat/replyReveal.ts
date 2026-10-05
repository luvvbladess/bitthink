import { useSyncExternalStore } from 'react';
import { normalizeMarkdown } from './markdownText';

/**
 * Typing-out of the reply that is arriving right now.
 *
 * The server persists the whole answer first and then hands it over in 800-character
 * pieces within milliseconds, then says `done`. So the text has to be paced on the
 * client, and the pacing must survive everything the chat does around it: the live
 * copy of the message being swapped for the saved one (a new id), the job being
 * dropped on `done`, the list being refetched. That is why the state lives here, in a
 * module, keyed by nothing but the reply's own text, and not in a component.
 *
 * Two subscriptions on purpose: the *snapshot* changes a few times per reply (text
 * arrived, typing ended) and may re-render the chat; `shown` changes ~30 times a second
 * and is read by the one message that is being typed, never by the list.
 */
const MIN_CPS = 170; // floor, characters per second
const MAX_CPS = 2400;
const CATCH_UP_S = 1; // time constant the backlog is drained with
const COMMIT_MS = 32; // ~30 fps: re-parsing the markdown is the cost, not the paint
const WORD_LOOKAHEAD = 14;

export interface ReplySnapshot {
  id: number;
  convId: string;
  /** What arrived, untouched. */
  raw: string;
  /** `raw` cleaned for display. This is the text that gets typed. */
  full: string;
  typing: boolean;
}

const EMPTY: ReplySnapshot = { id: 0, convId: '', raw: '', full: '', typing: false };

let snap: ReplySnapshot = EMPTY;
let shown = 0;
let pos = 0;
let sealed = true;
let raf = 0;
let lastFrame = 0;
let lastCommit = 0;
let frameCost = 0; // smoothed time between frames, ms: grows when the device cannot keep up
const coarse = new Set<() => void>();
const fine = new Set<() => void>();
const idle: Array<() => void> = [];

const emit = (listeners: Set<() => void>) => listeners.forEach((listener) => listener());

function setSnap(patch: Partial<ReplySnapshot>) {
  snap = { ...snap, ...patch };
  emit(coarse);
}

function noMotion(): boolean {
  if (typeof window === 'undefined') return true;
  return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) || document.hidden;
}

/** Move `index` to the end of the word it sits in, so the text grows by whole words. */
function snapToWord(text: string, index: number): number {
  if (index >= text.length) return text.length;
  if (index > 0) {
    const prev = text.charCodeAt(index - 1);
    if (prev >= 0xd800 && prev <= 0xdbff) index += 1; // never split a surrogate pair
  }
  const limit = Math.min(text.length, index + WORD_LOOKAHEAD);
  for (let i = index; i < limit; i += 1) {
    const ch = text.charCodeAt(i);
    if (ch === 32 || ch === 10) return i + 1;
  }
  return Math.min(index, text.length);
}

/** An unfinished `**`, `` ` `` or `#` renders as raw punctuation for a moment; carry it with the next character. */
function holdMarkup(text: string, count: number): number {
  while (count < text.length && /[*_`~#>]/.test(text[count - 1] || '')) count += 1;
  return count;
}

function finishTyping() {
  cancelAnimationFrame(raf);
  raf = 0;
  pos = snap.full.length;
  shown = snap.full.length;
  emit(fine);
  if (snap.typing) setSnap({ typing: false });
  idle.splice(0).forEach((fn) => fn());
}

function frame(now: number) {
  raf = 0;
  const target = snap.full;
  const dt = Math.min((now - lastFrame) / 1000, 1.5);
  lastFrame = now;
  frameCost = frameCost * 0.8 + Math.min(dt * 1000, 250) * 0.2;
  if (noMotion()) {
    finishTyping(); // nobody is watching, or motion is off: don't queue up a replay
    return;
  }
  pos = Math.min(pos, target.length);
  const backlog = target.length - pos;
  if (backlog > 0) {
    const step = backlog * (1 - Math.exp(-dt / CATCH_UP_S));
    pos += Math.min(backlog, Math.min(MAX_CPS * dt, Math.max(MIN_CPS * dt, step)));
  }
  if (pos >= target.length - 0.5) {
    finishTyping();
    return;
  }
  // A slow device re-parses the text more rarely instead of freezing the page on every step.
  if (now - lastCommit >= Math.max(COMMIT_MS, frameCost * 1.8)) {
    lastCommit = now;
    const next = holdMarkup(target, snapToWord(target, Math.floor(pos)));
    if (next !== shown) {
      shown = next;
      emit(fine);
    }
  }
  raf = requestAnimationFrame(frame);
}

export const replyReveal = {
  /** A new turn starts: forget the previous reply. */
  begin(convId: string) {
    cancelAnimationFrame(raf);
    raf = 0;
    pos = 0;
    shown = 0;
    frameCost = 0;
    sealed = false;
    idle.length = 0;
    snap = { id: snap.id + 1, convId, raw: '', full: '', typing: false };
    emit(coarse);
    emit(fine);
  },

  /** A piece of the reply arrived over the socket. */
  push(convId: string, piece: string) {
    if (sealed || convId !== snap.convId) this.begin(convId);
    const raw = snap.raw + piece;
    const full = normalizeMarkdown(raw);
    pos = Math.min(pos, full.length);
    if (noMotion()) {
      pos = full.length;
      shown = full.length;
      setSnap({ raw, full, typing: false });
      emit(fine);
      return;
    }
    setSnap({ raw, full, typing: true });
    if (!raf) {
      lastFrame = performance.now();
      raf = requestAnimationFrame(frame);
    }
  },

  /** The turn is over (done, stopped, failed). The next piece starts a new reply. */
  seal() {
    sealed = true;
  },

  /** Run `fn` once nothing is being typed (immediately if nothing is). */
  whenIdle(fn: () => void) {
    if (!snap.typing) fn();
    else idle.push(fn);
  },

  isTyping(convId?: string) {
    return snap.typing && (!convId || snap.convId === convId);
  },
};

function subscribe(set: Set<() => void>) {
  return (listener: () => void) => {
    set.add(listener);
    return () => {
      set.delete(listener);
    };
  };
}
const subscribeCoarse = subscribe(coarse);
const subscribeFine = subscribe(fine);

/**
 * Changes a few times per reply. Safe for the chat window. A message that cannot be the
 * reply passes `false` and never re-renders on it (the list can hold hundreds).
 */
export function useReplySnapshot(enabled = true): ReplySnapshot {
  return useSyncExternalStore(subscribeCoarse, () => (enabled ? snap : EMPTY), () => EMPTY);
}

/** How many characters of `full` are on screen. Changes ~30x/s: subscribe only from the message being typed. */
export function useRevealShown(): number {
  return useSyncExternalStore(subscribeFine, () => Math.min(shown, snap.full.length), () => 0);
}

/**
 * Is `clean` (already cleaned) this reply? Equal, or one is the start of the other:
 * the live copy holds only what arrived so far, the saved one can already hold it all.
 */
export function isReplyText(clean: string, reply: ReplySnapshot): boolean {
  return clean.length > 0 && reply.full.length > 0 && (reply.full.startsWith(clean) || clean.startsWith(reply.full));
}
