import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { loadDraft, saveDraft, clearDraftAccount } from './draftStorage';

interface Draft { text: string; files: File[] }
const drafts = new Map<string, Draft>();
const redirects = new WeakMap<Draft, string>();
const storageKey = (scope: string) => `bit-think-draft:${scope}`;
const unsafe = new Set<string>();
const saves = new Map<string, Promise<unknown>>();
if (typeof window !== 'undefined') window.addEventListener('beforeunload', event => {
  if (unsafe.size) { event.preventDefault(); event.returnValue = ''; }
});
useAuthStore.subscribe((state, previous) => {
  const account = previous.user?.id || previous.user?.email;
  if (account && (!state.accessToken || (state.user?.id || state.user?.email) !== account)) {
    for (const scope of drafts.keys()) if (scope.startsWith(`${account}:`)) { drafts.delete(scope); unsafe.delete(scope); try { sessionStorage.removeItem(storageKey(scope)); } catch { /* unavailable */ } }
    void Promise.allSettled([...saves.values()]).then(() => clearDraftAccount(String(account))).catch(() => undefined);
  }
});

/** Pending files delay automatic route reloads, even after a local backup. */
export function hasPendingAttachments(): boolean {
  return [...drafts.values()].some(draft => draft.files.length > 0);
}

function read(scope: string): Draft {
  const cached = drafts.get(scope);
  if (cached) return cached;
  let text = '';
  try { text = sessionStorage.getItem(storageKey(scope)) || ''; } catch { /* Storage can be unavailable. */ }
  const draft = { text, files: [] };
  drafts.set(scope, draft);
  return draft;
}

function write(scope: string, draft: Draft) {
  drafts.set(scope, draft);
  try {
    if (draft.text) sessionStorage.setItem(storageKey(scope), draft.text);
    else sessionStorage.removeItem(storageKey(scope));
  } catch { /* Keep the in-memory draft even when storage is full or disabled. */ }
  if (draft.files.length) unsafe.add(scope); else unsafe.delete(scope);
  const save = (saves.get(scope) || Promise.resolve()).catch(() => undefined).then(() => saveDraft(scope, draft)).then(safe => {
    if (drafts.get(scope) === draft && safe) unsafe.delete(scope);
  }).catch(() => { window.dispatchEvent(new CustomEvent('bitthink-draft-warning', { detail: scope })); });
  saves.set(scope, save);
}

/** Keep unsent work with its account and conversation, including across route changes. */
export function adoptNewComposerDraft(account: string, conversationId: string) {
  const source = `${account}:new`;
  const target = `${account}:${conversationId}`;
  const draft = read(source);
  write(target, draft);
  write(source, { text: '', files: [] });
  redirects.set(draft, target);
}

export function useComposerDraft(conversationId: string | null | undefined) {
  const account = useAuthStore(s => s.user?.id || s.user?.email || 'anonymous');
  const scope = `${account}:${conversationId || 'new'}`;
  const currentScope = useRef(scope);
  const [draft, setDraft] = useState(() => read(scope));
  const [restoring, setRestoring] = useState(true);
  const [storageWarning, setStorageWarning] = useState('');
  useEffect(() => {
    const warn = (event: Event) => { if ((event as CustomEvent).detail === scope) setStorageWarning('Не удалось сохранить черновик на устройстве. Не закрывайте вкладку до отправки.'); };
    window.addEventListener('bitthink-draft-warning', warn);
    return () => window.removeEventListener('bitthink-draft-warning', warn);
  }, [scope]);
  useEffect(() => {
    let disposed = false;
    const original = read(scope);
    setRestoring(true);
    void loadDraft(scope).then(saved => {
      if (!disposed && saved && read(scope) === original) {
        const next = { text: original.text || saved.text, files: original.files.length ? original.files : saved.files };
        drafts.set(scope, next); setDraft(next);
      }
    }).catch(() => { if (!disposed) setStorageWarning('Не удалось сохранить черновик на устройстве. Не закрывайте вкладку до отправки.'); })
      .finally(() => { if (!disposed) setRestoring(false); });
    return () => { disposed = true; };
  }, [scope]);

  useLayoutEffect(() => {
    const previous = currentScope.current;
    if (previous === scope) return;
    currentScope.current = scope;
    setDraft(read(scope));
  }, [scope]);

  function update(patch: (value: Draft) => Draft) {
    const next = patch(read(scope));
    write(scope, next);
    if (next.files.reduce((size, file) => size + file.size, 0) > 20 * 1024 * 1024) setStorageWarning('Вложения больше 20 МБ сохраняются только до закрытия вкладки. Отправьте их перед обновлением страницы.');
    if (currentScope.current === scope) setDraft(next);
  }

  function submission() {
    const sent = read(scope);
    return () => {
      const target = redirects.get(sent) || scope;
      const current = read(target);
      // A late acknowledgement must never erase a newer draft.
      if (current.text !== sent.text || current.files !== sent.files) return;
      const empty = { text: '', files: [] };
      write(target, empty);
      if (currentScope.current === target) setDraft(empty);
    };
  }

  return {
    restoring, storageWarning,
    text: draft.text,
    pendingFiles: draft.files,
    setText: (value: string | ((previous: string) => string)) => update(previous => ({ ...previous, text: typeof value === 'function' ? value(previous.text) : value })),
    setPendingFiles: (value: File[] | ((previous: File[]) => File[])) => update(previous => ({ ...previous, files: typeof value === 'function' ? value(previous.files) : value })),
    submission,
  };
}
