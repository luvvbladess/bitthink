import { useInfiniteQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { apiFetch } from '@/api/client';
import { measure } from '@/api/performance';
import type { DisplayMessage } from './ChatWindow';

type Page = { items: DisplayMessage[]; has_more: boolean; before: number | null; has_newer: boolean };
export function useConversationHistory(id: string | undefined, thinking: boolean, shared: boolean, around?: string | null) {
  const query = useInfiniteQuery<Page>({
    queryKey: ['messages', id, 'pages', around || 'latest'],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ signal, pageParam }) => {
      const started = performance.now();
      const params = new URLSearchParams({ limit: '80' });
      if (pageParam) params.set('before', String(pageParam));
      else if (around) params.set('around', around);
      const result = await apiFetch(`/conversations/${id}/history?${params}`, { signal, timeoutMs: 15000 });
      measure('history_load', performance.now() - started);
      return result as Page;
    },
    getNextPageParam: page => page.has_more && page.before ? page.before : undefined,
    enabled: !!id, staleTime: 3000,
    refetchInterval: thinking && id ? 2000 : shared ? 4000 : false,
  });
  const data = useMemo(() => {
    if (!query.data) return undefined;
    const unique = new Map<string, DisplayMessage>();
    [...query.data.pages].reverse().forEach(page => page.items.forEach(message => unique.set(message.id, message)));
    return [...unique.values()];
  }, [query.data]);
  return { ...query, data, hasNewer: query.data?.pages[0]?.has_newer };
}
