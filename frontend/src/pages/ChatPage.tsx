import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Drawer, SwipeableDrawer, IconButton, Tooltip, useMediaQuery, useTheme } from '@mui/material';
import { List as ListIcon, FileArrowDown, MagnifyingGlass, WarningCircle, SquareHalf } from '@phosphor-icons/react';
import { headerIconBtnSx } from '@/theme/effects';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { ChatSidebar, ConversationItem } from '@/features/chat/ChatSidebar';
import { AccountMenu } from '@/components/AccountMenu';
import { ColorModeToggle } from '@/components/ColorModeToggle';
import { ChatWindow, DisplayMessage } from '@/features/chat/ChatWindow';
import { DesignCanvas, findStudioCanvas } from '@/features/chat/DesignCanvas';
import { MessageInput } from '@/features/chat/MessageInput';
import { AttachmentInfo } from '@/features/chat/DocumentAttachment';
import { lastChatImageUrl } from '@/features/chat/chatImages';
import { useWebSocket } from '@/hooks/useWebSocket';
import { apiFetch, apiFormData, downloadBlob, exportDocx as requestDocx } from '@/api/client';
import { useAuthStore } from '@/stores/authStore';
import { CHAT_COL } from '@/features/chat/chatColumn';
import { QuotaNotice } from '@/features/chat/QuotaNotice';
import { ClarifyCard } from '@/features/chat/ClarifyCard';
import { isClarifyMessage, isClarifyReply, splitSearch } from '@/features/chat/clarify';
import { collectDialogueSources, parseSources, sourcesLabel } from '@/features/chat/sources';
import { SourcesRail, SourcesSheet } from '@/features/chat/SourcesPanel';
import { dropJob, emptyJob, mergeRemoteJobs, upsertJob, type LiveJobPatch, type LiveJobsMap } from '@/features/chat/liveJobs';
import { DialogueJumpChip, DialogueJumpSheet } from '@/features/chat/DialogueJumpSheet';
import { MIN_DIALOGUE_QUESTIONS, type DialogueJumpFn } from '@/features/chat/dialogueNav';
import { BRAND_NAME, NEW_CHAT_TITLE } from '@/brand';
import { applyPageMeta } from '@/seo';

// Same-origin by default so it goes through the reverse proxy (nginx routes
// /chat/ws to the backend — see frontend/nginx.conf) instead of a baked-in
// public IP. VITE_WS_URL stays as an explicit override for local dev, where
// the frontend (5173) and backend (8000) run on different ports directly.
const WS_URL =
  import.meta.env.VITE_WS_URL ||
  (import.meta.env.PROD
    ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
    : 'ws://127.0.0.1:8000');

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

export default function ChatPage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const isWide = useMediaQuery(theme.breakpoints.up('lg'));
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sourcesSheetOpen, setSourcesSheetOpen] = useState(false);
  const [dialogueSheetOpen, setDialogueSheetOpen] = useState(false);
  const [mobileCanvasOpen, setMobileCanvasOpen] = useState(false);
  const dialogueJumpRef = useRef<DialogueJumpFn | null>(null);
  const [sourceMessageId, setSourceMessageId] = useState<string | undefined>();
  const [activeConvId, setActiveConvId] = useState<string | undefined>();
  const [searchParams, setSearchParams] = useSearchParams();
  const openNewChat = searchParams.get('new') === '1';

  useEffect(() => {
    applyPageMeta({
      title: `Чат – ${BRAND_NAME}`,
      canonicalPath: '/chat',
      noindex: true,
    });
  }, []);
  const [displayMessages, setDisplayMessages] = useState<DisplayMessage[]>([]);
  const [forcedEditUrl, setForcedEditUrl] = useState<string | null>(null);
  const [skipLastImage, setSkipLastImage] = useState(false);
  const [imageModeRequest, setImageModeRequest] = useState(0);
  const [jobs, setJobs] = useState<LiveJobsMap>({});
  const [jobErrors, setJobErrors] = useState<Record<string, string>>({});
  const live = activeConvId ? jobs[activeConvId] : undefined;
  const thinking = Boolean(live?.thinking);
  const statusText = live?.statusText || '';
  const pendingContent = useMemo(() => ({
    convId: live?.convId || activeConvId,
    userText: live?.userText || '',
    text: live?.text || '',
    thinking,
    file: live?.file,
    reasoning: live?.reasoning,
    search: live?.search,
  }), [live, activeConvId, thinking]);
  const generatingIds = Object.keys(jobs).filter((id) => jobs[id]?.thinking);
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: () => apiFetch('/models'), staleTime: 10_000 });
  const isStudio = models?.selected === 'studio';
  const isDocgen = models?.selected === 'docgen';
  const canvasSource = useMemo(() => findStudioCanvas(displayMessages), [displayMessages]);
  const patchJob = (convId: string | undefined, patch: LiveJobPatch) => {
    if (!convId) return;
    setJobs((prev) => upsertJob(prev, convId, patch));
  };
  const finishJob = (convId?: string) => {
    if (!convId) return;
    delete imageBaselineRef.current[convId];
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
  const [exporting, setExporting] = useState(false);
  // Id of the assistant message currently being replaced by a regenerate — hidden
  // from `base` below so the old answer doesn't flash alongside the new one while
  // the server hasn't confirmed the deletion/replacement yet.
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const token = useAuthStore((s) => s.accessToken);
  const queryClient = useQueryClient();

  const { data: conversations = [], isFetched: conversationsFetched } = useQuery<ConversationItem[]>({
    queryKey: ['conversations'],
    queryFn: () => apiFetch('/conversations'),
    staleTime: 5_000,
  });

  const { data: messages = [] } = useQuery<{ id: string; role: string; content: string; attachment?: AttachmentInfo; search?: { query: string; summary: string }[] }[]>({
    queryKey: ['messages', activeConvId],
    queryFn: () => apiFetch(`/conversations/${activeConvId}/messages`),
    enabled: !!activeConvId,
    staleTime: 3_000,
    refetchInterval: thinking && activeConvId ? 2000 : false,
  });

  // Restore the latest/active chat after a page reload instead of showing an
  // empty home screen while its messages and document cards still exist.
  useEffect(() => {
    if (openNewChat) return;
    if (!activeConvId && conversations.length) {
      const restored = conversations.find((conversation) => conversation.is_active) || conversations[0];
      setActiveConvId(restored.id);
    }
  }, [activeConvId, conversations, openNewChat]);

  useEffect(() => {
    if (activeConvId && messages) {
      const base = messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .filter((m) => m.id !== regeneratingId)
        .map((m) => ({
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          attachment: m.attachment,
          search: m.search,
        }));

      if (pendingContent.convId === activeConvId) {
        const lastBaseUser = [...base].reverse().find((m) => m.role === 'user');
        const imageBaseline = activeConvId ? imageBaselineRef.current[activeConvId] : undefined;
        const persistedNewUser = Boolean(
          pendingContent.userText
          && imageBaseline
          && base.some((message) => (
            message.role === 'user'
            && message.content === pendingContent.userText
            && !imageBaseline.has(message.id)
          )),
        );
        const withUser =
          pendingContent.userText && lastBaseUser?.content !== pendingContent.userText
            ? [...base, { id: 'pending-user', role: 'user' as const, content: pendingContent.userText }]
            : pendingContent.userText && imageBaseline && !persistedNewUser
              ? [...base, { id: 'pending-user', role: 'user' as const, content: pendingContent.userText }]
              : base;

        const lastBaseAssistant = [...withUser].reverse().find((m) => m.role === 'assistant');
        const pendingClarify = splitSearch(pendingContent.search).questions.length > 0;
        const lastHasClarify = isClarifyMessage(
          lastBaseAssistant && 'search' in lastBaseAssistant ? lastBaseAssistant.search : undefined,
        );
        const withAssistant =
          (pendingContent.text || pendingClarify) &&
          !lastHasClarify &&
          lastBaseAssistant?.content !== pendingContent.text
            ? [
                ...withUser,
                {
                  id: 'pending-assistant',
                  role: 'assistant' as const,
                  content: pendingContent.text,
                  reasoning: pendingContent.reasoning,
                  search: pendingContent.search,
                },
              ]
            : withUser;

        const lastAssistant = withAssistant[withAssistant.length - 1];
        const withFile = pendingContent.file
          ? lastAssistant?.role === 'assistant'
            ? withAssistant.map((message, index) =>
                index === withAssistant.length - 1 ? { ...message, file: pendingContent.file } : message,
              )
            : [
                ...withAssistant,
                {
                  id: 'pending-file',
                  role: 'assistant' as const,
                  content: `Файл готов: ${pendingContent.file.filename}`,
                  file: pendingContent.file,
                  ...(withAssistant === withUser
                    ? { reasoning: pendingContent.reasoning, search: pendingContent.search }
                    : {}),
                },
              ]
          : withAssistant;

        const lastUserIndex = [...withFile].map((message) => message.role).lastIndexOf('user');
        const hasAssistantAfterUser = lastUserIndex >= 0
          && withFile.slice(lastUserIndex + 1).some((message) => message.role === 'assistant');
        const jobError = activeConvId ? jobErrors[activeConvId] : undefined;
        const withError = jobError && !hasAssistantAfterUser && !pendingContent.thinking
          ? [...withFile, { id: `job-err-${activeConvId}`, role: 'assistant' as const, content: jobError }]
          : withFile;
        if (jobError && hasAssistantAfterUser) {
          setJobErrors((prev) => {
            if (!activeConvId || !prev[activeConvId]) return prev;
            const next = { ...prev };
            delete next[activeConvId];
            return next;
          });
        }

        setDisplayMessages(withError);

        // If the socket reconnected during a long analysis, polling may see the
        // persisted assistant answer before a new `done` event can arrive.
        const pendingUserIndex = pendingContent.userText
          ? base.map((message) => message.role === 'user' ? message.content : '').lastIndexOf(pendingContent.userText)
          : -1;
        const recoveredAnswer = imageBaseline
          ? base.some((message) => message.role === 'assistant' && !imageBaseline.has(message.id))
          : pendingUserIndex >= 0
            && base.slice(pendingUserIndex + 1).some((message) => message.role === 'assistant');
        if (pendingContent.thinking && recoveredAnswer) {
          setRegeneratingId(null);
          finishJob(activeConvId);
          if (activeConvId) delete imageBaselineRef.current[activeConvId];
        }

        // Once the assistant response has been persisted to the server, drop the pending copy.
        const lastAttachment =
          lastBaseAssistant && 'attachment' in lastBaseAssistant ? lastBaseAssistant.attachment : undefined;
        if (pendingContent.text && lastBaseAssistant?.content === pendingContent.text) {
          const persistedCanvas = Boolean(lastAttachment?.url);
          if (persistedCanvas || !pendingContent.file) {
            setJobs((prev) => dropJob(prev, activeConvId));
          } else {
            patchJob(activeConvId, { text: '', userText: '', thinking: false, file: pendingContent.file });
          }
        } else if (!pendingContent.thinking && lastAttachment?.url && pendingContent.file) {
          setJobs((prev) => dropJob(prev, activeConvId));
        }
      } else {
        setDisplayMessages(base);
      }
    }
  }, [activeConvId, messages, pendingContent, regeneratingId, jobErrors]);

  const createMutation = useMutation({
    mutationFn: () => apiFetch('/conversations', { method: 'POST', body: JSON.stringify({ title: NEW_CHAT_TITLE }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['conversations'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiFetch(`/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      if (activeConvId === deletedId) {
        setActiveConvId(undefined);
        setDisplayMessages([]);
      }
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiFetch(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['conversations'] }),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => apiFetch(`/conversations/${id}/activate`, { method: 'POST' }),
  });

  const { messages: wsMessages, send, status: wsStatus, waitUntilReady } = useWebSocket(WS_URL, token);
  const processedRef = useRef<Set<string>>(new Set());
  const ignoreByConvRef = useRef<Set<string>>(new Set());
  const openingNewRef = useRef(false);
  const imageAbortRef = useRef<AbortController | null>(null);
  const imageBaselineRef = useRef<Record<string, Set<string>>>({});

  useEffect(() => {
    if (wsStatus === 'open' && activeConvId) {
      queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
    }
  }, [wsStatus, activeConvId, queryClient]);

  useEffect(() => {
    apiFetch('/chat/jobs')
      .then((data) => {
        setJobs((prev) => mergeRemoteJobs(prev, data.jobs));
      })
      .catch(() => undefined);
  }, [wsStatus]);

  useEffect(() => {
    wsMessages.forEach((msg, idx) => {
      const key = `${idx}-${msg.type}`;
      if (processedRef.current.has(key)) return;
      processedRef.current.add(key);

      const convId = (msg.payload?.conversation_id as string | undefined) || undefined;
      if (convId && ignoreByConvRef.current.has(convId) && msg.type !== 'stopped' && msg.type !== 'done' && msg.type !== 'error') {
        return;
      }

      if (msg.type === 'jobs') {
        setJobs((prev) => mergeRemoteJobs(prev, msg.payload.jobs));
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
        if (!activeConvId) setActiveConvId(convId);
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
        const doneConvId = convId || pendingContent.convId;
        if (doneConvId) ignoreByConvRef.current.delete(doneConvId);
        if (doneConvId === activeConvId) setRegeneratingId(null);
        finishJob(doneConvId);
        if (doneConvId) {
          queryClient.invalidateQueries({ queryKey: ['messages', doneConvId] });
        }
        queryClient.invalidateQueries({ queryKey: ['conversations'] });
        queryClient.invalidateQueries({ queryKey: ['subscription'] });
      }
      if (msg.type === 'stopped') {
        const stoppedId = convId || pendingContent.convId;
        if (stoppedId) ignoreByConvRef.current.delete(stoppedId);
        patchJob(stoppedId, { thinking: false, statusText: '' });
      }
      if (msg.type === 'error') {
        const errConvId = convId || pendingContent.convId || activeConvId;
        if (errConvId) ignoreByConvRef.current.delete(errConvId);
        if (errConvId === activeConvId) setRegeneratingId(null);
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
  }, [wsMessages, activeConvId, queryClient, pendingContent.convId]);

  useEffect(() => {
    setForcedEditUrl(null);
    setSkipLastImage(false);
  }, [activeConvId]);

  useEffect(() => {
    if (isStudio && isMobile && canvasSource) setMobileCanvasOpen(true);
  }, [isStudio, isMobile, canvasSource?.url, canvasSource?.html, canvasSource?.name]);

  const handleSelect = async (id: string) => {
    await activateMutation.mutateAsync(id);
    setActiveConvId(id);
    setDisplayMessages([]);
    setSourceMessageId(undefined);
    setSourcesSheetOpen(false);
    if (isMobile) setSidebarOpen(false);
  };

  const handleCreate = async () => {
    const blank = conversations.find(
      (conversation) =>
        conversation.message_count === 0 && /^(Новый чат|Новая беседа|Беседа #\d+)$/.test(conversation.title),
    );
    if (blank) {
      if (blank.id !== activeConvId) {
        await activateMutation.mutateAsync(blank.id);
        setActiveConvId(blank.id);
        setDisplayMessages([]);
      }
      setSourceMessageId(undefined);
      setSourcesSheetOpen(false);
      if (isMobile) setSidebarOpen(false);
      return;
    }
    const conv = await createMutation.mutateAsync();
    setActiveConvId(conv.id);
    setDisplayMessages([]);
    setSourceMessageId(undefined);
    setSourcesSheetOpen(false);
    if (isMobile) setSidebarOpen(false);
  };

  useEffect(() => {
    if (!openNewChat || !conversationsFetched || openingNewRef.current) return;
    openingNewRef.current = true;
    void handleCreate().finally(() => {
      setSearchParams({}, { replace: true });
      openingNewRef.current = false;
    });
  }, [openNewChat, conversationsFetched]);

  const handleSend = async (rawText: string, files: File[] = [], mode: 'chat' | 'image' = 'chat'): Promise<boolean> => {
    const text = rawText || (files.length ? 'Проанализируй прикреплённые файлы.' : '');
    if (!text) return false;
    let optimisticId: string | undefined;
    let conversationId = activeConvId;
    try {
      if (!conversationId) {
        const conversation = await createMutation.mutateAsync();
        conversationId = conversation.id;
        setActiveConvId(conversationId);
      }
      if (!conversationId) throw new Error('не удалось создать беседу');
      ignoreByConvRef.current.delete(conversationId);
      setJobErrors((prev) => {
        if (!prev[conversationId!]) return prev;
        const next = { ...prev };
        delete next[conversationId!];
        return next;
      });
      imageBaselineRef.current[conversationId] = new Set(displayMessages.map((message) => message.id));

      // Resolve the conversation before touching the optimistic UI. This keeps
      // a newly uploaded file and its prompt in the same stable chat instead of
      // briefly falling back to the empty state during the id transition.
      optimisticId = `pending-user-${Date.now()}`;
      setDisplayMessages((current) => [
        ...current,
        { id: optimisticId!, role: 'user' as const, content: text },
      ]);
      patchJob(conversationId, {
        thinking: true,
        userText: text,
        text: '',
        statusText: files.length ? 'Готовлю файлы' : 'Думаю',
        file: undefined,
        reasoning: undefined,
        search: undefined,
      });

      if (mode === 'image') {
        const imageFiles = files.filter((file) => file.type.startsWith('image/'));
        const sourceUrl = imageFiles.length
          ? undefined
          : (forcedEditUrl || (!skipLastImage ? lastChatImageUrl(displayMessages) : undefined));
        patchJob(conversationId, {
          statusText: imageFiles.length || sourceUrl ? 'Меняю изображение' : 'Рисую изображение',
        });
        const abort = new AbortController();
        imageAbortRef.current = abort;
        const timeoutMs = 210_000;
        let data: { url?: string; kind?: string; message?: { id?: string } };
        try {
          if (imageFiles.length) {
            const formData = new FormData();
            formData.append('prompt', text);
            formData.append('conversation_id', conversationId);
            imageFiles.forEach((file) => formData.append('files', file));
            const res = await apiFormData('/media/images/edit', formData, { signal: abort.signal, timeoutMs });
            if (!res.ok) {
              const errData = await res.json().catch(() => ({}));
              throw new Error(errData.detail || errData.message || 'не удалось изменить изображение');
            }
            data = await res.json();
          } else {
            data = await apiFetch('/media/images/generate', {
              method: 'POST',
              body: JSON.stringify({
                prompt: text,
                conversation_id: conversationId,
                ...(sourceUrl ? { source_urls: [sourceUrl] } : {}),
              }),
              signal: abort.signal,
              timeoutMs,
            });
          }
        } finally {
          if (imageAbortRef.current === abort) imageAbortRef.current = null;
        }
        const caption = data.kind === 'edit' ? 'Отредактированное изображение' : 'Сгенерированное изображение';
        if (data.url) {
          setDisplayMessages((current) => {
            const withoutPending = current.filter((message) => message.id !== optimisticId);
            if (withoutPending.some((message) => message.content.includes(data.url!))) return withoutPending;
            return [
              ...withoutPending,
              { id: optimisticId!, role: 'user' as const, content: text },
              { id: data.message?.id || `img-${Date.now()}`, role: 'assistant' as const, content: `![${caption}](${data.url})` },
            ];
          });
        }
        setForcedEditUrl(null);
        setSkipLastImage(false);
        finishJob(conversationId);
        queryClient.invalidateQueries({ queryKey: ['messages', conversationId] });
        queryClient.invalidateQueries({ queryKey: ['conversations'] });
        return true;
      }
      if (files.length) {
        const uploaded = await handleFileUpload(files, conversationId, true);
        if (!uploaded) throw new Error('не удалось загрузить вложения');
        patchJob(conversationId, { statusText: 'Смотрю файлы' });
      }
      // Long multi-file uploads can outlive a WS reconnect. Wait until auth
      // completes before treating the send as delivered.
      const ready = await waitUntilReady(45000);
      if (!ready) throw new Error('нет соединения с сервером, попробуйте ещё раз');
      send('message', { content: text, conversation_id: conversationId });
      return true;
    } catch (error: any) {
      const targetConvId = activeConvId || conversationId;
      finishJob(targetConvId);
      queryClient.invalidateQueries({ queryKey: ['messages', targetConvId] });
      const aborted = /остановлен|ожидания/i.test(error?.message || '');
      setDisplayMessages((current) => [
        ...current.filter((message) => message.id !== optimisticId),
        {
          id: `err-${Date.now()}`,
          role: 'assistant' as const,
          content: aborted
            ? (error?.message?.includes('ожидания')
              ? 'Картинка рисуется слишком долго. Попробуйте ещё раз или упростите описание.'
              : 'Генерация остановлена.')
            : `Не удалось отправить сообщение: ${error?.message || 'ошибка соединения'}`,
        },
      ]);
      return false;
    }
  };

  const handleStop = () => {
    imageAbortRef.current?.abort();
    if (!activeConvId) return;
    ignoreByConvRef.current.add(activeConvId);
    finishJob(activeConvId);
    send('stop', { conversation_id: activeConvId });
    queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
  };

  const handleRegenerate = () => {
    if (!activeConvId) return;
    ignoreByConvRef.current.delete(activeConvId);
    imageBaselineRef.current[activeConvId] = new Set(displayMessages.map((m) => m.id));
    const lastUser = [...displayMessages].reverse().find((m) => m.role === 'user');
    const lastAssistant = [...displayMessages].reverse().find((m) => m.role === 'assistant');
    if (lastAssistant) setRegeneratingId(lastAssistant.id);
    patchJob(activeConvId, {
      thinking: true,
      userText: lastUser?.content || '',
      text: '',
      statusText: 'Думаю',
      file: undefined,
      reasoning: undefined,
      search: undefined,
    });
    send('regenerate', { conversation_id: activeConvId });
  };

  const handleEditMessage = async (messageId: string, newContent: string) => {
    if (!activeConvId) return;
    const idx = displayMessages.findIndex((m) => m.id === messageId);
    if (idx === -1) return;
    try {
      await apiFetch(`/conversations/${activeConvId}/messages/truncate`, {
        method: 'POST',
        body: JSON.stringify({ keep_count: idx }),
      });
      setDisplayMessages((m) => m.slice(0, idx));
      queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
      handleSend(newContent);
    } catch (e: any) {
      setDisplayMessages((m) => [...m, { id: `err-${Date.now()}`, role: 'assistant', content: `Не удалось изменить сообщение: ${e.message}` }]);
    }
  };

  const handleRemoveAttachment = async (messageId: string) => {
    const msg = displayMessages.find((m) => m.id === messageId && m.attachment);
    if (!msg?.attachment) return;
    try {
      await apiFetch(`/documents/${encodeURIComponent(msg.attachment.name)}`, { method: 'DELETE' });
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    } catch (e: any) {
      setDisplayMessages((m) => [
        ...m,
        { id: `err-${Date.now()}`, role: 'assistant', content: `Не удалось удалить вложение из контекста: ${e.message}` },
      ]);
    }
  };

  async function handleFileUpload(files: File[], conversationId: string, keepThinking = false): Promise<boolean> {
    if (!files.length) return true;
    let successCount = 0;
    const batch = files.map((file, index) => ({ file, uploadId: `upload-${Date.now()}-${index}` }));
    setDisplayMessages((m) => [
      ...m,
      ...batch.map(({ file, uploadId }) => ({
        id: uploadId,
        role: 'user' as const,
        content: '',
        attachment: { name: file.name, size: file.size, status: 'uploading' as const, type: file.type.startsWith('image/') ? 'image' as const : 'document' as const },
      })),
    ]);
    patchJob(conversationId, { thinking: true, statusText: `Загружаю файлы: 0 из ${batch.length}` });
    // Persist in selection order so cards never reshuffle after a refresh.
    // There is no artificial file-count limit; progress stays visible for long batches.
    const UPLOAD_CONCURRENCY = 3;
    const UPLOAD_TIMEOUT_MS = isDocgen ? 600_000 : 180_000;
    let lastError: string | undefined;
    let finished = 0;

    const uploadOne = async (index: number) => {
      const { file, uploadId } = batch[index];
      const formData = new FormData();
      formData.append('file', file);
      formData.append('conversation_id', conversationId!);
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      try {
        const res = await apiFormData('/documents', formData, { signal: controller.signal });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errMsg = errData.detail || errData.message || (res.status === 413 ? 'Файл слишком большой для загрузки' : `HTTP ${res.status}`);
          throw new Error(errMsg);
        }
        const data = await res.json();
        successCount += 1;
        const persisted = data.message as { id: string; role: string; content: string; attachment?: AttachmentInfo } | undefined;
        setDisplayMessages((current) => current.map((message) => message.id === uploadId ? {
          id: persisted?.id ?? message.id,
          role: 'user' as const,
          content: '',
          attachment: persisted?.attachment ?? { ...message.attachment!, status: 'done' },
        } : message));
      } catch (err: any) {
        lastError = err?.name === 'AbortError' ? 'превышено время загрузки файла' : (err?.message || 'ошибка загрузки');
        setDisplayMessages((current) => current.map((message) => message.id === uploadId
          ? { ...message, attachment: { ...message.attachment!, status: 'error' } }
          : message));
      } finally {
        window.clearTimeout(timer);
        finished += 1;
        patchJob(conversationId, { statusText: `Загружаю файлы: ${finished} из ${batch.length}` });
      }
    };

    let cursor = 0;
    const workers = Array.from({ length: Math.min(UPLOAD_CONCURRENCY, batch.length) }, async () => {
      while (cursor < batch.length) {
        const index = cursor;
        cursor += 1;
        await uploadOne(index);
      }
    });
    await Promise.all(workers);
    queryClient.invalidateQueries({ queryKey: ['messages', conversationId] });
    queryClient.invalidateQueries({ queryKey: ['conversations'] });
    if (!keepThinking) {
      patchJob(conversationId, { thinking: false, statusText: '' });
    }
    if (successCount === 0 && lastError) {
      throw new Error(lastError);
    }
    return successCount > 0;
  }

  const exportDocx = async () => {
    const lastAssistant = [...displayMessages].reverse().find((m) => m.role === 'assistant' && !isClarifyMessage(m.search));
    if (!lastAssistant?.content?.trim()) return;
    setExporting(true);
    try {
      const blob = await requestDocx(lastAssistant.content);
      downloadBlob(blob, 'response.docx');
    } catch (e: any) {
      setDisplayMessages((m) => [...m, { id: `err-${Date.now()}`, role: 'assistant', content: `Не удалось экспортировать в DOCX: ${e.message}` }]);
    } finally {
      setExporting(false);
    }
  };

  const allSources = useMemo(() => collectDialogueSources(displayMessages), [displayMessages]);
  const questionTicks = useMemo(
    () =>
      displayMessages
        .filter((message) => !isClarifyMessage(message.search))
        .filter((message) => message.role === 'user' && !isClarifyReply(message.content) && message.content.trim())
        .map((message) => ({ id: message.id, label: message.content })),
    [displayMessages]
  );
  const focusedSourceMessage = displayMessages.find(
    (message) => message.id === sourceMessageId && parseSources(splitSearch(message.search).sources).length,
  );
  const focusedSources = useMemo(
    () => (focusedSourceMessage ? parseSources(splitSearch(focusedSourceMessage.search).sources) : allSources),
    [allSources, focusedSourceMessage?.id, focusedSourceMessage?.search],
  );
  const latestSourceId = [...displayMessages].reverse().find((message) => parseSources(splitSearch(message.search).sources).length)?.id;
  const clarifyQuestions = useMemo(() => {
    if (thinking) return [];
    const last = displayMessages[displayMessages.length - 1];
    if (!last || last.role !== 'assistant') return [];
    return splitSearch(last.search).questions;
  }, [displayMessages, thinking]);

  useEffect(() => {
    setSourceMessageId(undefined);
  }, [latestSourceId]);

  useEffect(() => {
    setDialogueSheetOpen(false);
  }, [activeConvId]);

  const openSources = (messageId: string) => {
    if (isWide) {
      setSourceMessageId((current) => (current === messageId ? undefined : messageId));
      return;
    }
    setSourceMessageId(messageId);
    setSourcesSheetOpen(true);
  };

  return (
    <Box
      sx={{
        height: '100%',
        display: 'flex',
        overflow: 'hidden',
      }}
    >
      {isMobile ? (
        <SwipeableDrawer
          anchor="left"
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onOpen={() => setSidebarOpen(true)}
          PaperProps={{
            sx: {
              width: 280,
              maxWidth: '85%',
              bgcolor: 'background.default',
              backgroundImage: 'none',
              boxShadow: 'none',
            },
          }}
          BackdropProps={{
            sx: { bgcolor: 'var(--bt-scrim)' },
          }}
        >
          <ChatSidebar
            conversations={conversations}
            activeId={activeConvId}
            onSelect={handleSelect}
            onCreate={handleCreate}
            onDelete={(id) => {
              send('stop', { conversation_id: id });
              finishJob(id);
              deleteMutation.mutate(id);
            }}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            onClose={() => setSidebarOpen(false)}
            generatingIds={generatingIds}
          />
        </SwipeableDrawer>
      ) : (
        <Box sx={{ flexShrink: 0, height: '100%', overflow: 'hidden' }}>
          <ChatSidebar
            conversations={conversations}
            activeId={activeConvId}
            onSelect={handleSelect}
            onCreate={handleCreate}
            onDelete={(id) => {
              send('stop', { conversation_id: id });
              finishJob(id);
              deleteMutation.mutate(id);
            }}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            generatingIds={generatingIds}
          />
        </Box>
      )}

      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', overflow: 'hidden' }}>
      <Box
        sx={{
          ...(isStudio && !isMobile
            ? { width: { md: 400, lg: 440, xl: 480 }, flexShrink: 0 }
            : { flex: 1 }),
          minWidth: 0,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            zIndex: 4,
            pointerEvents: 'none',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 0.75,
            px: { xs: 1.5, sm: 2 },
            pt: { xs: 'max(10px, env(safe-area-inset-top))', sm: 1.5 },
            pb: 3,
            background: 'linear-gradient(180deg, var(--bt-fade) 0%, var(--bt-fade-mid) 62%, transparent 100%)',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', pointerEvents: 'auto' }}>
            {isMobile && (
              <IconButton onClick={() => setSidebarOpen(true)} sx={headerIconBtnSx} aria-label="Открыть список бесед">
                <ListIcon size={22} weight="bold" />
              </IconButton>
            )}
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, pointerEvents: 'auto' }}>
            {!isWide && allSources.length > 0 && (
              <Tooltip title={sourcesLabel(allSources.length)}>
                <IconButton
                  onClick={() => {
                    setSourceMessageId(undefined);
                    setSourcesSheetOpen(true);
                  }}
                  sx={headerIconBtnSx}
                  aria-label={sourcesLabel(allSources.length)}
                >
                  <MagnifyingGlass size={22} weight="bold" />
                </IconButton>
              </Tooltip>
            )}
            {isStudio && isMobile && (
              <Tooltip title="Открыть холст">
                <IconButton
                  onClick={() => setMobileCanvasOpen(true)}
                  sx={{
                    ...headerIconBtnSx,
                    width: 'auto',
                    px: 1.2,
                    gap: 0.65,
                    borderColor: canvasSource || thinking ? 'var(--bt-line)' : 'var(--bt-hairline)',
                  }}
                  aria-label="Открыть холст"
                >
                  <SquareHalf size={20} weight="bold" />
                  <Box component="span" sx={{ fontSize: '0.8125rem', fontWeight: 600, letterSpacing: '-0.02em' }}>
                    Холст
                  </Box>
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title="Экспортировать ответ в DOCX">
              <span>
                <IconButton
                  onClick={exportDocx}
                  disabled={exporting || !displayMessages.some((m) => m.role === 'assistant')}
                  sx={headerIconBtnSx}
                  aria-label="Экспортировать ответ в DOCX"
                >
                  <FileArrowDown size={22} weight="bold" />
                </IconButton>
              </span>
            </Tooltip>
            <ColorModeToggle />
            <AccountMenu />
          </Box>
        </Box>
        {(wsStatus === 'closed' || wsStatus === 'error') && (
          <Box
            sx={{
              position: 'absolute',
              top: { xs: 58, sm: 62 },
              left: 0,
              right: 0,
              zIndex: 4,
              display: 'flex',
              justifyContent: 'center',
              px: 2,
              pointerEvents: 'none',
            }}
            role="status"
            aria-live="polite"
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 0.75,
                px: 1.25,
                py: 0.6,
                borderRadius: '999px',
                bgcolor: 'var(--bt-panel)',
                border: '1px solid var(--bt-hairline)',
                color: 'text.secondary',
                fontSize: '0.8125rem',
                pointerEvents: 'auto',
              }}
            >
              <WarningCircle size={16} weight="bold" />
              {wsStatus === 'closed' && 'Соединение потеряно. Переподключаемся...'}
              {wsStatus === 'error' && 'Ошибка соединения. Переподключаемся...'}
            </Box>
          </Box>
        )}
        <ChatWindow
          key={activeConvId || 'new'}
          messages={displayMessages}
          thinking={thinking}
          statusText={statusText}
          liveReasoning={pendingContent.convId === activeConvId ? pendingContent.reasoning : undefined}
          onRemoveAttachment={handleRemoveAttachment}
          onRegenerate={handleRegenerate}
          onEditMessage={handleEditMessage}
          onEditImage={
            isStudio || isDocgen
              ? undefined
              : (url) => {
                  setForcedEditUrl(url);
                  setSkipLastImage(false);
                  setImageModeRequest((value) => value + 1);
                }
          }
          onSuggestion={handleSend}
          hasCanvas={Boolean(canvasSource)}
          activeSourceId={sourceMessageId}
          onOpenSources={openSources}
          clarifyDocked={clarifyQuestions.length > 0}
          jumpRef={dialogueJumpRef}
          splitPane={Boolean(isStudio && !isMobile)}
        />
        <Box
          sx={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 3,
            pointerEvents: 'none',
            pt: clarifyQuestions.length ? 2 : 2.5,
            background: 'linear-gradient(180deg, transparent 0%, var(--bt-fade) 42%, var(--bt-fade-solid) 78%)',
          }}
        >
          <Box sx={{ ...CHAT_COL, ...(isStudio && !isMobile ? { maxWidth: '100%', px: 1.75 } : {}), position: 'relative', pb: { xs: 'max(12px, env(safe-area-inset-bottom))', md: 2 }, pointerEvents: 'auto' }}>
            {isMobile && questionTicks.length >= MIN_DIALOGUE_QUESTIONS && (
              <Box
                sx={{
                  position: 'absolute',
                  right: { xs: 2, sm: 3 },
                  top: 0,
                  transform: 'translateY(calc(-100% - 10px))',
                  zIndex: 4,
                }}
              >
                <DialogueJumpChip count={questionTicks.length} onClick={() => setDialogueSheetOpen(true)} />
              </Box>
            )}
            <QuotaNotice />
            {clarifyQuestions.length > 0 && (
              <Box sx={{ mb: 1.5 }}>
                <ClarifyCard
                  key={clarifyQuestions.map((question) => question.prompt).join('|')}
                  questions={clarifyQuestions}
                  onSubmit={(text) => {
                    void handleSend(text);
                  }}
                />
              </Box>
            )}
            <MessageInput
              onSend={handleSend}
              disabled={thinking}
              isGenerating={thinking}
              onStop={handleStop}
              editSourceUrl={forcedEditUrl || (!skipLastImage ? lastChatImageUrl(displayMessages) : null)}
              onClearEditSource={() => {
                setForcedEditUrl(null);
                setSkipLastImage(true);
              }}
              imageModeRequest={imageModeRequest}
            />
          </Box>
        </Box>
        {isWide && allSources.length > 0 && !isStudio && (
          <Box
            sx={{
              display: { xs: 'none', lg: 'block' },
              position: 'absolute',
              top: 80,
              right: { lg: 20, xl: 28 },
              width: 268,
              zIndex: 2,
              pointerEvents: 'none',
              '& > *': { pointerEvents: 'auto' },
            }}
          >
            <SourcesRail
              key={sourceMessageId || 'all'}
              sources={focusedSources}
              scoped={Boolean(focusedSourceMessage)}
              allCount={allSources.length}
              onShowAll={() => setSourceMessageId(undefined)}
            />
          </Box>
        )}
      </Box>
      {isStudio && !isMobile && (
        <DesignCanvas source={canvasSource} thinking={thinking} statusText={statusText} />
      )}
      </Box>
      {isStudio && isMobile && (
        <Drawer
          anchor="bottom"
          open={mobileCanvasOpen}
          onClose={() => setMobileCanvasOpen(false)}
          ModalProps={{ keepMounted: true }}
          PaperProps={{
            sx: {
              height: 'min(92dvh, 100%)',
              maxHeight: '100%',
              bgcolor: 'background.default',
              backgroundImage: 'none',
              borderTopLeftRadius: '18px',
              borderTopRightRadius: '18px',
              overflow: 'hidden',
            },
          }}
        >
          <DesignCanvas
            source={canvasSource}
            thinking={thinking}
            statusText={statusText}
            compact
            onClose={() => setMobileCanvasOpen(false)}
          />
        </Drawer>
      )}
      <DialogueJumpSheet
        open={isMobile && dialogueSheetOpen}
        questions={questionTicks}
        onClose={() => setDialogueSheetOpen(false)}
        onOpen={() => setDialogueSheetOpen(true)}
        onJump={(id) => dialogueJumpRef.current?.(id)}
      />
      <SourcesSheet
        sources={focusedSources}
        scoped={Boolean(focusedSourceMessage)}
        allCount={allSources.length}
        onShowAll={() => setSourceMessageId(undefined)}
        open={sourcesSheetOpen}
        onClose={() => setSourcesSheetOpen(false)}
        onOpen={() => setSourcesSheetOpen(true)}
      />
    </Box>
  );
}
