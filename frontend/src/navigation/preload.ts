// Share the import promise between intent preloading and React.lazy.
export const loadChat = () => import('@/pages/ChatPage');
export const loadSettings = () => import('@/pages/SettingsPage');
export const loadBilling = () => import('@/pages/BillingPage');

export function preloadRoute(path: string) {
  const load = path === '/chat' ? loadChat : path === '/settings' ? loadSettings : path === '/billing' ? loadBilling : null;
  if (load) void load().catch(() => undefined);
}

export function preloadAccountPages() {
  preloadRoute('/settings');
  preloadRoute('/billing');
}
