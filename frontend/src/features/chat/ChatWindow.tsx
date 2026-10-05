import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { createPortal } from 'react-dom';
import { Box, IconButton } from '@mui/material';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowsLeftRight, Bug, Newspaper, Paperclip, type Icon } from '@phosphor-icons/react';
import { useAuthStore } from '@/stores/authStore';
import { ChatMessage } from './ChatMessage';
import { ActivityFeed } from '@/components/ActivityFeed';
import { AttachmentInfo } from './DocumentAttachment';
import { ReasoningTrace, SearchItem } from './ReasoningTrace';
import { DialogueRail } from './DialogueRail';
import { type DialogueJumpFn, MIN_DIALOGUE_QUESTIONS, messageOffset, scrollToQuestion } from './dialogueNav';
import { CHAT_COL, CLARIFY_SCROLL_PAD, COMPOSER_SCROLL_PAD, HEADER_SCROLL_PAD } from './chatColumn';
import { isClarifyMessage, isClarifyReply } from './clarify';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { CaretDown, CaretUp, Desktop, Presentation } from '@phosphor-icons/react';
import { useSelectModel } from '@/components/ModelSelector';
import { DOCGEN_LABEL, PILOT_LABEL, STUDIO_LABEL } from '@/constants/modes';
import { BrandMark } from '@/components/BrandMark';
import { followUpChips, followUpMode } from './followUps';
import { normalizeMarkdown } from './markdownText';
import { isReplyText, useReplySnapshot } from './replyReveal';

export interface DisplayMessage {
  id: string;
  message_id?: number;
  role: 'user' | 'assistant';
  content: string;
  file?: { filename: string; data: string; url?: string; canvas?: boolean };
  attachment?: AttachmentInfo;
  reasoning?: string;
  search?: SearchItem[];
  author?: { name: string; avatar_url?: string | null } | null;
  mine?: boolean;
}

interface Props {
  messages: DisplayMessage[];
  thinking: boolean;
  statusText: string;
  liveReasoning?: string;
  onRemoveAttachment?: (messageId: string) => void;
  onRegenerate?: () => void;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onEditImage?: (url: string) => void;
  onSuggestion?: (text: string) => void;
  hasCanvas?: boolean;
  people?: boolean;
  activeSourceId?: string;
  onOpenSources?: (messageId: string) => void;
  clarifyDocked?: boolean;
  jumpRef?: MutableRefObject<DialogueJumpFn | null>;
  splitPane?: boolean;
  /** Empty chat only: a spacer under the heading. The page parks the (single) composer on top of it. */
  composerSlotRef?: (element: HTMLElement | null) => void;
  /** The open conversation: tells a reply that is being typed out which chat it belongs to. */
  convId?: string;
  /** Where the follow-up chips go: a slot in the composer dock, so they never end up under it. */
  chipsHost?: HTMLElement | null;
}

interface Suggestion {
  label: string;
  text: string;
  icon?: Icon;
}

const SUGGESTIONS: Suggestion[] = [
  { label: 'Что нового в мире', text: 'Что главное произошло сегодня в мире? Коротко и по источникам.', icon: Newspaper },
  { label: 'Разобрать файл', text: 'Я прикреплю файл. Вытащи главное и скажи, что с этим делать.', icon: Paperclip },
  { label: 'Сравнить варианты', text: 'Сравни два подхода и скажи, что выбрать в обычном случае.', icon: ArrowsLeftRight },
  { label: 'Найти ошибку в коде', text: 'Помоги найти ошибку в куске кода и как её чинить.', icon: Bug },
];

function greeting(name?: string): string {
  const hour = new Date().getHours();
  const hello = hour >= 5 && hour < 12 ? 'Доброе утро' : hour >= 12 && hour < 18 ? 'Добрый день' : hour >= 18 && hour < 23 ? 'Добрый вечер' : 'Доброй ночи';
  return name ? `${hello}, ${name}` : hello;
}

const COMPUTER_SUGGESTIONS = [
  { label: 'Место по фото', text: 'По фото найди, где это снято, и открой источники, а не угадывай по виду.' },
  { label: 'Перескажи сайт', text: 'Зайди на сайт и кратко перескажи главное, со ссылками.' },
  { label: 'Проверь почту', text: 'Проверь непрочитанные письма в Gmail и скажи, что требует ответа.' },
];

const STUDIO_SUGGESTIONS = [
  { label: 'Картинка', text: 'Нарисуй рыжего кота на крыше на закате, кинематографичный кадр, без текста.' },
  { label: 'Пичч запуска', text: 'Собери презентацию запуска умной кофейни в центре: свой визуальный язык, живые кадры, не шаблон из буллетов.' },
  { label: 'Лендинг', text: 'Собери лендинг умной кофейни: hero, меню и бронь. Свой визуальный язык, не шаблон SaaS.' },
  { label: 'Инфографика', text: 'Собери одноэкранную инфографику: путь зерна от фермы до чашки. Свой макет, не ряд одинаковых карточек.' },
];

const DOCGEN_SUGGESTIONS = [
  { label: 'По шаблону', text: 'Собери документ по шаблону из прикреплённых файлов. Остальные файлы — база знаний, не меняй структуру шаблона.' },
  { label: 'Комплект', text: 'Сделай отдельные документы по каждому шаблону, данные возьми из прикреплённых архивов.' },
  { label: 'Большой том', text: 'Собери полный документ по прикреплённым материалам. Перед генерацией покажи план и спроси подтверждение.' },
];

const suggestionChipSx = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 0.8,
  textAlign: 'left' as const,
  py: 1,
  px: 1.35,
  border: '1px solid',
  borderColor: 'var(--bt-hairline)',
  borderRadius: '999px',
  bgcolor: 'var(--bt-overlay-faint)',
  color: 'text.secondary',
  font: 'inherit',
  fontSize: '0.8125rem',
  cursor: 'pointer',
  boxSizing: 'border-box',
  transition: 'color 0.18s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.18s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.18s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
  '&:hover': {
    color: 'text.primary',
    borderColor: 'primary.main',
    bgcolor: 'var(--bt-glow)',
  },
};

export function ChatWindow({
  messages,
  thinking,
  statusText,
  liveReasoning,
  onRemoveAttachment,
  onRegenerate,
  onEditMessage,
  onEditImage,
  onSuggestion,
  hasCanvas = false,
  people = false,
  activeSourceId,
  onOpenSources,
  clarifyDocked = false,
  jumpRef,
  splitPane = false,
  composerSlotRef,
  convId,
  chipsHost,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pinToBottomRef = useRef(true);
  const skipPinUpdateRef = useRef(false);
  // Editing is locked while a reply is generated. Read through a ref and a CSS class, not a prop:
  // a prop that flips with `thinking` re-renders (and re-parses) every user message twice per turn.
  const thinkingRef = useRef(thinking);
  thinkingRef.current = thinking;
  const reduce = useReducedMotion();
  const user = useAuthStore((s) => s.user);
  const firstName = user?.first_name || undefined;
  const [scrollerNode, setScrollerNode] = useState<HTMLDivElement | null>(null);
  const [arriveId, setArriveId] = useState<string | null>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const visibleMessages = messages.filter((msg) => !isClarifyMessage(msg.search));
  // The reply that is being typed out. Its state lives outside this component (see
  // replyReveal.ts), so the live copy being swapped for the saved message cannot cut it off.
  const reply = useReplySnapshot();
  const newestAssistant = [...visibleMessages].reverse().find((msg) => msg.role === 'assistant');
  // Between `done` and the refetch the saved message is not in the list yet; keep the reply on screen.
  const showGhost =
    Boolean(convId) &&
    reply.convId === convId &&
    reply.typing &&
    !(newestAssistant && isReplyText(normalizeMarkdown(newestAssistant.content), reply));
  const listMessages: DisplayMessage[] = showGhost
    ? [...visibleMessages, { id: 'reply-ghost', role: 'assistant', content: reply.raw }]
    : visibleMessages;
  const questionTicks = useMemo(
    () =>
      visibleMessages
        .filter((msg) => msg.role === 'user' && !isClarifyReply(msg.content) && msg.content.trim())
        .map((msg) => ({ id: msg.id, label: msg.content })),
    [visibleMessages]
  );
  const lastAssistantId = [...listMessages].reverse().find((m) => m.role === 'assistant')?.id;
  const lastUser = [...visibleMessages].reverse().find((m) => m.role === 'user');
  const lastUserId = lastUser?.id;
  const lastUserText = lastUser?.content || '';
  const lastAssistantText = [...listMessages].reverse().find((m) => m.role === 'assistant')?.content || '';
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: () => apiFetch('/models') });
  const isComputer = models?.selected === 'director';
  const isStudio = models?.selected === 'studio';
  const isDocgen = models?.selected === 'docgen';
  const computerAvailable = Boolean(models?.computerAvailable);
  const studioAvailable = Boolean(models?.studioAvailable);
  const selectModel = useSelectModel();
  const suggestions = isDocgen
    ? DOCGEN_SUGGESTIONS
    : isStudio
      ? STUDIO_SUGGESTIONS
      : isComputer
        ? COMPUTER_SUGGESTIONS
        : SUGGESTIONS;
  const nextChips = !thinking && !reply.typing && !clarifyDocked
    ? followUpChips(lastUserText, lastAssistantText, followUpMode(models?.selected), hasCanvas)
    : [];
  const snappedTurnRef = useRef(false);
  const [jump, setJump] = useState({ up: false, down: false });
  // Same value, same state: a growing reply must not re-render the whole chat on every frame.
  const applyJump = (next: { up: boolean; down: boolean }) =>
    setJump((prev) => (prev.up === next.up && prev.down === next.down ? prev : next));

  const scrollToBottom = () => {
    const node = scrollerRef.current;
    if (!node) return;
    skipPinUpdateRef.current = true;
    pinToBottomRef.current = true;
    node.scrollTop = node.scrollHeight;
    requestAnimationFrame(() => {
      node.scrollTop = node.scrollHeight;
      skipPinUpdateRef.current = false;
      const gap = node.scrollHeight - node.scrollTop - node.clientHeight;
      const questionTop = lastUserId ? messageOffset(node, lastUserId) : 0;
      applyJump({
        down: gap > 64,
        up: node.scrollTop > questionTop + 56,
      });
    });
  };

  const measureJump = () => {
    const node = scrollerRef.current;
    if (!node) {
      applyJump({ up: false, down: false });
      return;
    }
    const gap = node.scrollHeight - node.scrollTop - node.clientHeight;
    const questionTop = lastUserId ? messageOffset(node, lastUserId) : 0;
    applyJump({
      down: gap > 64,
      up: node.scrollTop > questionTop + 56,
    });
  };

  const updatePin = () => {
    if (skipPinUpdateRef.current) return;
    const node = scrollerRef.current;
    if (!node) return;
    pinToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 160;
    measureJump();
  };

  useLayoutEffect(() => {
    if (!thinking) {
      snappedTurnRef.current = false;
      return;
    }
    if (snappedTurnRef.current || !lastUserId) return;
    const node = scrollerRef.current;
    if (!node) return;
    snappedTurnRef.current = true;
    pinToBottomRef.current = false;
    skipPinUpdateRef.current = true;
    scrollToQuestion(node, lastUserId, Boolean(reduce));
    const timer = window.setTimeout(() => {
      skipPinUpdateRef.current = false;
      measureJump();
    }, 80);
    return () => window.clearTimeout(timer);
  }, [thinking, lastUserId, reduce]);

  useLayoutEffect(() => {
    if (!pinToBottomRef.current) {
      measureJump();
      return;
    }
    scrollToBottom();
  }, [messages, thinking, statusText, liveReasoning, nextChips.length]);

  useLayoutEffect(() => {
    setScrollerNode(scrollerRef.current);
  });

  // A reply that types itself out grows without `messages` changing, so the scroll
  // arrows and the pinned-to-bottom state follow the column's real height instead.
  const followRef = useRef<() => void>(() => undefined);
  followRef.current = () => {
    if (pinToBottomRef.current) scrollToBottom();
    else measureJump();
  };
  useEffect(() => {
    const column = columnRef.current;
    if (!column || typeof ResizeObserver === 'undefined') return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        followRef.current();
      });
    });
    observer.observe(column);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  const jumpToQuestion = useCallback((id: string) => {
    const node = scrollerRef.current;
    if (!node) return;
    pinToBottomRef.current = false;
    skipPinUpdateRef.current = true;
    setArriveId(id);
    scrollToQuestion(node, id, Boolean(reduce));
    window.setTimeout(() => {
      skipPinUpdateRef.current = false;
      setArriveId((current) => (current === id ? null : current));
      const gap = node.scrollHeight - node.scrollTop - node.clientHeight;
      const questionTop = messageOffset(node, id);
      applyJump({
        down: gap > 64,
        up: node.scrollTop > questionTop + 56,
      });
    }, 860);
  }, [reduce]);

  useLayoutEffect(() => {
    if (!jumpRef) return;
    jumpRef.current = jumpToQuestion;
    return () => {
      jumpRef.current = null;
    };
  }, [jumpRef, jumpToQuestion]);

  return (
    <Box sx={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', position: 'relative' }}>
    <Box
      ref={scrollerRef}
      className={thinking ? 'bt-generating' : undefined}
      onScroll={updatePin}
      onWheel={(event) => {
        if (event.deltaY < 0) pinToBottomRef.current = false;
      }}
      sx={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        overflowX: 'hidden',
        overscrollBehavior: 'contain',
        display: 'flex',
        flexDirection: 'column',
        scrollbarWidth: 'thin',
        scrollbarColor: 'var(--bt-overlay-strong) transparent',
        '&::-webkit-scrollbar': { width: 8 },
        '&::-webkit-scrollbar-track': { background: 'transparent' },
        '&::-webkit-scrollbar-thumb': { bgcolor: 'var(--bt-overlay-strong)', borderRadius: 8, border: '2px solid transparent', backgroundClip: 'padding-box' },
        '&::-webkit-scrollbar-button': { display: 'none', width: 0, height: 0 },
        '&.bt-generating .bt-edit': { display: 'none' },
        '@keyframes dialogue-arrive': {
          '0%': { boxShadow: '0 0 0 0 var(--bt-glow-strong)' },
          '35%': { boxShadow: '0 0 0 8px var(--bt-glow)' },
          '100%': { boxShadow: '0 0 0 0 transparent' },
        },
      }}
    >
      <Box ref={columnRef} sx={{
        ...CHAT_COL,
        ...(splitPane ? { maxWidth: '100%', px: { xs: 1.25, sm: 1.75 } } : {}),
        pt: HEADER_SCROLL_PAD,
        // --bt-composer-h-pad follows the measured composer dock (ChatPage); the
        // constants only cover the first paint before it is measured.
        pb: clarifyDocked
          ? { xs: `var(--bt-composer-h-pad, ${CLARIFY_SCROLL_PAD.xs})`, md: `var(--bt-composer-h-pad, ${CLARIFY_SCROLL_PAD.md})` }
          : { xs: `var(--bt-composer-h-pad, ${COMPOSER_SCROLL_PAD.xs})`, md: `var(--bt-composer-h-pad, ${COMPOSER_SCROLL_PAD.md})` },
        flexGrow: 1,
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
      }}>
        {messages.length === 0 && !thinking && (
          <Box sx={{ m: 'auto', textAlign: 'center', width: '100%', maxWidth: 480, py: 2 }}>
            <motion.div
              initial={reduce ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduce ? 0 : 0.35, ease: [0.23, 1, 0.32, 1] }}
            >
              {/* The sidebar already carries the logo on desktop; phones have no sidebar on screen. */}
              <Box sx={{ mb: 2.25, display: { xs: 'flex', md: 'none' }, justifyContent: 'center' }}>
                <BrandMark variant="empty" />
              </Box>
              {isComputer && (
                <Box
                  sx={{
                    color: 'primary.light',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    letterSpacing: '-0.01em',
                    mb: 0.75,
                  }}
                >
                  {PILOT_LABEL} включён
                </Box>
              )}
              {isStudio && (
                <Box
                  sx={{
                    color: 'primary.light',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    letterSpacing: '-0.01em',
                    mb: 0.75,
                  }}
                >
                  {STUDIO_LABEL} включена
                </Box>
              )}
              {isDocgen && (
                <Box
                  sx={{
                    color: 'primary.light',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    letterSpacing: '-0.01em',
                    mb: 0.75,
                  }}
                >
                  {DOCGEN_LABEL} включены
                </Box>
              )}
              {!isComputer && !isStudio && !isDocgen && (
                <Box sx={{ color: 'text.secondary', fontSize: '0.875rem', mb: 0.75 }}>{greeting(firstName)}</Box>
              )}
              <Box sx={{ fontSize: { xs: '1.5rem', md: '1.85rem' }, fontWeight: 600, letterSpacing: '-0.035em', mb: isComputer || isStudio || isDocgen ? 0.75 : { xs: 2.5, md: 3 }, lineHeight: 1.15, textWrap: 'balance', color: 'text.primary' }}>
                {isDocgen ? 'Что собрать?' : isStudio ? 'Что визуализируем?' : isComputer ? 'Над чем поработаем?' : 'С чего начнём?'}
              </Box>
              {(isComputer || isStudio || isDocgen) && (
              <Box sx={{ color: 'text.secondary', mb: 2.25, fontSize: '0.9375rem', mx: 'auto', maxWidth: '40ch', lineHeight: 1.5 }}>
                {isDocgen
                  ? 'Прикрепите шаблоны и базу — Word, PDF, Excel или zip. Соберёт .docx. Перед генерацией покажет план и спросит подтверждение.'
                  : isStudio
                    ? 'Прикрепите образец PPTX и ТЗ — повторит стиль и соберёт слайды. Или опишите картинку и макет.'
                    : isComputer
                      ? 'Опишите задачу своими словами. Оркестратор в песочнице разделит её на должности, подберёт подходящих ИИ-агентов и соберёт итог.'
                      : ''}
              </Box>
              )}
              {composerSlotRef && (
                <Box ref={composerSlotRef} aria-hidden sx={{ height: 'var(--bt-composer-h, 112px)', mb: 2.5 }} />
              )}
              {!isComputer && !isStudio && !isDocgen && studioAvailable && (
                <Box
                  component="button"
                  type="button"
                  aria-label={`Включить ${STUDIO_LABEL}: живой холст со слайдами, картинками и инфографикой`}
                  onClick={() => selectModel.mutate('studio')}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.25,
                    width: '100%',
                    maxWidth: 420,
                    mx: 'auto',
                    mb: 1.5,
                    px: 1.5,
                    py: 1.25,
                    minHeight: 64,
                    textAlign: 'left',
                    border: '1px solid var(--bt-line)',
                    borderRadius: '16px',
                    bgcolor: 'var(--bt-panel)',
                    color: 'text.primary',
                    font: 'inherit',
                    cursor: 'pointer',
                    transition: 'border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
                    '&:hover': { bgcolor: 'var(--bt-glow)', borderColor: 'primary.main' },
                    '&:active': { transform: 'scale(0.99)' },
                    '@media (prefers-reduced-motion: reduce)': {
                      '&:active': { transform: 'none' },
                    },
                    '&:focus-visible': {
                      outline: '2px solid',
                      outlineColor: 'primary.main',
                      outlineOffset: 2,
                    },
                  }}
                >
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '12px',
                      flexShrink: 0,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'var(--bt-glow)',
                      color: 'primary.light',
                    }}
                  >
                    <Presentation size={20} weight="bold" />
                  </Box>
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Box sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em' }}>{STUDIO_LABEL}</Box>
                    <Box sx={{ color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.4, mt: 0.2 }}>
                      Презентации, лендинг и дашборд на живом холсте
                    </Box>
                  </Box>
                </Box>
              )}
              {!isComputer && !isDocgen && computerAvailable && (
                <Box
                  component="button"
                  type="button"
                  aria-label={`Включить ${PILOT_LABEL}: оркестратор в песочнице, раздаёт должности подходящим ИИ-агентам`}
                  onClick={() => selectModel.mutate('director')}
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.25,
                    width: '100%',
                    maxWidth: 420,
                    mx: 'auto',
                    mb: 2.5,
                    px: 1.5,
                    py: 1.25,
                    minHeight: 64,
                    textAlign: 'left',
                    border: '1px solid var(--bt-line)',
                    borderRadius: '16px',
                    bgcolor: 'var(--bt-panel)',
                    color: 'text.primary',
                    font: 'inherit',
                    cursor: 'pointer',
                    transition: 'border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
                    '&:hover': { bgcolor: 'var(--bt-glow)', borderColor: 'primary.main' },
                    '&:active': { transform: 'scale(0.99)' },
                    '@media (prefers-reduced-motion: reduce)': {
                      '&:active': { transform: 'none' },
                    },
                    '&:focus-visible': {
                      outline: '2px solid',
                      outlineColor: 'primary.main',
                      outlineOffset: 2,
                    },
                  }}
                >
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '12px',
                      flexShrink: 0,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'var(--bt-glow)',
                      color: 'primary.light',
                    }}
                  >
                    <Desktop size={20} weight="bold" />
                  </Box>
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Box sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em' }}>{PILOT_LABEL}</Box>
                    <Box sx={{ color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.4, mt: 0.2 }}>
                      Раздаёт должности подходящим ИИ-агентам в песочнице
                    </Box>
                  </Box>
                  <Box
                    sx={{
                      flexShrink: 0,
                      px: 1.25,
                      py: 0.65,
                      borderRadius: '999px',
                      bgcolor: 'primary.main',
                      color: 'primary.contrastText',
                      fontSize: '0.8125rem',
                      fontWeight: 600,
                    }}
                  >
                    Включить
                  </Box>
                </Box>
              )}
              <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 0.75 }}>
                {suggestions.map((s: Suggestion) => (
                  <Box
                    key={s.label}
                    component="button"
                    type="button"
                    onClick={() => onSuggestion?.(s.text)}
                    sx={suggestionChipSx}
                  >
                    {s.icon && <s.icon size={15} aria-hidden style={{ flexShrink: 0, opacity: 0.8 }} />}
                    {s.label}
                  </Box>
                ))}
              </Box>
            </motion.div>
          </Box>
        )}

        {listMessages.map((msg) => (
          <Box
            key={msg.id}
            data-dialogue-id={msg.id}
            sx={{
              minWidth: 0,
              width: '100%',
              borderRadius: '18px',
              animation: arriveId === msg.id ? 'dialogue-arrive 0.85s cubic-bezier(0.22, 1, 0.36, 1)' : 'none',
            }}
          >
          <motion.div
            // The reply being typed needs no entrance of its own: the typing is the entrance.
            initial={msg.id === lastAssistantId && isReplyText(normalizeMarkdown(msg.content), reply) ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            style={{ minWidth: 0, width: '100%' }}
          >
            <ChatMessage
              role={msg.role}
              content={msg.content}
              file={msg.file}
              attachment={msg.attachment}
              onRemoveAttachment={msg.role === 'user' && msg.attachment && (msg.mine || !people) ? () => onRemoveAttachment?.(msg.id) : undefined}
              reasoning={msg.reasoning}
              search={msg.search}
              isLastAssistant={!thinking && msg.role === 'assistant' && msg.id === lastAssistantId}
              sourcesActive={msg.id === activeSourceId}
              onOpenSources={() => onOpenSources?.(msg.id)}
              onRegenerate={onRegenerate}
              onEdit={msg.role === 'user' && !isClarifyReply(msg.content) ? (text) => { if (!thinkingRef.current) onEditMessage?.(msg.id, text); } : undefined}
              onEditImage={onEditImage}
              onAcceptMode={(model) => selectModel.mutateAsync(model)}
              people={people}
              author={msg.author}
              mine={msg.mine}
              revealTarget={msg.id === lastAssistantId}
              touchActions={msg.id === lastAssistantId || msg.id === lastUserId}
            />
          </motion.div>
          </Box>
        ))}

        <AnimatePresence initial={false}>
          {thinking && (
            <motion.div
              key="activity"
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, transition: { duration: 0.22, ease: [0.23, 1, 0.32, 1] } }}
              // The status folds away while the answer starts, so the text slides up into its place.
              exit={{ opacity: 0, height: 0, transition: { duration: reduce ? 0 : 0.18, ease: [0.23, 1, 0.32, 1] } }}
              style={{ overflow: 'hidden' }}
            >
              {liveReasoning && (
                <Box sx={{ width: '100%' }}>
                  <ReasoningTrace reasoning={liveReasoning} live />
                </Box>
              )}
              <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 3 }}>
                <ActivityFeed statusText={statusText} />
              </Box>
            </motion.div>
          )}
        </AnimatePresence>

        {chipsHost &&
          nextChips.length > 0 &&
          createPortal(
            <Box
              key={lastAssistantId}
              sx={{
                display: 'flex',
                gap: 0.75,
                // One row that scrolls sideways on a phone; it sits right above the composer.
                flexWrap: 'nowrap',
                overflowX: 'auto',
                scrollbarWidth: 'none',
                '&::-webkit-scrollbar': { display: 'none' },
                pb: 1,
                pl: { xs: 0, sm: 0.5 },
                animation: 'bt-chips-in 0.22s cubic-bezier(0.23, 1, 0.32, 1) both',
                '@keyframes bt-chips-in': { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'none' } },
              }}
            >
              {nextChips.map((chip) => (
                <Box
                  key={chip.label}
                  component="button"
                  type="button"
                  onClick={() => onSuggestion?.(chip.text)}
                  sx={{ ...suggestionChipSx, flexShrink: 0, whiteSpace: 'nowrap', bgcolor: 'var(--bt-panel)' }}
                >
                  {chip.label}
                </Box>
              ))}
            </Box>,
            chipsHost,
          )}
        <div ref={bottomRef} />
      </Box>
    </Box>
    <DialogueRail scroller={scrollerNode} questions={questionTicks} onJump={jumpToQuestion} />
    {visibleMessages.length > 0 && (jump.up || jump.down) && (
      <Box
        sx={{
          position: 'absolute',
          zIndex: 3,
          right: splitPane ? 12 : { xs: 12, md: 'max(12px, calc((100% - 768px) / 2 - 4px))', xl: 'max(12px, calc((100% - 880px) / 2 - 4px))' },
          // Above the composer; on phones also above the «Вопросы» chip that sits on it.
          bottom: {
            xs: questionTicks.length >= MIN_DIALOGUE_QUESTIONS
              ? 'calc(var(--bt-composer-h, 140px) + 66px)'
              : 'calc(var(--bt-composer-h, 140px) + 8px)',
            md: 'calc(var(--bt-composer-h, 148px) + 8px)',
          },
          display: 'flex',
          flexDirection: 'column',
          border: '1px solid var(--bt-hairline)',
          borderRadius: '14px',
          bgcolor: 'var(--bt-elevated)',
          boxShadow: 'var(--bt-shadow)',
          overflow: 'hidden',
        }}
      >
        <IconButton
          size="small"
          disabled={!jump.up || !lastUserId}
          onClick={() => lastUserId && jumpToQuestion(lastUserId)}
          aria-label="К вопросу"
          sx={{
            width: 40,
            height: 40,
            borderRadius: 0,
            color: 'text.secondary',
            '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay-faint)' },
            '&.Mui-disabled': { color: 'text.disabled' },
          }}
        >
          <CaretUp size={18} weight="bold" />
        </IconButton>
        <Box sx={{ height: '1px', bgcolor: 'var(--bt-hairline)' }} />
        <IconButton
          size="small"
          disabled={!jump.down}
          onClick={scrollToBottom}
          aria-label="К концу ответа"
          sx={{
            width: 40,
            height: 40,
            borderRadius: 0,
            color: 'text.secondary',
            '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay-faint)' },
            '&.Mui-disabled': { color: 'text.disabled' },
          }}
        >
          <CaretDown size={18} weight="bold" />
        </IconButton>
      </Box>
    )}
    </Box>
  );
}
