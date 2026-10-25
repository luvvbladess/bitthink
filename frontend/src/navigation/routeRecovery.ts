import { hasPendingAttachments } from '@/features/chat/useComposerDraft';

/** A route download failure needs a fresh document; a render error does not. */
export function isRouteDownloadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading (?:CSS )?chunk .+ failed|Unable to preload CSS/i.test(message);
}

// A single automatic refresh can recover an outdated entry point or a transient
// module download. A persistent outage must never cause a refresh loop.
export function refreshRouteOnce(): boolean {
  if (!navigator.onLine || hasPendingAttachments()) return false;
  try {
    const key = 'bit-think-route-refresh';
    const previous = Number(sessionStorage.getItem(key));
    const now = Date.now();
    if (previous && now - previous < 60_000) return false;
    sessionStorage.setItem(key, String(now));
  } catch {
    // Without storage we cannot guarantee that a refresh will be bounded.
    return false;
  }
  window.location.reload();
  return true;
}
