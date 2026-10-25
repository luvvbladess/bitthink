// Deduplicate focus/hover/background preloads and the actual route load. A
// rejected speculative preload must not poison a later navigation attempt.
function routeLoader<T>(load: () => Promise<T>) {
  let pending: Promise<T> | undefined;
  return () => {
    if (!pending) pending = load().catch(error => { pending = undefined; throw error; });
    return pending;
  };
}
export const loadChat = routeLoader(() => import('@/pages/ChatPage'));
export const loadSettings = routeLoader(() => import('@/pages/SettingsPage'));
export const loadBilling = routeLoader(() => import('@/pages/BillingPage'));

export function preloadRoute(path: string) {
  if (!navigator.onLine) return;
  const load = path === '/chat' ? loadChat : path === '/settings' ? loadSettings : path === '/billing' ? loadBilling : null;
  if (load) void load().catch(() => undefined);
}

export function preloadAccountPages() {
  preloadRoute('/settings');
  preloadRoute('/billing');
}
