import { useAuthStore } from '@/stores/authStore';

function key() {
  const user = useAuthStore.getState().user;
  return `bit-think-last-chat:${user?.id || user?.email || 'anonymous'}`;
}

// Navigation state is per account and per browser tab. Returning from settings
// must not depend on a slow background request that persists the active chat.
export function lastConversation(): string | undefined {
  try { return sessionStorage.getItem(key()) || undefined; } catch { return undefined; }
}

export function rememberConversation(id?: string) {
  try {
    if (id) sessionStorage.setItem(key(), id);
    else sessionStorage.removeItem(key());
  } catch { /* The URL remains the source of truth when storage is unavailable. */ }
}
