import { useCallback, useEffect, useRef, useState } from 'react';
import { clearPendingSends, drainSends, enqueueSend } from '@/hooks/wsQueue';

export type WSStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

interface WSMessage {
  type: string;
  payload: Record<string, any>;
}

const MAX_RECONNECT_DELAY_MS = 15000;
const HEARTBEAT_INTERVAL_MS = 25000;
const DISCONNECT_NOTICE_DELAY_MS = 2500;

export function useWebSocket(url: string, token: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const disconnectNoticeRef = useRef<ReturnType<typeof setTimeout>>();
  const heartbeatRef = useRef<ReturnType<typeof setInterval>>();
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

    const connect = () => {
      const fullUrl = `${url}/chat/ws`;
      const isInitialConnection = wsRef.current === null;
      const ws = new WebSocket(fullUrl);
      wsRef.current = ws;
      readyRef.current = false;
      if (isInitialConnection) setStatus('connecting');

      ws.onopen = () => {
        // Auth travels as the first message instead of a URL query param so
        // it doesn't end up in proxy/access logs. Do not flush the send queue
        // here: the server only accepts business frames after auth succeeds
        // and replies with `jobs`.
        ws.send(JSON.stringify({ type: 'auth', payload: { token } }));
        reconnectAttemptsRef.current = 0;
        clearTimeout(disconnectNoticeRef.current);
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', payload: {} }));
          }
        }, HEARTBEAT_INTERVAL_MS);
        setStatus('open');
      };

      ws.onclose = () => {
        readyRef.current = false;
        clearInterval(heartbeatRef.current);
        if (wsRef.current !== ws) return;
        if (manualCloseRef.current) return;
        clearTimeout(disconnectNoticeRef.current);
        disconnectNoticeRef.current = setTimeout(() => {
          if (wsRef.current?.readyState !== WebSocket.OPEN) setStatus('closed');
        }, DISCONNECT_NOTICE_DELAY_MS);
        const delay = Math.min(500 * 2 ** reconnectAttemptsRef.current, MAX_RECONNECT_DELAY_MS);
        reconnectAttemptsRef.current += 1;
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      // `close` owns reconnect state. Browsers commonly fire `error` immediately
      // before `close`; exposing both caused the connection banner to flicker.
      ws.onerror = () => undefined;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong') return;
          if (data.type === 'jobs') {
            readyRef.current = true;
            flushPending(ws);
          }
          setMessages((prev) => [...prev, data]);
        } catch {
          // ignore malformed
        }
      };
    };

    connect();

    return () => {
      manualCloseRef.current = true;
      clearTimeout(reconnectTimeoutRef.current);
      clearTimeout(disconnectNoticeRef.current);
      clearInterval(heartbeatRef.current);
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
