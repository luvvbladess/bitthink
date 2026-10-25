import { useAuthStore } from '@/stores/authStore';

type Category = 'render' | 'chunk' | 'unhandled';
const reports = new Map<string, { id: string; time: number }>();

function routeName() {
  const path = location.pathname;
  if (/^\/join\//.test(path)) return '/join/:token';
  if (/^\/admin\/users\/[^/]+$/.test(path)) return '/admin/users/:id';
  return ['/', '/chat', '/settings', '/billing', '/login', '/register', '/privacy', '/admin', '/admin/users', '/admin/stats'].includes(path) ? path : '/other';
}

/** Never transmit error.message, raw stacks, URLs with queries, or user content. */
export function reportClientError(error: unknown, category: Category): string | undefined {
  const token = useAuthStore.getState().accessToken;
  if (!token) return;
  const build = (document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src.split('/').pop()?.split('?')[0] || 'local').replace(/[^A-Za-z0-9_.-]/g, '').slice(0, 120);
  const frames = [...(error instanceof Error ? error.stack || '' : '').matchAll(/\/assets\/([A-Za-z0-9_.-]+\.js):(\d+):(\d+)/g)]
    .slice(0, 4).map(match => ({ file: match[1], line: Number(match[2]), column: Number(match[3]) }));
  const route = routeName();
  const key = JSON.stringify([category, route, build, frames]);
  const now = Date.now();
  for (const [name, report] of reports) if (now - report.time > 60000) reports.delete(name);
  const previous = reports.get(key);
  if (previous) return previous.id;
  if (reports.size >= 10) return;
  const id = crypto.randomUUID();
  reports.set(key, { id, time: now });
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  void fetch('/api/diagnostics/client-error', {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ report_id: id, category, route, build, frames }), keepalive: true, signal: controller.signal,
  }).catch(() => undefined).finally(() => window.clearTimeout(timeout));
  return id;
}

export function installDiagnostics() {
  window.addEventListener('error', event => { if (event.error) reportClientError(event.error, 'unhandled'); });
  window.addEventListener('unhandledrejection', event => reportClientError(event.reason, 'unhandled'));
}
