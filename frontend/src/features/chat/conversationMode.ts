/** Last mode used in a conversation, kept in this browser. A missing entry means Express. */

const KEY = 'bt-conversation-mode';
const LIMIT = 200;

let ownerId: string | undefined;

export function setConversationModeOwner(id: string | undefined) {
  ownerId = id;
}

export function conversationModeOwner() {
  return ownerId;
}

function read(): Record<string, string> {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '{}') as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
  } catch {
    return {};
  }
}

export function conversationMode(id: string): string | undefined {
  return read()[id];
}

export function rememberConversationMode(id: string, model: string) {
  if (!id || !model) return;
  const all = read();
  if (all[id] === model) return;
  delete all[id];
  all[id] = model;
  const ids = Object.keys(all);
  if (ids.length > LIMIT) {
    for (const extra of ids.slice(0, ids.length - LIMIT)) {
      if (extra !== id) delete all[extra];
    }
  }
  try { localStorage.setItem(KEY, JSON.stringify(all)); } catch { /* private mode */ }
}
