import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useWebSocket, type WSMessage, type WSStatus } from './useWebSocket';
import { useAuthStore } from '@/stores/authStore';

const WS_URL = import.meta.env.VITE_WS_URL || (import.meta.env.PROD
  ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  : 'ws://127.0.0.1:8000');

type Listener = (message: WSMessage) => void;
type Connection = {
  status: WSStatus;
  send: (type: string, payload: Record<string, any>) => boolean;
  submit: (type: string, payload: Record<string, any>, requestId: string) => Promise<boolean>;
  waitUntilReady: (timeoutMs?: number) => Promise<boolean>;
  subscribe: (listener: Listener) => () => void;
};
const Context = createContext<Connection | null>(null);

// The authenticated session owns the connection. Visiting Settings or Billing
// must not disconnect a running answer or require another handshake on return.
export function ChatConnectionProvider({ children }: { children: ReactNode }) {
  const token = useAuthStore(state => state.accessToken);
  const listeners = useRef(new Set<Listener>());
  const receive = useCallback((message: WSMessage) => {
    listeners.current.forEach(listener => listener(message));
  }, []);
  const { status, send, submit, waitUntilReady } = useWebSocket(WS_URL, token, receive);
  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => { listeners.current.delete(listener); };
  }, []);
  const value = useMemo(() => ({ status, send, submit, waitUntilReady, subscribe }), [status, send, submit, waitUntilReady, subscribe]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useChatConnection() {
  const connection = useContext(Context);
  if (!connection) throw new Error('ChatConnectionProvider is required');
  const [messages, setMessages] = useState<Array<WSMessage & { deliveryId: number }>>([]);
  const nextDeliveryId = useRef(0);
  useEffect(() => connection.subscribe(message => {
    const received = { ...message, deliveryId: ++nextDeliveryId.current };
    setMessages(previous => [...previous, received]);
  }), [connection.subscribe]);
  // Retain only unconsumed frames. A fixed-size buffer could drop a burst of
  // chunks; retaining the entire session makes every update progressively slower.
  const acknowledge = useCallback((through: number) => setMessages(previous =>
    previous.length && previous[0].deliveryId <= through ? previous.filter(message => message.deliveryId > through) : previous
  ), []);
  // A remounted chat reads saved history and the current /chat/jobs snapshot;
  // replaying already consumed chunks would duplicate text and old errors.
  return { ...connection, messages, acknowledge };
}
