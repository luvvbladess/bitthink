import { useAuthStore } from '@/stores/authStore';

type Name = 'interaction' | 'conversation_open' | 'list_load' | 'history_load' | 'first_token' | 'reconnect' | 'disconnect';
const pending: Array<{ name: Name; value: number; device: 'mobile' | 'desktop' }> = [];
let timer: number | undefined;
export function measure(name: Name, duration: number) {
  if (!useAuthStore.getState().accessToken || !Number.isFinite(duration)) return;
  if (pending.length < 20) pending.push({ name, value: Math.max(0, Math.min(600000, Math.round(duration))), device: matchMedia('(max-width: 767px)').matches ? 'mobile' : 'desktop' });
  timer ??= window.setTimeout(flush, 10000);
}
function flush() {
  window.clearTimeout(timer); timer = undefined;
  const metrics = pending.splice(0);
  const token = useAuthStore.getState().accessToken;
  if (!token || !metrics.length) return;
  void fetch('/api/diagnostics/performance', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ metrics }), keepalive: true }).catch(() => undefined);
}
export function installPerformance() {
  if (typeof PerformanceObserver !== 'undefined') {
    try {
      let worst = 0;
      const observer = new PerformanceObserver(list => {
        for (const entry of list.getEntries()) worst = Math.max(worst, entry.duration);
      });
      observer.observe({ type: 'event', buffered: true, durationThreshold: 40 } as PerformanceObserverInit);
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') { if (worst) measure('interaction', worst); worst = 0; flush(); } });
    } catch { /* Unsupported browser; task measurements still work. */ }
  }
  window.addEventListener('pagehide', flush);
  useAuthStore.subscribe((state, previous) => { if (state.user?.email !== previous.user?.email || !state.accessToken) pending.splice(0); });
}
