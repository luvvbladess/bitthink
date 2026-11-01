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
export const loadAdminLayout = routeLoader(() => import('@/pages/admin/AdminLayout'));
export const loadAdminUsers = routeLoader(() => import('@/pages/admin/AdminUsersPage'));
export const loadAdminStats = routeLoader(() => import('@/pages/admin/AdminStatsPage'));
export const loadAdminUser = routeLoader(() => import('@/pages/admin/AdminUserDetailPage'));

export function preloadRoute(path: string) {
  if (!navigator.onLine) return;
  if (path === '/admin' || path.startsWith('/admin/')) {
    void loadAdminLayout().catch(() => undefined);
    const page = path === '/admin/stats' ? loadAdminStats : /^\/admin\/users\/[^/]+$/.test(path) ? loadAdminUser : loadAdminUsers;
    void page().catch(() => undefined);
    return;
  }
  const load = path === '/chat' ? loadChat : path === '/settings' ? loadSettings : path === '/billing' ? loadBilling : null;
  if (load) void load().catch(() => undefined);
}

export function preloadAccountPages() {
  preloadRoute('/settings');
  preloadRoute('/billing');
}
