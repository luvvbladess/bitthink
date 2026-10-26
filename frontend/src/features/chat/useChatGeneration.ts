import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { SetURLSearchParams } from 'react-router-dom';
import { useChatConnection } from '@/hooks/ChatConnection';
import { apiFetch } from '@/api/client';
import type { DisplayMessage } from './ChatWindow';
import { filesQueryKey } from '@/features/editor/ConversationFiles';
import { replyReveal } from './replyReveal';
import { splitSearch } from './clarify';
import { dropJob, emptyJob, mergeRemoteJobs, upsertJob, type LiveJobPatch, type LiveJobsMap } from './liveJobs';

// Fallback parser for Kimi-style citations like [1] Title – https://...
// so the "Web search (N)" panel still appears even if the backend extras
// message is missed or empty.
function parseSearchFromText(text: string): { query: string; summary: string }[] | undefined {
  const results: { query: string; summary: string }[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\n/)) {
    const m = line.match(/^\[(\d+)\]\s*(.+)$/);
    if (!m) continue;
    const body = m[2].trim();
    const parts = body.split(/\s+[–—-]\s+/);
    let title = '';
    let url = '';
    if (parts.length >= 2) {
      title = parts[0].trim();
      url = parts[parts.length - 1].trim();
    } else {
      const urlMatch = body.match(/https?:\/\/[^\s\)\]\>\"\']+/);
      if (urlMatch) {
        url = urlMatch[0];
        title = body.replace(url, '').trim();
      }
    }
    if (!url) continue;
    url = url.replace(/[.,;:!?\)\]\>\"\']+$/, '');
    if (seen.has(url)) continue;
    seen.add(url);
    results.push({ query: title || 'Источник', summary: url });
  }
  return results.length ? results : undefined;
}

export function useChatGeneration({ activeConvId, setActiveConvId, setSearchParams, setRegeneratingId, setDisplayMessages }: {
  activeConvId?: string;
  setActiveConvId: Dispatch<SetStateAction<string | undefined>>;
  setSearchParams: SetURLSearchParams;
  setRegeneratingId: Dispatch<SetStateAction<number | null>>;
  setDisplayMessages: Dispatch<SetStateAction<DisplayMessage[]>>;
}) {
  const queryClient = useQueryClient();
  const [jobs, setJobs] = useState<LiveJobsMap>({});
  const [jobErrors, setJobErrors] = useState<Record<string, string>>({});
  const live = activeConvId ? jobs[activeConvId] : undefined;
  const thinking = Boolean(live?.thinking);
  const statusText = live?.statusText || '';
  const pendingContent = useMemo(() => ({
    convId: live?.convId,
    userText: live?.convId === activeConvId ? (live?.userText || '') : '',
    text: live?.convId === activeConvId ? (live?.text || '') : '',
    thinking,
    file: live?.convId === activeConvId ? live?.file : undefined,
    reasoning: live?.convId === activeConvId ? live?.reasoning : undefined,
    search: live?.convId === activeConvId ? live?.search : undefined,
  }), [live, activeConvId, thinking]);
  const generatingIds = Object.keys(jobs).filter((id) => jobs[id]?.thinking);
  const patchJob = (convId: string | undefined, patch: LiveJobPatch) => {
    if (!convId) return;
    setJobs((prev) => upsertJob(prev, convId, patch));
  };
  const finishJob = (convId?: string) => {
    if (!convId) return;
    delete imageBaselineRef.current[convId];
    httpJobsRef.current.delete(convId);
    setJobs((prev) => {
      const current = prev[convId];
      const keepCanvas =
        Boolean(current?.file?.url)
        || Boolean(current?.file?.canvas)
        || /\.html?$/i.test(current?.file?.filename || '');
      if (current?.file && keepCanvas) {
        return upsertJob(prev, convId, { thinking: false, statusText: '', file: current.file });
      }
      return dropJob(prev, convId);
    });
  };
  function restoreJobs(list: Parameters<typeof mergeRemoteJobs>[1]) {
    setJobs(previous => mergeRemoteJobs(previous, list));
    setJobErrors(previous => {
      let next = previous;
      for (const job of list || []) if (job.error && previous[job.conversation_id] !== job.error) {
        next = { ...next, [job.conversation_id]: job.error };
      }
      return next;
    });
  }
  const { messages: wsMessages, acknowledge, send, submit, status: wsStatus, waitUntilReady } = useChatConnection();
  const processedThrough = useRef(0);
  const ignoreByConvRef = useRef<Set<string>>(new Set());
  const imageAbortRef = useRef<AbortController | null>(null);
  const imageBaselineRef = useRef<Record<string, Set<string>>>({});
  // Chats whose current job runs over plain HTTP (images), not over the socket: no stream is coming.
  const httpJobsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (wsStatus === 'open' && activeConvId) {
      queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
    }
  }, [wsStatus, activeConvId, queryClient]);

  useEffect(() => {
    apiFetch('/chat/jobs')
      .then((data) => {
        restoreJobs(data.jobs);
      })
      .catch(() => undefined);
  }, [wsStatus]);

  useEffect(() => {
    wsMessages.forEach((msg) => {
      if (msg.deliveryId <= processedThrough.current) return;
      processedThrough.current = msg.deliveryId;

      const convId = (msg.payload?.conversation_id as string | undefined) || undefined;
      if (msg.type === 'accepted' && convId) {
        if (['completed', 'failed', 'stopped', 'interrupted', 'archived'].includes(msg.payload.status)) {
          finishJob(convId);
          if (['failed', 'interrupted'].includes(msg.payload.status)) setJobErrors(previous => ({ ...previous, [convId]: 'Предыдущая отправка была принята, но ответ не завершён. Проверьте историю и отправьте новый запрос.' }));
        }
        queryClient.invalidateQueries({ queryKey: ['messages', convId] });
      }
      if (convId && ignoreByConvRef.current.has(convId) && msg.type !== 'stopped' && msg.type !== 'done' && msg.type !== 'error') {
        return;
      }

      if (msg.type === 'conversation_sync') {
        const syncId = msg.payload?.conversation_id as string | undefined;
        if (syncId) {
          queryClient.invalidateQueries({ queryKey: ['messages', syncId] });
          queryClient.invalidateQueries({ queryKey: ['asides', syncId] });
          queryClient.invalidateQueries({ queryKey: ['conversations'] });
          queryClient.invalidateQueries({ queryKey: filesQueryKey(syncId) });
        }
        return;
      }
      if (msg.type === 'jobs') {
        restoreJobs(msg.payload.jobs);
        return;
      }
      if (msg.type === 'thinking' && convId) {
        patchJob(convId, { thinking: true });
      }
      if (msg.type === 'status' && convId) {
        patchJob(convId, { thinking: true, statusText: msg.payload.text || '' });
      }
      if (msg.type === 'reasoning_delta' && convId) {
        setJobs((prev) => upsertJob(prev, convId, { reasoning: (prev[convId]?.reasoning || '') + (msg.payload.text || '') }));
      }
      if (msg.type === 'chunk' && convId) {
        replyReveal.push(convId, msg.payload.text || '');
        setJobs((prev) => {
          const current = prev[convId] || emptyJob(convId);
          const nextText = (current.text || '') + (msg.payload.text || '');
          const fallbackSearch = !current.search?.length ? parseSearchFromText(nextText) : undefined;
          return upsertJob(prev, convId, {
            text: nextText,
            thinking: false,
            search: current.search?.length ? current.search : fallbackSearch,
          });
        });
      }
      if (msg.type === 'meta' && convId) {
        // replaces: the open chat was deleted elsewhere and the reply moved to a new one.
        if (!activeConvId || msg.payload?.replaces === activeConvId) {
          setActiveConvId(convId);
          setSearchParams({ c: convId }, { replace: true });
        }
        patchJob(convId, { thinking: true });
      }
      if (msg.type === 'file' && convId) {
        patchJob(convId, {
          file: {
            filename: msg.payload.filename,
            data: msg.payload.data || '',
            url: msg.payload.url,
            canvas: Boolean(msg.payload.canvas),
          },
        });
      }
      if (msg.type === 'extras' && convId) {
        const extrasSearch = msg.payload.search?.length ? msg.payload.search : undefined;
        setJobs((prev) => {
          const current = prev[convId] || emptyJob(convId);
          const fallbackSearch = !extrasSearch ? parseSearchFromText(current.text) : undefined;
          const hasClarify = splitSearch(extrasSearch).questions.length > 0;
          return upsertJob(prev, convId, {
            reasoning: msg.payload.reasoning || undefined,
            search: extrasSearch || fallbackSearch,
            ...(hasClarify ? { thinking: false, statusText: '' } : {}),
          });
        });
      }
      if (msg.type === 'done') {
        queryClient.invalidateQueries({ queryKey: ['project-workspace'] });
        queryClient.invalidateQueries({ queryKey: ['project-suggestions'] });
        const doneConvId = convId || pendingContent.convId;
        if (doneConvId) ignoreByConvRef.current.delete(doneConvId);
        if (doneConvId === activeConvId) setRegeneratingId(null);
        replyReveal.seal();
        if (doneConvId && replyReveal.isTyping(doneConvId)) {
          // The text arrives in milliseconds but is typed out over a few seconds. Keep the live
          // copy on screen until then; it drops itself as soon as the saved message matches.
          patchJob(doneConvId, { thinking: false, statusText: '' });
          replyReveal.whenIdle(() => finishJob(doneConvId));
        } else {
          finishJob(doneConvId);
        }
        if (doneConvId) {
          queryClient.invalidateQueries({ queryKey: ['messages', doneConvId] });
        }
        queryClient.invalidateQueries({ queryKey: ['conversations'] });
        queryClient.invalidateQueries({ queryKey: ['subscription'] });
      }
      if (msg.type === 'stopped') {
        const stoppedId = convId || pendingContent.convId;
        if (stoppedId) ignoreByConvRef.current.delete(stoppedId);
        replyReveal.seal();
        patchJob(stoppedId, { thinking: false, statusText: '' });
      }
      if (msg.type === 'error') {
        const errConvId = convId || pendingContent.convId || activeConvId;
        if (errConvId) ignoreByConvRef.current.delete(errConvId);
        if (errConvId === activeConvId) setRegeneratingId(null);
        replyReveal.seal();
        finishJob(errConvId);
        const raw = msg.payload.message || 'Internal error';
        const errorText = /законч|тариф|токен|картинк/i.test(raw) ? raw : `Ошибка: ${raw}`;
        if (errConvId) {
          setJobErrors((prev) => ({ ...prev, [errConvId]: errorText }));
        }
        if (errConvId === activeConvId) {
          setDisplayMessages((m) => {
            if (m.some((message) => message.content === errorText)) return m;
            return [...m, { id: `err-${Date.now()}`, role: 'assistant', content: errorText }];
          });
        }
        queryClient.invalidateQueries({ queryKey: ['subscription'] });
        if (errConvId) {
          queryClient.invalidateQueries({ queryKey: ['messages', errConvId] });
        }
      }
    });
    if (wsMessages.length) acknowledge(processedThrough.current);
  }, [wsMessages, activeConvId, queryClient, pendingContent.convId, acknowledge]);

  return { jobs, setJobs, jobErrors, setJobErrors, pendingContent, thinking, statusText, generatingIds,
    patchJob, finishJob, send, submit, wsStatus, waitUntilReady, ignoreByConvRef, imageAbortRef, imageBaselineRef, httpJobsRef };
}
