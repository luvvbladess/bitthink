import { useLayoutEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/authStore';

interface Draft { text: string; files: File[] }
const drafts = new Map<string, Draft>();
const redirects = new WeakMap<Draft, string>();
const storageKey = (scope: string) => `bit-think-draft:${scope}`;

/** Text survives a document refresh; browser File objects only live in memory. */
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

  useLayoutEffect(() => {
    const previous = currentScope.current;
    if (previous === scope) return;
    currentScope.current = scope;
    setDraft(read(scope));
  }, [scope]);

  function update(patch: (value: Draft) => Draft) {
    const next = patch(read(scope));
    write(scope, next);
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
    text: draft.text,
    pendingFiles: draft.files,
    setText: (value: string | ((previous: string) => string)) => update(previous => ({ ...previous, text: typeof value === 'function' ? value(previous.text) : value })),
    setPendingFiles: (value: File[] | ((previous: File[]) => File[])) => update(previous => ({ ...previous, files: typeof value === 'function' ? value(previous.files) : value })),
    submission,
  };
}
