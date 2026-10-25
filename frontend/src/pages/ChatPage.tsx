import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, Snackbar, Alert, Drawer, SwipeableDrawer, IconButton, Tooltip, Menu, MenuItem, ListItemIcon, ListItemText, useMediaQuery, useTheme } from '@mui/material';
import { List as ListIcon, FileArrowDown, MagnifyingGlass, WarningCircle, SquareHalf, Users, ChatsCircle, FolderSimple, DotsThree, Sun, Moon } from '@phosphor-icons/react';
import { useColorMode } from '@/theme/ColorMode';
import { headerGroupBtnSx, headerGroupSx, headerIconBtnSx } from '@/theme/effects';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { replyReveal } from '@/features/chat/replyReveal';
import { ChatSidebar, ConversationItem } from '@/features/chat/ChatSidebar';
import { AccountMenu } from '@/components/AccountMenu';
import { ChatWindow, DisplayMessage } from '@/features/chat/ChatWindow';
import { DesignCanvas, findStudioCanvas } from '@/features/chat/DesignCanvas';
import { MessageInput } from '@/features/chat/MessageInput';
import { adoptNewComposerDraft } from '@/features/chat/useComposerDraft';
import { AttachmentInfo } from '@/features/chat/DocumentAttachment';
import { lastChatImageUrl } from '@/features/chat/chatImages';
import { useChatConnection } from '@/hooks/ChatConnection';
import { apiFetch, apiFormData, apiFormDataProgress, downloadBlob, exportDocx as requestDocx } from '@/api/client';
import { useAuthStore } from '@/stores/authStore';
import { CHAT_COL } from '@/features/chat/chatColumn';
import { QuotaNotice } from '@/features/chat/QuotaNotice';
import { ClarifyCard } from '@/features/chat/ClarifyCard';
import { isClarifyMessage, isClarifyReply, splitSearch } from '@/features/chat/clarify';
import { collectDialogueSources, parseSources, sourcesLabel } from '@/features/chat/sources';
import { SourcesSheet } from '@/features/chat/SourcesPanel';
import { dropJob, emptyJob, mergeRemoteJobs, upsertJob, type LiveJobPatch, type LiveJobsMap } from '@/features/chat/liveJobs';
import { DialogueJumpChip, DialogueJumpSheet } from '@/features/chat/DialogueJumpSheet';
import { MIN_DIALOGUE_QUESTIONS, type DialogueJumpFn } from '@/features/chat/dialogueNav';
import { BRAND_NAME, NEW_CHAT_TITLE } from '@/brand';
import { ShareDialog } from '@/features/chat/ShareDialog';
import { DocumentEditorDialog } from '@/features/editor/DocumentEditor';
import { ConversationFilesDrawer, filesQueryKey, type FilesScope } from '@/features/editor/ConversationFiles';
import { RoomChat } from '@/features/chat/RoomChat';
import { ProjectWorkspace, type ProjectItem, type ProjectSpace } from '@/features/chat/ProjectWorkspace';
import { ProjectContextControl } from '@/features/chat/ProjectContextControl';
import { CloudTaskBar, type CloudTask } from '@/features/chat/CloudTaskBar';
import type { ResultEditRequest } from '@/features/chat/projectResultLinks';
import type { ProjectCitation } from '@/features/chat/EvidenceLink';
import { applyPageMeta } from '@/seo';
import { useVisualViewportHeight } from '@/features/chat/useVisualViewportHeight';
import { lastConversation, rememberConversation } from '@/navigation/chatLocation';

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

function keepLiveUploads(current: DisplayMessage[], derived: DisplayMessage[]): DisplayMessage[] {
  const uploads = current.filter((message) => (
    message.attachment?.status === 'uploading' && !derived.some((item) => item.id === message.id)
  ));
  return uploads.length ? [...derived, ...uploads] : derived;
}

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const openNewChat = searchParams.get('new') === '1';
  const requestedConversation = searchParams.get('c');
  const visualViewportHeight = useVisualViewportHeight();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  // Sources dock beside the reply only when the 768px reading column plus its
  // gutters still fit next to the sidebar and a 292px panel. Narrower screens
  // open them from the header instead of squeezing the text.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sourcesSheetOpen, setSourcesSheetOpen] = useState(false);
  const [chipsHost, setChipsHost] = useState<HTMLElement | null>(null);
  const [dialogueSheetOpen, setDialogueSheetOpen] = useState(false);
  const [mobileCanvasOpen, setMobileCanvasOpen] = useState(false);
  const dialogueJumpRef = useRef<DialogueJumpFn | null>(null);
  const [sourceMessageId, setSourceMessageId] = useState<string | undefined>();
  const [selectionQuote, setSelectionQuote] = useState<{ text: string } | null>(null);
  const [activeConvId, setActiveConvId] = useState<string | undefined>(() => openNewChat ? undefined : requestedConversation || lastConversation());
  const activeConvRef = useRef(activeConvId);
  activeConvRef.current = activeConvId;
  const appliedLocationRef = useRef(requestedConversation);
  const selectionRequestRef = useRef(0);
  const creationQueueRef = useRef<Promise<void>>(Promise.resolve());
  const sendingRef = useRef(new Set<string>());
  const uploadedFilesRef = useRef(new WeakMap<File, Set<string>>());
  const [projectPanel, setProjectPanel] = useState<string | null>(null);
  const [resultEdit, setResultEdit] = useState<ResultEditRequest | null>(null);
  const [projectCitation, setProjectCitation] = useState<ProjectCitation | null>(null);
  const taskEnrollmentRef = useRef({ payload: '', key: '' });
  const lastCloudState = useRef<{ id: string; status: string } | null>(null);
  const [projectOpenError, setProjectOpenError] = useState('');
  const [projectExpanded, setProjectExpanded] = useState(false);
  const projectRequestRef = useRef(0);
  const projectsQuery = useQuery<ProjectItem[]>({ queryKey: ['projects'], queryFn: () => apiFetch('/projects') });

  useEffect(() => {
    applyPageMeta({
      title: `Чат – ${BRAND_NAME}`,
      canonicalPath: '/chat',
      noindex: true,
    });
  }, []);
  const [displayMessages, setDisplayMessages] = useState<DisplayMessage[]>([]);
  const [displayConversationId, setDisplayConversationId] = useState<string | undefined>();
  const [forcedEditUrl, setForcedEditUrl] = useState<string | null>(null);
  const [skipLastImage, setSkipLastImage] = useState(false);
  const [imageModeRequest, setImageModeRequest] = useState(0);
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
  const [exporting, setExporting] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [roomOpenById, setRoomOpenById] = useState<Record<string, boolean>>({});
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesScope, setFilesScope] = useState<FilesScope>('chat');
  const [moreAnchor, setMoreAnchor] = useState<HTMLElement | null>(null);
  // The composer floats over the message list and grows (long drafts, the mode
  // hint under it, the clarify card). Publish its real height so the list's
  // bottom padding and the scroll arrows follow it instead of a fixed guess.
  const composerDockRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const dock = composerDockRef.current;
    const column = dock?.parentElement;
    if (!dock || !column || typeof ResizeObserver === 'undefined') return;
    const publish = () => {
      const height = Math.ceil(dock.getBoundingClientRect().height);
      column.style.setProperty('--bt-composer-h', `${height}px`);
      // The dock already includes its fade strip on top; a small gap is enough.
      column.style.setProperty('--bt-composer-h-pad', `${height + 16}px`);
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(dock);
    return () => observer.disconnect();
  }, []);
  // Empty chat on desktop: the composer sits right under the heading (the question is the
  // centre of the screen) instead of being pinned 370px below it. Same component, no remount.
  const [slotEl, setSlotEl] = useState<HTMLElement | null>(null);
  const [slotTop, setSlotTop] = useState<number | null>(null);
  useLayoutEffect(() => {
    const dock = composerDockRef.current;
    const column = dock?.parentElement;
    if (!slotEl || !dock || !column) {
      setSlotTop(null);
      return;
    }
    const measure = () => {
      const top = slotEl.getBoundingClientRect().top - column.getBoundingClientRect().top;
      const fits = top + dock.getBoundingClientRect().height <= column.getBoundingClientRect().height - 8;
      const next = fits ? top : null;
      setSlotTop((prev) => (prev === next || (prev !== null && next !== null && Math.abs(prev - next) < 0.5) ? prev : next));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(slotEl);
    if (slotEl.parentElement) observer.observe(slotEl.parentElement);
    observer.observe(column);
    // The placeholder can move when the greeting scrolls on a short screen.
    // Keep the parked composer aligned with it, not only when sizes change.
    column.addEventListener('scroll', measure, true);
    return () => { observer.disconnect(); column.removeEventListener('scroll', measure, true); };
  }, [slotEl]);
  const composerInSlot = slotEl !== null && slotTop !== null;
  const colorMode = useColorMode();
  // Id of the assistant message currently being replaced by a regenerate — hidden
  // from `base` below so the old answer doesn't flash alongside the new one while
  // the server hasn't confirmed the deletion/replacement yet.
  const [regeneratingId, setRegeneratingId] = useState<number | null>(null);
  const queryClient = useQueryClient();

  const conversationsQuery = useQuery<ConversationItem[]>({
    queryKey: ['conversations'],
    queryFn: ({ signal }) => apiFetch('/conversations', { signal, timeoutMs: 15000 }),
    staleTime: 5_000,
  });
  const { data: conversations = [], isFetched: conversationsFetched } = conversationsQuery;

  const activeConversation = conversations.find((conversation) => conversation.id === activeConvId);
  const sharedRoom = Boolean(activeConversation?.shared);
  const projectBinding = useQuery<{ project_id: string | null }>({ queryKey: ['project-chat', activeConvId], queryFn: () => apiFetch(`/projects/chat/${activeConvId}`), enabled: !!activeConvId && !sharedRoom });
  const cloudTasks = useQuery<CloudTask[]>({ queryKey: ['computer-tasks'], queryFn: () => apiFetch('/computer/tasks'), enabled: !sharedRoom,
    refetchInterval: query => query.state.data?.some(t => ['queued', 'running'].includes(t.status)) ? 3000 : 15000 });
  const currentCloudTask = cloudTasks.data?.find(task => task.conversation_id === activeConvId && ['queued', 'running'].includes(task.status))
    || cloudTasks.data?.find(task => task.conversation_id === activeConvId);
  useEffect(() => {
    if (!currentCloudTask || !activeConvId) { lastCloudState.current = null; return; }
    const previous = lastCloudState.current;
    if (['queued', 'running'].includes(currentCloudTask.status)) {
      ignoreByConvRef.current.delete(activeConvId);
      patchJob(activeConvId, { thinking: true, userText: currentCloudTask.prompt, statusText: currentCloudTask.progress || 'Задача в очереди' });
    } else if (previous?.id === currentCloudTask.id && ['queued', 'running'].includes(previous.status)) {
      finishJob(activeConvId);
      queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
      queryClient.invalidateQueries({ queryKey: ['project-context', activeConvId] });
    }
    lastCloudState.current = { id: currentCloudTask.id, status: currentCloudTask.status };
  }, [activeConvId, currentCloudTask?.id, currentCloudTask?.status, currentCloudTask?.run_number]);
  const canSplitProject = useMediaQuery('(min-width: 1280px)') && !isStudio;
  const projectSideBySide = canSplitProject && !projectExpanded;
  const messagesQuery = useQuery<{
    id: string;
    message_id?: number;
    role: string;
    content: string;
    attachment?: AttachmentInfo;
    search?: { query: string; summary: string }[];
    author?: { name: string; avatar_url?: string | null } | null;
    mine?: boolean;
  }[]>({
    queryKey: ['messages', activeConvId],
    queryFn: ({ signal }) => apiFetch(`/conversations/${activeConvId}/messages`, { signal, timeoutMs: 15000 }),
    enabled: !!activeConvId,
    staleTime: 3_000,
    refetchInterval: thinking && activeConvId ? 2000 : sharedRoom ? 4000 : false,
  });
  const messagesReady = Boolean(activeConvId) && messagesQuery.data !== undefined && !messagesQuery.isPlaceholderData;
  const messages = messagesReady ? (messagesQuery.data ?? []) : [];
  // A missing history is a loading state, not a new conversation. Cached query
  // data can also arrive one render before its display projection is installed.
  const restoringConversation = !openNewChat && !activeConvId && (!conversationsFetched || conversations.length > 0);
  const conversationListFailed = !activeConvId && conversationsQuery.isError && !conversationsQuery.data;
  const historyPending = conversationListFailed || restoringConversation || Boolean(activeConvId && (!messagesReady || displayConversationId !== activeConvId));

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
        setProjectPanel(null);
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

  useLayoutEffect(() => {
    setDisplayMessages([]);
    setDisplayConversationId(undefined);
    setSelectionQuote(null);
    setForcedEditUrl(null);
    setSkipLastImage(false);
    setRegeneratingId(null);
    setSourceMessageId(undefined);
    setSourcesSheetOpen(false);
  }, [activeConvId]);

  useLayoutEffect(() => {
    if (!activeConvId || !messagesReady) return;
      // Commit the conversation and its projected messages before paint. The
      // welcome screen is only valid after a loaded history is genuinely empty.
      setDisplayConversationId(activeConvId);
      const base = messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .filter((m) => regeneratingId == null || m.message_id !== regeneratingId)
        .map((m) => ({
          id: m.id,
          message_id: m.message_id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          attachment: m.attachment,
          search: m.search,
          author: m.author,
          mine: m.mine,
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
            ? [...base, { id: 'pending-user', role: 'user' as const, content: pendingContent.userText, mine: true }]
            : pendingContent.userText && imageBaseline && !persistedNewUser
              ? [...base, { id: 'pending-user', role: 'user' as const, content: pendingContent.userText, mine: true }]
              : base;

        const lastBaseAssistant = [...withUser].reverse().find((m) => m.role === 'assistant');
        // The server saves the reply a moment before it streams the text. A poll that lands in that
        // gap would show the whole answer at once, and the typing would have nothing left to type.
        // Hold the saved answer back until the text starts arriving (the job stops "thinking").
        // Without a live socket, or for an image job (plain HTTP), no stream is coming: show what the poll found.
        const holdSavedAnswer =
          pendingContent.thinking && wsStatus === 'open' && !(activeConvId && httpJobsRef.current.has(activeConvId));
        const lastUserAt = withUser.map((m) => m.role).lastIndexOf('user');
        const viewBase = holdSavedAnswer
          ? withUser.filter((m, i) => !(i > lastUserAt && m.role === 'assistant' && !('attachment' in m && m.attachment?.interim)))
          : withUser;
        const pendingClarify = splitSearch(pendingContent.search).questions.length > 0;
        const lastHasClarify = isClarifyMessage(
          lastBaseAssistant && 'search' in lastBaseAssistant ? lastBaseAssistant.search : undefined,
        );
        const withAssistant =
          (pendingContent.text || pendingClarify) &&
          !lastHasClarify &&
          lastBaseAssistant?.content !== pendingContent.text
            ? [
                ...viewBase,
                {
                  id: 'pending-assistant',
                  role: 'assistant' as const,
                  content: pendingContent.text,
                  reasoning: pendingContent.reasoning,
                  search: pendingContent.search,
                },
              ]
            : viewBase;

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
                  ...(withAssistant === viewBase
                    ? { reasoning: pendingContent.reasoning, search: pendingContent.search }
                    : {}),
                },
              ]
          : withAssistant;

        // A Pilot package posts each finished document mid-reply; those are not the answer yet.
        const isFinalAnswer = (message: (typeof withFile)[number]) => message.role === 'assistant'
          && !('attachment' in message && message.attachment?.interim);
        const jobError = activeConvId ? jobErrors[activeConvId] : undefined;
        const withError = jobError && !pendingContent.thinking
          ? [...withFile, { id: `job-err-${activeConvId}`, role: 'assistant' as const, content: jobError }]
          : withFile;

        setDisplayMessages((current) => keepLiveUploads(current, withError));

        // If the socket reconnected during a long analysis, polling may see the
        // persisted assistant answer before a new `done` event can arrive.
        const pendingUserIndex = pendingContent.userText
          ? base.map((message) => message.role === 'user' ? message.content : '').lastIndexOf(pendingContent.userText)
          : -1;
        const recoveredAnswer = imageBaseline
          ? base.some((message) => isFinalAnswer(message) && !imageBaseline.has(message.id))
          : pendingUserIndex >= 0
            && base.slice(pendingUserIndex + 1).some(isFinalAnswer);
        if (pendingContent.thinking && recoveredAnswer && !holdSavedAnswer) {
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
        const error = jobErrors[activeConvId];
        const withError = error ? [...base, { id: `job-err-${activeConvId}`, role: 'assistant' as const, content: error }] : base;
        setDisplayMessages((current) => keepLiveUploads(current, withError));
      }
  }, [activeConvId, messages, messagesReady, pendingContent, regeneratingId, jobErrors]);

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
        setSearchParams({}, { replace: true });
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
    // Persist rapid selections in order, so a slow earlier request cannot
    // become the server's active conversation after the latest selection.
    scope: { id: 'activate-conversation' },
    mutationFn: (id: string) => apiFetch(`/conversations/${id}/activate`, { method: 'POST', timeoutMs: 15000 }),
  });

  useEffect(() => {
    if (!activeConvId) return;
    activateMutation.mutate(activeConvId, { onError: () => {
      if (activeConvRef.current === activeConvId) setProjectNotice({ text: 'Не удалось сохранить выбор беседы. Она останется открытой; повторите выбор, когда соединение восстановится.', warning: true });
    } });
  }, [activeConvId]);

  const { messages: wsMessages, send, status: wsStatus, waitUntilReady } = useChatConnection();
  const processedRef = useRef<Set<string>>(new Set());
  const ignoreByConvRef = useRef<Set<string>>(new Set());
  const openingNewRef = useRef(false);
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
  }, [wsMessages, activeConvId, queryClient, pendingContent.convId]);

  useEffect(() => {
    setForcedEditUrl(null);
    setSkipLastImage(false);
    setSelectionQuote(null);
  }, [activeConvId]);

  useEffect(() => {
    if (isStudio && isMobile && canvasSource) setMobileCanvasOpen(true);
  }, [isStudio, isMobile, canvasSource?.url, canvasSource?.html, canvasSource?.name]);

  const handleSelect = async (id: string) => {
    ++selectionRequestRef.current;
    setProjectPanel(null);
    // Tapping the chat that is already open must not blank it: activeConvId stays the
    // same, so nothing would refill displayMessages afterwards.
    if (id === activeConvId) {
      void activateMutation.mutateAsync(id).catch(() => setProjectNotice({ text: 'Не удалось сохранить выбранную беседу. Проверьте соединение.', warning: true }));
      if (isMobile) setSidebarOpen(false);
      return;
    }
    setActiveConvId(id);
    setSearchParams({ c: id });
    setDisplayMessages([]);
    setSourceMessageId(undefined);
    setSourcesSheetOpen(false);
    if (isMobile) setSidebarOpen(false);
  };

  const handleCreate = async (targetProject?: string | null) => {
    const request = ++selectionRequestRef.current;
    const owner = useAuthStore.getState().user;
    const ownerId = owner?.id || owner?.email;
    const sameAccount = () => {
      const current = useAuthStore.getState();
      return Boolean(current.accessToken) && (current.user?.id || current.user?.email) === ownerId;
    };
    ++projectRequestRef.current;
    const pid = targetProject === undefined ? (projectPanel || projectBinding.data?.project_id || null) : targetProject;
    setProjectPanel(null);
    let created = false;
    // Every explicit click creates its own chat. Keep server-side activation in
    // click order while generation in other conversations continues independently.
    const creation = creationQueueRef.current.then(async () => {
      if (!sameAccount()) return;
      const conv = await createMutation.mutateAsync();
      created = true;
      if (!sameAccount()) return;
      if (pid) await apiFetch(`/projects/chat/${conv.id}`, { method: 'PUT', body: JSON.stringify({ project_id: pid }) });
      if (!sameAccount()) return;
      void queryClient.invalidateQueries({ queryKey: ['project-chat'] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      if (request !== selectionRequestRef.current) {
        // A later selection owns the screen and the active chat after reload.
        const selected = activeConvRef.current;
        if (selected) await activateMutation.mutateAsync(selected);
        return;
      }
      setActiveConvId(conv.id);
      setSearchParams({ c: conv.id }, { replace: openNewChat });
      setDisplayMessages([]);
      setSourceMessageId(undefined);
      setSourcesSheetOpen(false);
      setProjectNotice(null);
      if (isMobile) setSidebarOpen(false);
    });
    // A failed request must not poison subsequent clicks in the queue.
    creationQueueRef.current = creation.catch(() => undefined);
    try { await creation; }
    catch {
      setProjectNotice({
        text: created
          ? 'Беседа создана, но не удалось завершить её открытие. Выберите её в списке бесед.'
          : 'Не удалось создать беседу. Проверьте соединение и попробуйте ещё раз.',
        warning: true,
      });
    }
  };

  useEffect(() => {
    if (!openNewChat || !conversationsFetched || openingNewRef.current) return;
    openingNewRef.current = true;
    void handleCreate().finally(() => {
      openingNewRef.current = false;
    });
  }, [openNewChat, conversationsFetched]);

  const moveChatToProject = async (cid: string, pid: string | null) => {
    await apiFetch(`/projects/chat/${cid}`, { method: 'PUT', body: JSON.stringify({ project_id: pid }) });
    ++projectRequestRef.current;
    if (cid === activeConvId) setProjectPanel(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['projects'] }),
      queryClient.invalidateQueries({ queryKey: ['project-chat', cid] }),
      queryClient.invalidateQueries({ queryKey: ['project-workspace'] }),
    ]);
  };

  const [projectNotice, setProjectNotice] = useState<{ text: string; warning: boolean } | null>(null);
  const handleProjectDeleted = (pid: string, cleanupPending = false) => {
    ++projectRequestRef.current;
    if (projectPanel === pid) { setProjectPanel(null); setProjectOpenError(''); }
    if (projectBinding.data?.project_id === pid && activeConvId) queryClient.setQueryData(['project-chat', activeConvId], { project_id: null });
    queryClient.setQueryData<ProjectItem[]>(['projects'], old => old?.filter(p => p.id !== pid));
    setProjectNotice({ text: cleanupPending ? 'Проект удалён, беседы сохранены. Очистка копий файлов пока не завершена.' : 'Проект удалён. Беседы сохранены в разделе «Беседы вне проектов».', warning: cleanupPending });
  };

  const openProject = async (pid: string) => {
    const request = ++projectRequestRef.current;
    setProjectPanel(pid); setSidebarOpen(false); setProjectOpenError('');
    try {
      const space = await apiFetch(`/projects/${pid}/workspace`) as ProjectSpace;
      let cid = space.chats.find(chat => chat.id === activeConvId)?.id || space.chats[0]?.id;
      if (!cid) {
        const chat = await createMutation.mutateAsync(); cid = chat.id;
        await apiFetch(`/projects/chat/${cid}`, { method: 'PUT', body: JSON.stringify({ project_id: pid }) });
      }
      if (request !== projectRequestRef.current) return;
      await handleSelect(cid!);
      if (request !== projectRequestRef.current) return;
      setProjectPanel(pid);
      queryClient.invalidateQueries({ queryKey: ['project-chat'] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      queryClient.invalidateQueries({ queryKey: ['project-workspace', pid] });
    } catch {
      if (request === projectRequestRef.current) setProjectOpenError('Не удалось открыть беседу проекта. Выберите проект ещё раз, чтобы повторить.');
    }
  };

  const handleSend = async (rawText: string, files: File[] = [], mode: 'chat' | 'image' = 'chat'): Promise<boolean> => {
    const text = rawText || (files.length ? 'Проанализируй прикреплённые файлы.' : '');
    const sendKey = activeConvId || 'new';
    if (!text || sendingRef.current.has(sendKey) || thinking || (activeConvId && !messagesReady)) return false;
    sendingRef.current.add(sendKey);
    let optimisticId: string | undefined;
    let conversationId = activeConvId;
    try {
      if (!conversationId) {
        const conversation = await createMutation.mutateAsync();
        conversationId = conversation.id;
        const account = useAuthStore.getState().user;
        adoptNewComposerDraft(account?.id || account?.email || 'anonymous', conversationId!);
        setActiveConvId(conversationId);
        setSearchParams({ c: conversationId! }, { replace: true });
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
        httpJobsRef.current.add(conversationId);
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
        if (data.url && activeConvRef.current === conversationId) {
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
      if (models?.selected === 'director' && !sharedRoom) {
        const payload = JSON.stringify({ prompt: text, conversation_id: conversationId });
        if (taskEnrollmentRef.current.payload !== payload) taskEnrollmentRef.current = { payload, key: crypto.randomUUID() };
        const task = await apiFetch('/computer/tasks', { method: 'POST', body: JSON.stringify({ prompt: text, conversation_id: conversationId, idempotency_key: taskEnrollmentRef.current.key }) }) as CloudTask;
        queryClient.setQueryData<CloudTask[]>(['computer-tasks'], old => [task, ...(old || []).filter(item => item.id !== task.id)]);
        taskEnrollmentRef.current = { payload: '', key: '' };
        return true;
      }
      // Long multi-file uploads can outlive a WS reconnect. Wait until auth
      // completes before treating the send as delivered.
      const ready = await waitUntilReady(45000);
      if (!ready) throw new Error('нет соединения с сервером, попробуйте ещё раз');
      send('message', { content: text, conversation_id: conversationId });
      return true;
    } catch (error: any) {
      const targetConvId = conversationId;
      finishJob(targetConvId);
      queryClient.invalidateQueries({ queryKey: ['messages', targetConvId] });
      const aborted = /остановлен|ожидания/i.test(error?.message || '');
      const errorText = aborted && mode === 'image'
        ? (error?.message?.includes('ожидания') ? 'Картинка рисуется слишком долго. Попробуйте ещё раз или упростите описание.' : 'Генерация остановлена.')
        : `Не удалось отправить сообщение: ${error?.message || 'ошибка соединения'}`;
      if (targetConvId) setJobErrors(previous => ({ ...previous, [targetConvId]: errorText }));
      if (activeConvRef.current === targetConvId) setDisplayMessages((current) => [
        ...current.filter((message) => message.id !== optimisticId),
        {
          id: `err-${Date.now()}`,
          role: 'assistant' as const,
          content: errorText,
        },
      ]);
      return false;
    } finally {
      sendingRef.current.delete(sendKey);
    }
  };

  const handleStop = () => {
    imageAbortRef.current?.abort();
    if (!activeConvId) return;
    if (currentCloudTask && ['queued', 'running'].includes(currentCloudTask.status)) {
      void apiFetch(`/computer/tasks/${currentCloudTask.id}/pause`, { method: 'POST' }).then(() => {
        ignoreByConvRef.current.add(activeConvId); finishJob(activeConvId);
        queryClient.invalidateQueries({ queryKey: ['computer-tasks'] });
        queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
      }).catch(error => setJobErrors(old => ({ ...old, [activeConvId]: error.message })));
      return;
    }
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
    if (typeof lastAssistant?.message_id === 'number') setRegeneratingId(lastAssistant.message_id);
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
    if (!activeConvId || thinking) return;
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
    if (!msg?.attachment || typeof msg.message_id !== 'number') return;
    try {
      const params = new URLSearchParams();
      if (activeConvId) params.set('conversation_id', activeConvId);
      params.set('message_id', String(msg.message_id));
      await apiFetch(`/documents/${encodeURIComponent(msg.attachment.name)}?${params}`, { method: 'DELETE' });
      setDisplayMessages((current) => current.filter((item) => item.id !== messageId));
      if (activeConvId) queryClient.invalidateQueries({ queryKey: ['messages', activeConvId] });
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    } catch (e: any) {
      setDisplayMessages((m) => [
        ...m,
        { id: `err-${Date.now()}`, role: 'assistant', content: `Не удалось удалить вложение из контекста: ${e.message}` },
      ]);
    }
  };

  async function handleFileUpload(files: File[], conversationId: string, keepThinking = false): Promise<boolean> {
    files = files.filter(file => !uploadedFilesRef.current.get(file)?.has(conversationId));
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
    const LARGE_DOCUMENT_BYTES = 1024 * 1024;
    let lastError: string | undefined;
    let finished = 0;

    const uploadOne = async (index: number) => {
      const { file, uploadId } = batch[index];
      const formData = new FormData();
      formData.append('file', file);
      formData.append('conversation_id', conversationId!);
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      const largeDocument = !file.type.startsWith('image/') && file.size >= LARGE_DOCUMENT_BYTES;
      const paintProgress = (progress: number | null, progressLabel: string) => {
        setDisplayMessages((current) => current.map((message) => message.id === uploadId ? {
          ...message,
          attachment: { ...message.attachment!, progress, progressLabel },
        } : message));
      };
      try {
        let data: { message?: { id: string; role: string; content: string; attachment?: AttachmentInfo } };
        if (largeDocument) {
          paintProgress(0, 'Загрузка 0%');
          data = await apiFormDataProgress('/documents', formData, {
            signal: controller.signal,
            timeoutMs: UPLOAD_TIMEOUT_MS,
            headers: { 'X-Document-Progress': '1' },
            onUploadProgress: (loaded, total) => {
              if (total <= 0) {
                paintProgress(null, 'Загрузка');
                return;
              }
              if (loaded >= total) {
                paintProgress(null, 'Разбираю документ');
                return;
              }
              const pct = Math.round((loaded * 100) / total);
              paintProgress(pct, `Загрузка ${pct}%`);
            },
            onEvent: (event) => {
              if (event.type !== 'progress') return;
              const done = Number(event.done);
              const total = Number(event.total);
              if (!Number.isFinite(done) || !Number.isFinite(total) || total < 2) return;
              const pct = Math.max(0, Math.min(100, Math.round((done * 100) / total)));
              paintProgress(pct, String(event.label || `Разбор ${done} из ${total}`));
            },
          }) as { message?: { id: string; role: string; content: string; attachment?: AttachmentInfo } };
        } else {
          const res = await apiFormData('/documents', formData, { signal: controller.signal });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.message || (res.status === 413 ? 'Файл слишком большой для загрузки' : `HTTP ${res.status}`);
            throw new Error(errMsg);
          }
          data = await res.json();
        }
        successCount += 1;
        const uploadedIn = uploadedFilesRef.current.get(file) || new Set<string>();
        uploadedIn.add(conversationId);
        uploadedFilesRef.current.set(file, uploadedIn);
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
    if (successCount !== batch.length) {
      throw new Error(`Не загружено файлов: ${batch.length - successCount}. ${lastError || 'Ошибка загрузки'}. Повторите отправку — готовые файлы загружать заново не нужно.`);
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
    setSourceMessageId(messageId);
    setSourcesSheetOpen(true);
  };

  let lastAssistantIndex = -1;
  for (let index = displayMessages.length - 1; index >= 0; index -= 1) {
    if (displayMessages[index].role === 'assistant') {
      lastAssistantIndex = index;
      break;
    }
  }
  const previousUser = lastAssistantIndex >= 0
    ? [...displayMessages.slice(0, lastAssistantIndex)].reverse().find((message) => message.role === 'user')
    : undefined;
  const canRegenerateReply = !sharedRoom || activeConversation?.role === 'owner' || Boolean(previousUser?.mine);

  // Phones: bare icons (44px touch target, no plate) like the assistants people compare it to.
  const phoneBtn = { ...headerIconBtnSx, bgcolor: 'transparent', borderColor: 'transparent', '&:hover': { bgcolor: 'transparent' } } as const;
  const barBtn = isMobile ? phoneBtn : headerIconBtnSx;
  const groupBtn = isMobile ? phoneBtn : headerGroupBtnSx;

  const chatHeader = (
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
            pb: { xs: 1.25, md: 3 },
            // Phones: a solid bar, so scrolled text never runs under the title and buttons.
            background: {
              xs: 'var(--bt-fade-solid)',
              md: 'linear-gradient(180deg, var(--bt-fade) 0%, var(--bt-fade-mid) 62%, transparent 100%)',
            },
            borderBottom: { xs: '1px solid var(--bt-hairline)', md: 'none' },
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, pointerEvents: 'auto', minWidth: 0, flex: { xs: 1, md: 'none' } }}>
            {isMobile && (
              <IconButton onClick={() => setSidebarOpen(true)} sx={barBtn} aria-label="Открыть список бесед">
                <ListIcon size={22} weight="bold" />
              </IconButton>
            )}
            {isMobile && activeConversation && displayMessages.length > 0 && (
              // Phones have no sidebar on screen: say which chat this is.
              <Box
                component="h1"
                sx={{
                  m: 0,
                  minWidth: 0,
                  fontSize: '0.9375rem',
                  fontWeight: 600,
                  letterSpacing: '-0.01em',
                  color: 'text.primary',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {activeConversation.title}
              </Box>
            )}
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, pointerEvents: 'auto' }}>
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
            <Box sx={isMobile ? { display: 'contents' } : headerGroupSx}>
            {allSources.length > 0 && (
              <Tooltip title={sourcesLabel(allSources.length)}>
                <IconButton
                  onClick={() => {
                    setSourceMessageId(undefined);
                    setSourcesSheetOpen(true);
                  }}
                  sx={groupBtn}
                  aria-label={sourcesLabel(allSources.length)}
                >
                  <MagnifyingGlass size={22} weight="bold" />
                </IconButton>
              </Tooltip>
            )}
            {activeConvId && !isMobile && (
              <Tooltip title="Файлы беседы">
                <IconButton onClick={() => { setFilesScope('chat'); setFilesOpen(true); }} sx={groupBtn} aria-label="Файлы беседы">
                  <FolderSimple size={22} weight="bold" />
                </IconButton>
              </Tooltip>
            )}
            {activeConvId && !isMobile && (
              <Tooltip title="Поделиться диалогом">
                <IconButton onClick={() => setShareOpen(true)} sx={groupBtn} aria-label="Поделиться диалогом">
                  <Users size={22} weight="bold" />
                </IconButton>
              </Tooltip>
            )}
            {sharedRoom && activeConvId && (
              <Tooltip title="Переписка между людьми, без ассистента">
                <IconButton
                  onClick={() => setRoomOpenById((prev) => ({ ...prev, [activeConvId]: !prev[activeConvId] }))}
                  sx={{
                    ...groupBtn,
                    ...(roomOpenById[activeConvId] ? { color: 'primary.light', bgcolor: 'var(--bt-glow)' } : {}),
                  }}
                  aria-label="Переписка между людьми"
                  aria-pressed={Boolean(roomOpenById[activeConvId])}
                >
                  <ChatsCircle size={22} weight="bold" />
                </IconButton>
              </Tooltip>
            )}
            {!isMobile && (
              <Tooltip title="Экспортировать ответ в DOCX">
                <span>
                  <IconButton
                    onClick={exportDocx}
                    disabled={exporting || !displayMessages.some((m) => m.role === 'assistant')}
                    sx={groupBtn}
                    aria-label="Экспортировать ответ в DOCX"
                  >
                    <FileArrowDown size={22} weight="bold" />
                  </IconButton>
                </span>
              </Tooltip>
            )}
            </Box>
            {isMobile && (
              // Seven round buttons do not fit a phone; the rarely used ones live here.
              <IconButton
                onClick={(event) => setMoreAnchor(event.currentTarget)}
                sx={barBtn}
                aria-label="Ещё действия"
                aria-haspopup="menu"
                aria-expanded={Boolean(moreAnchor)}
              >
                <DotsThree size={22} weight="bold" />
              </IconButton>
            )}
            <Menu
              anchorEl={moreAnchor}
              open={Boolean(moreAnchor)}
              onClose={() => setMoreAnchor(null)}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
              transformOrigin={{ vertical: 'top', horizontal: 'right' }}
              slotProps={{ paper: { sx: { minWidth: 240, mt: 0.75, borderRadius: '14px' } } }}
            >
              {activeConvId && (
                <MenuItem onClick={() => { setMoreAnchor(null); setFilesScope('chat'); setFilesOpen(true); }} sx={{ minHeight: 48 }}>
                  <ListItemIcon><FolderSimple size={20} /></ListItemIcon>
                  <ListItemText>Файлы беседы</ListItemText>
                </MenuItem>
              )}
              {activeConvId && (
                <MenuItem onClick={() => { setMoreAnchor(null); setShareOpen(true); }} sx={{ minHeight: 48 }}>
                  <ListItemIcon><Users size={20} /></ListItemIcon>
                  <ListItemText>Поделиться диалогом</ListItemText>
                </MenuItem>
              )}
              <MenuItem
                disabled={exporting || !displayMessages.some((m) => m.role === 'assistant')}
                onClick={() => { setMoreAnchor(null); exportDocx(); }}
                sx={{ minHeight: 48 }}
              >
                <ListItemIcon><FileArrowDown size={20} /></ListItemIcon>
                <ListItemText>Ответ в DOCX</ListItemText>
              </MenuItem>
              <MenuItem onClick={() => { setMoreAnchor(null); colorMode.toggle(); }} sx={{ minHeight: 48 }}>
                <ListItemIcon>{colorMode.mode === 'dark' ? <Sun size={20} /> : <Moon size={20} />}</ListItemIcon>
                <ListItemText>{colorMode.mode === 'dark' ? 'Светлая тема' : 'Тёмная тема'}</ListItemText>
              </MenuItem>
            </Menu>
            {/* Desktop keeps the account in the sidebar footer; phones have no sidebar on screen. */}
            {isMobile && <AccountMenu />}
          </Box>
        </Box>
  );

  return (
    <Box
      sx={{
        height: `min(100dvh, ${visualViewportHeight}px)`,
        '--bt-viewport-h': `${visualViewportHeight}px`,
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
              width: 'min(88vw, 320px)',
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
            onSelect={id => { ++projectRequestRef.current; void handleSelect(id); }}
            onCreate={() => { void handleCreate(null); }}
            onCreateInProject={pid => handleCreate(pid)}
            onDelete={(id) => {
              send('stop', { conversation_id: id });
              finishJob(id);
              deleteMutation.mutate(id);
            }}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            onClose={() => setSidebarOpen(false)}
            onLibrary={() => { setFilesScope('all'); setFilesOpen(true); if (isMobile) setSidebarOpen(false); }}
            generatingIds={generatingIds}
            onProjectDeleted={handleProjectDeleted}
            onMoveChat={moveChatToProject}
            projects={projectsQuery.data || []}
            activeProjectId={projectPanel || projectBinding.data?.project_id}
            onProject={pid => { void openProject(pid); }}
            onCreateProject={() => { ++projectRequestRef.current; setProjectOpenError(''); setProjectPanel(''); setSidebarOpen(false); }}
          />
        </SwipeableDrawer>
      ) : (
        <Box sx={{ flexShrink: 0, height: '100%', overflow: 'hidden' }}>
          <ChatSidebar
            conversations={conversations}
            activeId={activeConvId}
            onSelect={id => { ++projectRequestRef.current; void handleSelect(id); }}
            onCreate={() => { void handleCreate(null); }}
            onCreateInProject={pid => handleCreate(pid)}
            onDelete={(id) => {
              send('stop', { conversation_id: id });
              finishJob(id);
              deleteMutation.mutate(id);
            }}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            onLibrary={() => { setFilesScope('all'); setFilesOpen(true); if (isMobile) setSidebarOpen(false); }}
            generatingIds={generatingIds}
            onProjectDeleted={handleProjectDeleted}
            onMoveChat={moveChatToProject}
            projects={projectsQuery.data || []}
            activeProjectId={projectPanel || projectBinding.data?.project_id}
            onProject={pid => { void openProject(pid); }}
            onCreateProject={() => { ++projectRequestRef.current; setProjectOpenError(''); setProjectPanel(''); setSidebarOpen(false); }}
          />
        </Box>
      )}

      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', overflow: 'hidden', position: 'relative' }}>
      <Box
        sx={{
          ...(isStudio && !isMobile
            ? { width: { md: 400, lg: 440, xl: 480 }, flexShrink: 0 }
            : { flex: 1 }),
          minWidth: 0,
          minHeight: 0,
          display: projectPanel !== null && (!projectSideBySide || !projectPanel) ? 'none' : 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {chatHeader}
        {!sharedRoom && projectBinding.data?.project_id && <Box sx={{ px: 2, pb: .75, flexShrink: 0 }}><Button size="small" color="inherit" startIcon={<FolderSimple size={15} />} onClick={() => setProjectPanel(projectBinding.data!.project_id)} sx={{ color: 'text.secondary', fontSize: 12 }}>Проект · {projectsQuery.data?.find(p => p.id === projectBinding.data?.project_id)?.name || 'Материалы'}</Button></Box>}
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
        {historyPending ? (
          <Box role={messagesQuery.isError || conversationListFailed ? 'alert' : 'status'} sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 1.5, px: 3, textAlign: 'center', color: 'text.secondary' }}>
            <Box>{conversationListFailed ? 'Не удалось загрузить список бесед. Повторите загрузку.' : messagesQuery.isError ? 'Не удалось загрузить беседу. Черновик сохранён.' : 'Загружаем беседу…'}</Box>
            {(messagesQuery.isError || conversationListFailed) && <Button onClick={() => void (conversationListFailed ? conversationsQuery.refetch() : messagesQuery.refetch())}>Повторить загрузку</Button>}
          </Box>
        ) : <ChatWindow
          key={activeConvId || 'new'}
          convId={activeConvId}
          chipsHost={chipsHost}
          messages={displayMessages}
          thinking={thinking}
          statusText={statusText}
          liveReasoning={pendingContent.convId === activeConvId ? pendingContent.reasoning : undefined}
          onRemoveAttachment={handleRemoveAttachment}
          onRegenerate={canRegenerateReply ? handleRegenerate : undefined}
          onStop={handleStop}
          onEditMessage={handleEditMessage}
          onEditImage={
            isDocgen
              ? undefined
              : (url) => {
                  setForcedEditUrl(url);
                  setSkipLastImage(false);
                  setImageModeRequest((value) => value + 1);
                }
          }
          onSuggestion={handleSend}
          onEditResult={(result, selection) => { setResultEdit({ ...result, selection, requestId: crypto.randomUUID() }); setProjectCitation(null); setProjectOpenError(''); setProjectPanel(result.projectId); }}
          onClarifySelection={text => { setSelectionQuote({ text }); setForcedEditUrl(null); setSkipLastImage(true); }}
          hasCanvas={Boolean(canvasSource)}
          people={sharedRoom}
          activeSourceId={sourceMessageId}
          onOpenSources={openSources}
          onOpenProjectCitation={citation => { setProjectCitation(citation); setProjectOpenError(''); setProjectPanel(citation.projectId); }}
          clarifyDocked={clarifyQuestions.length > 0}
          jumpRef={dialogueJumpRef}
          splitPane={Boolean(isStudio && !isMobile)}
          composerSlotRef={!isMobile && !isStudio ? setSlotEl : undefined}
        />}
        <Box
          ref={composerDockRef}
          sx={{
            position: 'absolute',
            left: 0,
            right: 0,
            ...(composerInSlot ? { top: slotTop, bottom: 'auto' } : { bottom: 0 }),
            zIndex: 3,
            pointerEvents: 'none',
            pt: composerInSlot ? 0 : clarifyQuestions.length ? 2 : 2.5,
            background: composerInSlot
              ? 'none'
              : 'linear-gradient(180deg, transparent 0%, var(--bt-fade) 42%, var(--bt-fade-solid) 78%)',
          }}
        >
          <Box sx={{ ...CHAT_COL, ...(isStudio && !isMobile ? { maxWidth: '100%', px: 1.75 } : {}), position: 'relative', display: 'flex', flexDirection: 'column', maxHeight: 'calc(var(--bt-viewport-h, 100dvh) - 76px)', pb: { xs: 'max(12px, env(safe-area-inset-bottom))', md: 2 }, pointerEvents: 'auto' }}>
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
            <Box sx={{ minHeight: 0, flex: '0 1 auto', overflowY: 'auto', overflowX: 'hidden' }}>
            <QuotaNotice />
            <Box ref={setChipsHost} />
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
            {currentCloudTask && <CloudTaskBar key={currentCloudTask.id} task={currentCloudTask} />}
            {!sharedRoom && activeConvId && projectBinding.data?.project_id && <ProjectContextControl key={activeConvId} conversationId={activeConvId} projectId={projectBinding.data.project_id} disabled={thinking} />}
            </Box>
            <MessageInput
              conversationId={activeConvId}
              selectionQuote={selectionQuote}
              onClearSelectionQuote={() => setSelectionQuote(null)}
              onOpenProjects={() => setProjectPanel(projectBinding.data?.project_id || '')}
              onSend={handleSend}
              disabled={thinking || historyPending}
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
      </Box>
      {sharedRoom && activeConvId && (
        <RoomChat
          key={activeConvId}
          conversationId={activeConvId}
          open={Boolean(roomOpenById[activeConvId])}
          onClose={() => setRoomOpenById((prev) => ({ ...prev, [activeConvId]: false }))}
        />
      )}
      <Snackbar open={!!projectNotice} autoHideDuration={projectNotice?.warning ? undefined : 6000} onClose={(_, reason) => { if (reason !== 'clickaway') setProjectNotice(null); }} anchorOrigin={{ vertical: 'top', horizontal: 'center' }}><Alert severity={projectNotice?.warning ? 'warning' : 'success'} onClose={() => setProjectNotice(null)} sx={{ maxWidth: 480 }}>{projectNotice?.text}</Alert></Snackbar>
      {projectPanel !== null && <Box sx={{ flex: projectSideBySide && projectPanel ? '0 0 48%' : '1 1 100%', minWidth: 0, minHeight: 0, borderLeft: projectSideBySide && projectPanel ? '1px solid var(--bt-hairline)' : 'none' }}>
        <ProjectWorkspace editRequest={resultEdit?.projectId === projectPanel ? resultEdit : null} citation={projectCitation?.projectId === projectPanel ? projectCitation : null} onProjectDeleted={handleProjectDeleted} key={projectPanel || 'create-project'} projectId={projectPanel} conversationId={!sharedRoom && projectBinding.data?.project_id === projectPanel ? activeConvId : undefined} externalError={projectOpenError} expanded={projectExpanded} onToggleSize={canSplitProject ? () => setProjectExpanded(value => !value) : undefined}
          onClose={() => { ++projectRequestRef.current; setProjectPanel(null); setProjectCitation(null); setResultEdit(null); }}
          onCreated={project => { queryClient.invalidateQueries({ queryKey: ['projects'] }); void openProject(project.id); }}
          onSelectChat={id => { ++projectRequestRef.current; void handleSelect(id); }} />
      </Box>}
      {projectPanel === null && isStudio && !isMobile && (
        <DesignCanvas source={canvasSource} thinking={thinking} statusText={statusText} />
      )}
      </Box>
      {projectPanel === null && isStudio && isMobile && (
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
        side={!isMobile}
        sources={focusedSources}
        scoped={Boolean(focusedSourceMessage)}
        allCount={allSources.length}
        onShowAll={() => setSourceMessageId(undefined)}
        open={sourcesSheetOpen}
        onClose={() => setSourcesSheetOpen(false)}
        onOpen={() => setSourcesSheetOpen(true)}
      />
      {activeConvId && (
        <ShareDialog conversationId={activeConvId} open={shareOpen} onClose={() => setShareOpen(false)} />
      )}
      <DocumentEditorDialog conversationId={activeConvId} />
      <ConversationFilesDrawer
        conversationId={activeConvId}
        open={filesOpen}
        scope={filesScope}
        onClose={() => setFilesOpen(false)}
        onOpenChat={handleSelect}
      />
    </Box>
  );
}
