import { useCallback, useEffect, useRef, useState } from 'react';
import { clearPendingSends, drainSends, enqueueSend } from '@/hooks/wsQueue';
import { apiFetch } from '@/api/client';

export type WSStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

export interface WSMessage {
  type: string;
  payload: Record<string, any>;
}

const MAX_RECONNECT_DELAY_MS = 15000;
const HEARTBEAT_INTERVAL_MS = 10000;
const RESPONSE_TIMEOUT_MS = 15000;
const DISCONNECT_NOTICE_DELAY_MS = 2500;

export function useWebSocket(url: string, token: string | null, onMessage?: (message: WSMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const disconnectNoticeRef = useRef<ReturnType<typeof setTimeout>>();
  const heartbeatRef = useRef<ReturnType<typeof setInterval>>();
  const responseTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const receiveRef = useRef(onMessage);
  receiveRef.current = onMessage;
  // The queue lives in wsQueue so logout can drop it. A remount while the
  // token is still set must not wipe a message queued during a file upload.
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const readyRef = useRef(false);
  const manualCloseRef = useRef(false);
  const [status, setStatus] = useState<WSStatus>('idle');
  const [messages, setMessages] = useState<WSMessage[]>([]);

  const flushPending = useCallback((ws: WebSocket) => {
    if (ws.readyState !== WebSocket.OPEN || !readyRef.current) return;
    for (const queued of drainSends()) {
      ws.send(JSON.stringify(queued));
    }
  }, []);

  useEffect(() => {
    if (!token || !url) return;
    manualCloseRef.current = false;
    let disposed = false;
    const restart = (ws: WebSocket) => {
      if (disposed || wsRef.current !== ws) return;
      readyRef.current = false;
      clearInterval(heartbeatRef.current);
      clearTimeout(responseTimeoutRef.current);
      responseTimeoutRef.current = undefined;
      // A dead TCP connection may take minutes to finish a close handshake.
      // Retire it immediately and ignore its late callbacks.
      ws.onclose = null;
      ws.close(4000, 'Connection timeout');
      setStatus('closed');
      connect();
    };

    const probe = () => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || responseTimeoutRef.current) return;
      ws.send(JSON.stringify({ type: 'ping', payload: {} }));
      responseTimeoutRef.current = setTimeout(() => {
        responseTimeoutRef.current = undefined;
        restart(ws);
      }, RESPONSE_TIMEOUT_MS);
    };

    const connect = () => {
      if (disposed) return;
      const fullUrl = `${url}/chat/ws`;
      const isInitialConnection = wsRef.current === null;
      const ws = new WebSocket(fullUrl);
      wsRef.current = ws;
      readyRef.current = false;
      responseTimeoutRef.current = setTimeout(() => {
        responseTimeoutRef.current = undefined;
        if (!readyRef.current) restart(ws);
      }, RESPONSE_TIMEOUT_MS);
      if (isInitialConnection) setStatus('connecting');

      ws.onopen = () => {
        if (disposed || wsRef.current !== ws) return;
        // Auth travels as the first message instead of a URL query param so
        // it doesn't end up in proxy/access logs. Do not flush the send queue
        // here: the server only accepts business frames after auth succeeds
        // and replies with `jobs`.
        ws.send(JSON.stringify({ type: 'auth', payload: { token } }));
        clearTimeout(disconnectNoticeRef.current);
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = setInterval(probe, HEARTBEAT_INTERVAL_MS);
      };

      ws.onclose = (event) => {
        if (wsRef.current !== ws) return;
        readyRef.current = false;
        clearInterval(heartbeatRef.current);
        clearTimeout(responseTimeoutRef.current);
        responseTimeoutRef.current = undefined;
        if (disposed || manualCloseRef.current) return;
        // An expired access token needs the shared HTTP refresh flow. Reopening
        // the socket with the same expired token can never recover the session.
        if (event.code === 1008) void apiFetch('/auth/me', { timeoutMs: 15000 }).catch(() => undefined);
        clearTimeout(disconnectNoticeRef.current);
        disconnectNoticeRef.current = setTimeout(() => {
          if (!readyRef.current) setStatus('closed');
        }, DISCONNECT_NOTICE_DELAY_MS);
        const delay = Math.min(500 * 2 ** reconnectAttemptsRef.current, MAX_RECONNECT_DELAY_MS);
        reconnectAttemptsRef.current += 1;
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      // `close` owns reconnect state. Browsers commonly fire `error` immediately
      // before `close`; exposing both caused the connection banner to flicker.
      ws.onerror = () => undefined;

      ws.onmessage = (event) => {
        if (disposed || wsRef.current !== ws) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong' || data.type === 'jobs') {
            clearTimeout(responseTimeoutRef.current);
            responseTimeoutRef.current = undefined;
          }
          if (data.type === 'pong') return;
          if (data.type === 'jobs') {
            readyRef.current = true;
            reconnectAttemptsRef.current = 0;
            clearTimeout(disconnectNoticeRef.current);
            setStatus('open');
            flushPending(ws);
          }
          if (receiveRef.current) receiveRef.current(data);
          else setMessages((prev) => [...prev, data]);
        } catch {
          // ignore malformed
        }
      };
    };

    connect();
    const wake = () => {
      if (document.visibilityState !== 'visible' || disposed) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        clearTimeout(reconnectTimeoutRef.current);
        connect();
      } else if (ws.readyState === WebSocket.OPEN) {
        probe();
      }
    };
    window.addEventListener('online', wake);
    document.addEventListener('visibilitychange', wake);

    return () => {
      disposed = true;
      manualCloseRef.current = true;
      clearTimeout(reconnectTimeoutRef.current);
      clearTimeout(disconnectNoticeRef.current);
      clearInterval(heartbeatRef.current);
      clearTimeout(responseTimeoutRef.current);
      responseTimeoutRef.current = undefined;
      window.removeEventListener('online', wake);
      document.removeEventListener('visibilitychange', wake);
      readyRef.current = false;
      wsRef.current?.close();
      wsRef.current = null;
      if (!tokenRef.current) clearPendingSends();
    };
  // `status` deliberately stays out of dependencies: reconnect callbacks manage
  // it, while recreating the effect on every status change would itself flap WS.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, token, flushPending]);

  const send = useCallback((type: string, payload: Record<string, any>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN && readyRef.current) {
      wsRef.current.send(JSON.stringify({ type, payload }));
      return true;
    }
    enqueueSend({ type, payload });
    return false;
  }, []);

  const waitUntilReady = useCallback((timeoutMs = 20000) => {
    if (wsRef.current?.readyState === WebSocket.OPEN && readyRef.current) {
      return Promise.resolve(true);
    }
    return new Promise<boolean>((resolve) => {
      const started = Date.now();
      const tick = () => {
        if (wsRef.current?.readyState === WebSocket.OPEN && readyRef.current) {
          resolve(true);
          return;
        }
        if (Date.now() - started >= timeoutMs) {
          resolve(false);
          return;
        }
        window.setTimeout(tick, 200);
      };
      tick();
    });
  }, []);

  const clearMessages = useCallback(() => setMessages([]), []);

  return { status, messages, send, clearMessages, waitUntilReady };
}
