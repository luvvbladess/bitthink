import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useMutation, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { measure } from '@/api/performance';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '@/api/client';
import type { ConversationItem } from './ChatSidebar';
import { lastConversation, rememberConversation } from '@/navigation/chatLocation';

export function useConversationNavigation(options: { onExternalSelection: () => void; onPersistError: (message: string) => void }) {
  const callbacks = useRef(options);
  callbacks.current = options;
  const [searchParams, setSearchParams] = useSearchParams();
  const openNewChat = searchParams.get('new') === '1';
  const requestedConversation = searchParams.get('c');
  const [activeConvId, setActiveConvId] = useState<string | undefined>(() => openNewChat ? undefined : requestedConversation || lastConversation());
  const activeConvRef = useRef(activeConvId);
  activeConvRef.current = activeConvId;
  const appliedLocationRef = useRef(requestedConversation);
  const selectionRequestRef = useRef(0);
  const conversationsQuery = useInfiniteQuery<ConversationItem[]>({
    queryKey: ['conversations', 'pages'],
    initialPageParam: 0,
    queryFn: async ({ signal, pageParam }) => {
      const started = performance.now();
      const result = await apiFetch(`/conversations?limit=50&offset=${pageParam}`, { signal, timeoutMs: 15000 });
      measure('list_load', performance.now() - started);
      return result;
    },
    getNextPageParam: (page, pages) => page.length === 50 ? pages.length * 50 : undefined,
    staleTime: 5_000,
  });
  const loadedConversations = conversationsQuery.data?.pages.flat() || [];
  const selected = useQuery<ConversationItem>({ queryKey: ['conversation-summary', activeConvId],
    queryFn: ({ signal }) => apiFetch(`/conversations/${activeConvId}/summary`, { signal, timeoutMs: 15000 }),
    enabled: !!activeConvId && conversationsQuery.isFetched && !loadedConversations.some(item => item.id === activeConvId) });
  const conversations = selected.data?.id && !loadedConversations.some(item => item.id === selected.data.id)
    ? [...loadedConversations, selected.data] : loadedConversations;
  const conversationsFetched = conversationsQuery.isFetched;

  // Restore the latest/active chat after a page reload instead of showing an
  // empty home screen while its messages and document cards still exist.
  useLayoutEffect(() => {
    if (openNewChat) return;
    if (requestedConversation) {
      // Router navigation can commit after a local selection. Only a changed
      // URL (including Back/Forward) may replace it; the old URL must not undo
      // a newly created chat while that navigation is still being committed.
      const locationChanged = appliedLocationRef.current !== requestedConversation;
      appliedLocationRef.current = requestedConversation;
      if (locationChanged && requestedConversation !== activeConvRef.current) {
        ++selectionRequestRef.current;
        callbacks.current.onExternalSelection();
        setActiveConvId(requestedConversation);
      }
      return;
    }
    appliedLocationRef.current = null;
    if (activeConvId) {
      setSearchParams({ c: activeConvId }, { replace: true });
    } else if (conversations.length) {
      const restored = conversations.find((conversation) => conversation.is_active) || conversations[0];
      setActiveConvId(restored.id);
      setSearchParams({ c: restored.id }, { replace: true });
    }
  }, [activeConvId, conversations, openNewChat, requestedConversation, setSearchParams]);

  useLayoutEffect(() => { rememberConversation(activeConvId); }, [activeConvId]);

  const activateMutation = useMutation({
    // Persist rapid selections in order, so a slow earlier request cannot
    // become the server's active conversation after the latest selection.
    scope: { id: 'activate-conversation' },
    mutationFn: (id: string) => apiFetch(`/conversations/${id}/activate`, { method: 'POST', timeoutMs: 15000 }),
  });

  useEffect(() => {
    if (!activeConvId) return;
    activateMutation.mutate(activeConvId, { onError: () => {
      if (activeConvRef.current === activeConvId) callbacks.current.onPersistError('Не удалось сохранить выбор беседы. Она останется открытой; повторите выбор, когда соединение восстановится.');
    } });
  }, [activeConvId]);

  return { activeConvId, setActiveConvId, activeConvRef, selectionRequestRef, openNewChat, setSearchParams,
    conversationsQuery, conversations, conversationsFetched, activateMutation };
}
