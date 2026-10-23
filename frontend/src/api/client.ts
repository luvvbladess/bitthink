import { useAuthStore } from '@/stores/authStore';

export const API_BASE = import.meta.env.VITE_API_URL || '/api';

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

// Shared in-flight refresh so concurrent 401s don't each trigger their own
// /auth/refresh call; they all await the same promise.
let refreshPromise: Promise<string | null> | null = null;
let refreshAccount: string | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = useAuthStore.getState().refreshToken;
  if (!refreshToken) return null;
  if (refreshPromise && refreshAccount === refreshToken) return refreshPromise;
  refreshAccount = refreshToken;
  const pending = (async () => {
    const timed = withTimeout({}, 15000);
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
        signal: timed.options.signal,
      });
      if (useAuthStore.getState().refreshToken !== refreshToken) throw new Error('Аккаунт изменился. Повторите действие.');
      if (res.status === 401 || res.status === 403) return null;
      if (!res.ok) throw new ApiError('Не удалось обновить подключение. Попробуйте ещё раз.', res.status);
      const data = await res.json();
      // A refresh from a previous account must not replace a newer login.
      if (useAuthStore.getState().refreshToken !== refreshToken) throw new Error('Аккаунт изменился. Повторите действие.');
      useAuthStore.getState().setTokens(data.access_token, data.refresh_token);
      return data.access_token as string;
    } finally { timed.cancel(); }
  })();
  refreshPromise = pending;
  try {
    return await pending;
  } finally {
    if (refreshPromise === pending) { refreshPromise = null; refreshAccount = null; }
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
  const abort = () => controller.abort();
  if (options.signal) {
    if (options.signal.aborted) controller.abort();
    else options.signal.addEventListener('abort', abort, { once: true });
  }
  return {
    options: { ...options, signal: controller.signal },
    cancel: () => { window.clearTimeout(timer); options.signal?.removeEventListener('abort', abort); },
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
      const detail = data.detail || data.message;
      throw new ApiError(typeof detail === 'string' ? detail : `Не удалось выполнить запрос (HTTP ${res.status}). Попробуйте ещё раз.`, res.status);
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

export interface FormProgressEvent {
  type?: string;
  done?: number;
  total?: number;
  label?: string;
  detail?: string;
  [key: string]: unknown;
}

/** Multipart upload that can report real byte progress and newline-delimited server events. */
export function apiFormDataProgress(
  path: string,
  formData: FormData,
  options: {
    signal?: AbortSignal;
    timeoutMs?: number;
    headers?: Record<string, string>;
    onUploadProgress?: (loaded: number, total: number) => void;
    onEvent?: (event: FormProgressEvent) => void;
  } = {},
): Promise<Record<string, unknown>> {
  const send = (token: string | null) =>
    new Promise<XMLHttpRequest>((resolve, reject) => {
      if (options.signal?.aborted) {
        reject(Object.assign(new Error('Запрос остановлен'), { name: 'AbortError' }));
        return;
      }
      const xhr = new XMLHttpRequest();
      let carry = '';
      let parsedLength = 0;
      const consume = (flushTail: boolean) => {
        const chunk = xhr.responseText.slice(parsedLength);
        parsedLength = xhr.responseText.length;
        carry += chunk;
        const lines = carry.split('\n');
        carry = flushTail ? '' : (lines.pop() ?? '');
        const pending = flushTail ? [...lines, carry].filter(Boolean) : lines;
        if (flushTail) carry = '';
        for (const line of pending) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            options.onEvent?.(JSON.parse(trimmed) as FormProgressEvent);
          } catch {
            // A non-event body (plain JSON error) is handled by the caller.
          }
        }
      };
      xhr.open('POST', `${API_BASE}${path}`);
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      for (const [key, value] of Object.entries(options.headers || {})) xhr.setRequestHeader(key, value);
      if (options.timeoutMs) xhr.timeout = options.timeoutMs;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) options.onUploadProgress?.(event.loaded, event.total);
      };
      xhr.onprogress = () => consume(false);
      const abort = () => xhr.abort();
      options.signal?.addEventListener('abort', abort, { once: true });
      xhr.onloadend = () => options.signal?.removeEventListener('abort', abort);
      xhr.onabort = () => reject(Object.assign(new Error('Запрос остановлен'), { name: 'AbortError' }));
      xhr.ontimeout = () => reject(new Error('Превышено время ожидания'));
      xhr.onerror = () => reject(new Error('Не удалось загрузить файл'));
      xhr.onload = () => {
        consume(true);
        options.signal?.removeEventListener('abort', abort);
        resolve(xhr);
      };
      xhr.send(formData);
    });

  const run = async (token: string | null, allowRefresh: boolean): Promise<Record<string, unknown>> => {
    const xhr = await send(token);
    if (xhr.status === 401 && allowRefresh && useAuthStore.getState().refreshToken) {
      const next = await refreshAccessToken();
      if (!next) {
        useAuthStore.getState().logout();
        throw new Error('HTTP 401');
      }
      return run(next, false);
    }
    if (xhr.status >= 400) {
      let detail = `HTTP ${xhr.status}`;
      try {
        const data = JSON.parse(xhr.responseText);
        detail = data.detail || data.message || detail;
      } catch {
        // keep the status text
      }
      throw new Error(typeof detail === 'string' ? detail : `HTTP ${xhr.status}`);
    }
    const events: FormProgressEvent[] = [];
    let sawEvent = false;
    for (const line of xhr.responseText.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const event = JSON.parse(trimmed) as FormProgressEvent;
        if (event && typeof event === 'object' && typeof event.type === 'string') {
          sawEvent = true;
          events.push(event);
        }
      } catch {
        sawEvent = false;
        break;
      }
    }
    if (sawEvent) {
      const failure = [...events].reverse().find((event) => event.type === 'error');
      if (failure) throw new Error(String(failure.detail || 'Не удалось прочитать документ'));
      const result = [...events].reverse().find((event) => event.type === 'result');
      if (!result) throw new Error('Сервер не закончил разбор документа');
      const { type: _type, ...rest } = result;
      return rest;
    }
    return JSON.parse(xhr.responseText);
  };

  return run(useAuthStore.getState().accessToken, true);
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

export async function apiBlob(path: string): Promise<Blob> {
  let token = useAuthStore.getState().accessToken;
  let response = await doFetch(path, {}, token);
  if (response.status === 401 && useAuthStore.getState().refreshToken) {
    token = await refreshAccessToken();
    if (token) response = await doFetch(path, {}, token);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Не удалось скачать файл');
  }
  return response.blob();
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
