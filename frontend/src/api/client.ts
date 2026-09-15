import { useAuthStore } from '@/stores/authStore';

export const API_BASE = import.meta.env.VITE_API_URL || '/api';

// Shared in-flight refresh so concurrent 401s don't each trigger their own
// /auth/refresh call; they all await the same promise.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const refreshToken = useAuthStore.getState().refreshToken;
    if (!refreshToken) return null;
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) return null;
      const data = await res.json();
      useAuthStore.getState().setTokens(data.access_token, data.refresh_token);
      return data.access_token as string;
    } catch {
      return null;
    }
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

function doFetch(path: string, options: RequestInit, token: string | null) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
}

function withTimeout(options: RequestInit, timeoutMs?: number): { options: RequestInit; cancel: () => void; timedOut: () => boolean } {
  if (!timeoutMs) return { options, cancel: () => undefined, timedOut: () => false };
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  if (options.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true });
  }
  return {
    options: { ...options, signal: controller.signal },
    cancel: () => window.clearTimeout(timer),
    timedOut: () => timedOut,
  };
}

export async function apiFetch(path: string, options: RequestInit & { timeoutMs?: number } = {}) {
  const { timeoutMs, ...rest } = options;
  const timed = withTimeout(rest, timeoutMs);
  let token = useAuthStore.getState().accessToken;
  try {
    let res = await doFetch(path, timed.options, token);

    if (res.status === 401 && useAuthStore.getState().refreshToken) {
      token = await refreshAccessToken();
      if (token) {
        res = await doFetch(path, timed.options, token);
      } else {
        useAuthStore.getState().logout();
      }
    }

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || data.message || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new Error(timed.timedOut() ? 'Превышено время ожидания' : 'Запрос остановлен');
    }
    throw error;
  } finally {
    timed.cancel();
  }
}

export async function apiFormData(path: string, formData: FormData, options?: { signal?: AbortSignal; timeoutMs?: number }) {
  const timed = withTimeout({ signal: options?.signal }, options?.timeoutMs);
  let token = useAuthStore.getState().accessToken;
  try {
    let res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: formData,
      signal: timed.options.signal,
    });

    if (res.status === 401 && useAuthStore.getState().refreshToken) {
      token = await refreshAccessToken();
      if (token) {
        res = await fetch(`${API_BASE}${path}`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
          signal: timed.options.signal,
        });
      } else {
        useAuthStore.getState().logout();
      }
    }

    return res;
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new Error(timed.timedOut() ? 'Превышено время ожидания' : 'Запрос остановлен');
    }
    throw error;
  } finally {
    timed.cancel();
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function exportDocx(markdown: string) {
  const body = JSON.stringify({ markdown });
  let token = useAuthStore.getState().accessToken;
  let res = await fetch(`${API_BASE}/documents/docx`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body,
  });
  if (res.status === 401 && useAuthStore.getState().refreshToken) {
    token = await refreshAccessToken();
    if (token) {
      res = await fetch(`${API_BASE}/documents/docx`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body,
      });
    } else {
      useAuthStore.getState().logout();
    }
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || data.message || 'Не удалось экспортировать документ');
  }
  const blob = await res.blob();
  if (!blob.size) throw new Error('Сервер вернул пустой документ');
  return blob;
}
