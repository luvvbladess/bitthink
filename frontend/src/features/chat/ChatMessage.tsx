import { memo, useMemo, useRef, useState, type ReactNode } from 'react';
import { Box, IconButton, TextField, Tooltip } from '@mui/material';
import { Copy, Check, FileArrowDown, ArrowClockwise, PencilSimple, X } from '@phosphor-icons/react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { downloadBlob } from '@/api/client';
import { DocumentAttachment, AttachmentInfo } from './DocumentAttachment';
import { UserAvatar } from '@/components/UserAvatar';
import { BrandIcon } from '@/components/BrandMark';
import { BRAND_NAME } from '@/brand';
import { ChatImage } from './ChatImage';
import { CLARIFY_ACK, isClarifyReply, splitSearch } from './clarify';
import { modeSwitchFromSearch } from './modeSwitch';
import { ModeSwitchCard } from './ModeSwitchCard';
import { parseSources } from './sources';
import { SourcesCountButton } from './SourcesPanel';
import { ReasoningTrace, SearchItem } from './ReasoningTrace';
import { normalizeMarkdown } from './markdownText';
import { isReplyText, useReplySnapshot, useRevealShown } from './replyReveal';
import '@/theme/highlight.css';

/** Module-level on purpose: a component created inside render is a new type on every
 *  render, React remounts it, and a table loses its horizontal scroll position. */
function MarkdownTable({ children }: { children?: ReactNode }) {
  return (
    <Box
      sx={{
        my: 1.5,
        overflowX: 'auto',
        border: '1px solid var(--bt-hairline)',
        borderRadius: '12px',
      }}
    >
      <table>{children}</table>
    </Box>
  );
}

interface Props {
  role: 'user' | 'assistant';
  content: string;
  file?: { filename: string; data: string };
  attachment?: AttachmentInfo;
  onRemoveAttachment?: () => void;
  reasoning?: string;
  search?: SearchItem[];
  isLastAssistant?: boolean;
  onRegenerate?: () => void;
  onEdit?: (newContent: string) => void;
  sourcesActive?: boolean;
  onOpenSources?: () => void;
  onEditImage?: (url: string) => void;
  onAcceptMode?: (model: string) => void;
  people?: boolean;
  author?: { name: string; avatar_url?: string | null } | null;
  mine?: boolean;
  /** The newest assistant message. If it is the reply that is arriving, its text is typed out. */
  revealTarget?: boolean;
  /** Phones have no hover: only the newest message of each side keeps its action buttons on screen. */
  touchActions?: boolean;
}

const ALLOWED_IMAGE_DATA_URI = /^data:image\/(png|jpe?g|gif|webp);base64,/i;

function sanitizeUrl(url: string): string {
  if (ALLOWED_IMAGE_DATA_URI.test(url)) return url;
  if (/^https?:\/\//i.test(url)) return url;
  if (/^mailto:/i.test(url)) return url;
  if (url.startsWith('#') && !/\.(xlsx|xls|csv|docx|pdf|zip)(\?|$)/i.test(url)) return url;
  if (url.startsWith('/uploads/')) return url;
  return '';
}

const DOWNLOAD_MIME: Record<string, string> = {
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  xls: 'application/vnd.ms-excel',
  csv: 'text/csv',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
  zip: 'application/zip',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
};

function downloadFile(filename: string, data: string) {
  const byteChars = atob(data);
  const byteNumbers = new Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) byteNumbers[i] = byteChars.charCodeAt(i);
  const ext = (filename.split('.').pop() || '').toLowerCase();
  const blob = new Blob([new Uint8Array(byteNumbers)], {
    type: DOWNLOAD_MIME[ext] || 'application/octet-stream',
  });
  downloadBlob(blob, filename || 'file');
}

async function copyToClipboard(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

/** ChatGPT/Claude-style code block: language label + copy button above the
 * highlighted code. Overrides ReactMarkdown's default bare <pre><code>. */
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  const codeEl = Array.isArray(children) ? children[0] : children;
  const className: string = (codeEl as any)?.props?.className || '';
  const lang = /language-(\w+)/.exec(className)?.[1] || '';

  const handleCopy = async () => {
    try {
      await copyToClipboard(preRef.current?.textContent || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Copy failed silently.
    }
  };

  return (
    <Box
      sx={{
        my: 1.5,
        borderRadius: '14px',
        overflow: 'hidden',
        border: '1px solid var(--bt-overlay-faint)',
        bgcolor: 'var(--bt-panel)',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 1.5,
          py: 0.55,
          bgcolor: 'transparent',
        }}
      >
        <Box
          component="span"
          sx={{
            fontSize: '0.75rem',
            color: 'text.muted',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
          }}
        >
          {lang || 'code'}
        </Box>
        <Tooltip title={copied ? 'Скопировано' : 'Скопировать код'}>
          <IconButton size="small" onClick={handleCopy} aria-label="Скопировать код" sx={{ color: 'text.muted', p: 0.5 }}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </IconButton>
        </Tooltip>
      </Box>
      <Box
        component="pre"
        ref={preRef}
        sx={{
          m: 0,
          bgcolor: 'transparent',
          color: 'text.primary',
          p: 2,
          pt: 0.5,
          overflow: 'auto',
          fontSize: '0.875rem',
          '& .hljs': { background: 'transparent', padding: 0, color: 'inherit' },
        }}
      >
        {children}
      </Box>
    </Box>
  );
}

const HIGHLIGHT = [rehypeHighlight];
const NO_PLUGINS: never[] = [];

type MdNode = { type: string; value?: string; children?: MdNode[] };

/** A single newline is a line break in a chat ("two lines" must show as two lines), not a space. */
function softBreaks() {
  const walk = (node: MdNode) => {
    if (!node.children) return;
    node.children = node.children.flatMap((child): MdNode[] => {
      if (child.type !== 'text' || !child.value?.includes('\n')) {
        walk(child);
        return [child];
      }
      return child.value
        .split('\n')
        .flatMap((part, index): MdNode[] =>
          index ? [{ type: 'break' }, { type: 'text', value: part }] : [{ type: 'text', value: part }],
        );
    });
  };
  return walk;
}

const REMARK = [remarkGfm, softBreaks];

function Markdown({ text, components, highlight = true }: { text: string; components: Components; highlight?: boolean }) {
  return (
    <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={highlight ? HIGHLIGHT : NO_PLUGINS} urlTransform={sanitizeUrl} components={components}>
      {text}
    </ReactMarkdown>
  );
}

/** The one place that follows the typing at ~30 fps; the rest of the chat does not re-render with it. */
function RevealedMarkdown({ full, components }: { full: string; components: Components }) {
  const shown = useRevealShown();
  const typing = shown < full.length;
  // Code is coloured once the text is complete: highlighting on every step is the costliest part of re-parsing.
  return <Markdown text={typing ? full.slice(0, shown) : full} components={components} highlight={!typing} />;
}

const ChatMessageView = memo(function ChatMessageView({
  role,
  content,
  file,
  attachment,
  onRemoveAttachment,
  reasoning,
  search,
  isLastAssistant,
  onRegenerate,
  onEdit,
  sourcesActive,
  onOpenSources,
  onEditImage,
  onAcceptMode,
  people = false,
  author,
  mine = false,
  revealTarget = false,
  touchActions = false,
}: Props) {
  const isUser = role === 'user';
  const alignEnd = people ? isUser && mine : isUser;
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(content);
  const { sources } = splitSearch(search);
  const parsedSources = parseSources(sources);
  const modeSwitch = !isUser ? modeSwitchFromSearch(search) : null;
  // Stable between renders (scrolling re-renders the list): see MarkdownTable.
  const mdComponents = useMemo(
    () =>
      ({
        pre: CodeBlock,
        table: MarkdownTable,
        img: ({ src, alt }: { src?: string | Blob; alt?: string }) =>
          typeof src === 'string' && src ? (
            <ChatImage
              src={src}
              alt={alt}
              onEdit={src.startsWith('/uploads/') && onEditImage ? () => onEditImage(src) : undefined}
            />
          ) : null,
      }) as Components,
    [onEditImage],
  );
  const visibleContent = isUser && isClarifyReply(content) ? CLARIFY_ACK : content;
  // A reply can carry several files (Pilot writes a set of documents); every one
  // gets its own card. Only the first one used to be drawn.
  const attachmentItems: AttachmentInfo[] = attachment ? (attachment.files?.length ? attachment.files : [attachment]) : [];
  // An upload's message text is just the file name; a reply's text is the answer
  // itself and belongs above its files.
  const trimmedContent = (visibleContent || '').trim();
  const textBesideFiles = Boolean(trimmedContent) && !attachmentItems.some((item) => item.name === trimmedContent);
  // Typed on the cleaned text, so the source list cut off at the end never flashes mid-reply.
  const cleanContent = useMemo(() => normalizeMarkdown(visibleContent), [visibleContent]);
  const reply = useReplySnapshot(revealTarget && !isUser);
  const revealing = revealTarget && !isUser && isReplyText(cleanContent, reply);
  const typing = revealing && reply.typing;

  const handleCopy = async () => {
    try {
      await copyToClipboard(visibleContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Copy failed silently.
    }
  };

  const startEdit = () => {
    setEditValue(content);
    setEditing(true);
  };

  const saveEdit = () => {
    const trimmed = editValue.trim();
    setEditing(false);
    if (trimmed && trimmed !== content) onEdit?.(trimmed);
  };

  return (
    <Box
      className="chat-message-row"
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: alignEnd ? 'flex-end' : 'flex-start',
        width: '100%',
        minWidth: 0,
        // Clip only user bubbles; assistant lists need room for 10.+ markers.
        overflowX: isUser ? 'clip' : 'visible',
        mb: isUser ? 1.5 : 2,
      }}
    >
      {people && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.5, flexDirection: alignEnd ? 'row-reverse' : 'row' }}>
          {isUser ? (
            <UserAvatar user={{ first_name: author?.name, avatar_url: author?.avatar_url }} sx={{ width: 28, height: 28, fontSize: '0.8rem' }} />
          ) : (
            <BrandIcon size={28} />
          )}
          <Box component="span" sx={{ fontSize: '0.75rem', fontWeight: 600, color: 'text.secondary' }}>
            {isUser ? (author?.name || 'Участник') : BRAND_NAME}
          </Box>
        </Box>
      )}
      {!isUser && <ReasoningTrace reasoning={reasoning} />}
      {attachment && !textBesideFiles ? null : editing ? (
        <Box sx={{ width: '100%', maxWidth: { xs: '92%', md: '78%' } }}>
          <TextField
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            fullWidth
            multiline
            autoFocus
            minRows={1}
            maxRows={10}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                saveEdit();
              }
              if (e.key === 'Escape') setEditing(false);
            }}
          />
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, mt: 1 }}>
            <IconButton size="small" onClick={() => setEditing(false)} aria-label="Отменить редактирование" sx={{ color: 'text.muted' }}>
              <X size={16} />
            </IconButton>
            <IconButton size="small" onClick={saveEdit} aria-label="Отправить исправленное сообщение" sx={{ color: 'primary.contrastText', bgcolor: 'primary.main', borderRadius: 1, '&:hover': { bgcolor: 'primary.dark' } }}>
              <Check size={16} />
            </IconButton>
          </Box>
        </Box>
      ) : (
        <Box
          className={typing ? 'bt-typing' : undefined}
          aria-busy={typing || undefined}
          sx={{
            minWidth: 0,
            width: isUser ? 'auto' : '100%',
            maxWidth: isUser ? { xs: '88%', md: '70%' } : '100%',
            px: isUser ? 1.75 : 0,
            py: isUser ? 1.1 : 0.25,
            borderRadius: isUser ? '18px' : 0,
            backgroundColor: isUser ? 'background.paper' : 'transparent',
            color: 'text.primary',
            fontSize: isUser ? '0.9375rem' : '1rem',
            fontWeight: 400,
            letterSpacing: 'normal',
            lineHeight: isUser ? 1.5 : 1.7,
            overflowWrap: 'anywhere',
            border: 'none',
            boxShadow: 'none',
            '& p': { m: 0, lineHeight: isUser ? 1.5 : 1.7 },
            '& p + p': { mt: 1.2 },
            '& code': {
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              fontSize: '0.875em',
            },
            '& :not(pre) > code': {
              bgcolor: 'var(--bt-hairline)',
              px: 0.6,
              py: 0.2,
              borderRadius: 1,
            },
            // Reading rhythm for longer answers: clear heading steps, quiet quotes, no side stripes.
            '& h1, & h2, & h3, & h4': { fontWeight: 600, letterSpacing: '-0.015em', lineHeight: 1.3, color: 'text.primary' },
            '& h1': { fontSize: '1.375rem', mt: 3, mb: 1.25 },
            '& h2': { fontSize: '1.1875rem', mt: 2.75, mb: 1 },
            '& h3': { fontSize: '1.0625rem', mt: 2.25, mb: 0.75 },
            '& h4': { fontSize: '1rem', mt: 2, mb: 0.5 },
            '& > :first-child': { mt: 0 },
            '& strong': { fontWeight: 600 },
            '& a': { color: 'primary.light', textDecorationColor: 'var(--bt-line)', textUnderlineOffset: '3px' },
            '& a:hover': { textDecorationColor: 'currentColor' },
            '& blockquote': {
              m: 0,
              my: 1.5,
              px: 2,
              py: 1.25,
              borderRadius: '12px',
              bgcolor: 'var(--bt-overlay-faint)',
              color: 'text.secondary',
            },
            '& blockquote > :first-child': { mt: 0 },
            '& blockquote > :last-child': { mb: 0 },
            '& hr': { border: 0, borderTop: '1px solid var(--bt-hairline)', my: 3 },
            '& li::marker': { color: 'var(--bt-ink-muted)' },
            '& ul': { pl: 2.5, my: 1 },
            // Outside markers + room for two-digit (and short three-digit) numbers.
            '& ol': { pl: 3.75, my: 1, listStylePosition: 'outside' },
            '& li': { mb: 0.5 },
            '& li:empty, & li:has(> p:only-child:empty)': { display: 'none' },
            // overflow-wrap:anywhere (set above) shrinks cell min-width to one letter and
            // splits words mid-way. Cells wrap only when a word really cannot fit.
            '& table': {
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.875rem',
              lineHeight: 1.5,
            },
            '& th, & td': {
              borderBottom: '1px solid var(--bt-hairline)',
              px: 1.5,
              py: 1,
              textAlign: 'left',
              verticalAlign: 'top',
              overflowWrap: 'break-word',
              wordBreak: 'normal',
            },
            '& th': { bgcolor: 'var(--bt-overlay-faint)', fontWeight: 600, whiteSpace: 'nowrap' },
            '& tr:last-child td': { borderBottom: 'none' },
            // Typing caret: solid, and only while the text is being laid out. It rides the last text block.
            '&.bt-typing > :is(p, h1, h2, h3, h4):last-child::after, &.bt-typing > :is(ul, ol):last-child > li:last-child::after, &.bt-typing > blockquote:last-child > p:last-child::after': {
              content: '""',
              display: 'inline-block',
              width: '2px',
              height: '1.05em',
              ml: '3px',
              verticalAlign: '-0.17em',
              borderRadius: '1px',
              bgcolor: 'primary.main',
            },
          }}
        >
          {revealing ? (
            <RevealedMarkdown full={reply.full} components={mdComponents} />
          ) : (
            <Markdown text={cleanContent} components={mdComponents} />
          )}
          {modeSwitch && onAcceptMode && (
            <ModeSwitchCard suggestion={modeSwitch} onAccept={() => onAcceptMode(modeSwitch.model)} />
          )}
        </Box>
      )}
      {attachmentItems.length > 0 && (
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: alignEnd ? 'flex-end' : 'flex-start',
            gap: 1,
            mt: textBesideFiles && !editing ? 1.25 : 0,
            width: '100%',
            minWidth: 0,
          }}
        >
          {attachmentItems.map((item, index) =>
            item.type === 'image' && item.status === 'done' && item.url ? (
              <ChatImage
                key={`${item.url}-${index}`}
                src={item.url}
                alt={item.name}
                onEdit={item.url.startsWith('/uploads/') && onEditImage ? () => onEditImage(item.url!) : undefined}
                onRemove={attachmentItems.length === 1 ? onRemoveAttachment : undefined}
              />
            ) : (
              <DocumentAttachment
                key={`${item.name}-${index}`}
                {...item}
                onRemoveFromContext={attachmentItems.length === 1 ? onRemoveAttachment : undefined}
              />
            ),
          )}
        </Box>
      )}
      {visibleContent && !editing && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            mt: 0.5,
            opacity: { xs: touchActions ? 1 : 0, md: 0 },
            pointerEvents: { xs: touchActions ? 'auto' : 'none', md: 'none' },
            transition: 'opacity 0.2s',
            '.chat-message-row:hover &, .chat-message-row:focus-within &': {
              opacity: 1,
              pointerEvents: 'auto',
            },
          }}
        >
          {isUser ? (
            onEdit && !isClarifyReply(content) && (
              <Tooltip title="Изменить">
                <IconButton size="small" onClick={startEdit} aria-label="Изменить сообщение" className="bt-edit" sx={{ color: 'text.muted', p: { xs: 1.1, md: 0.5 } }}>
                  <PencilSimple size={14} />
                </IconButton>
              </Tooltip>
            )
          ) : (
            <>
              <Tooltip title={copied ? 'Скопировано' : 'Скопировать'}>
                <IconButton
                  size="small"
                  onClick={handleCopy}
                  aria-label="Скопировать сообщение"
                  sx={{ color: 'text.muted', p: { xs: 1.1, md: 0.5 } }}
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                </IconButton>
              </Tooltip>
              {file && (
                <Tooltip title="Скачать файл">
                  <IconButton
                    size="small"
                    onClick={() => downloadFile(file.filename, file.data)}
                    aria-label="Скачать файл"
                    sx={{ color: 'text.muted', p: { xs: 1.1, md: 0.5 } }}
                  >
                    <FileArrowDown size={14} />
                  </IconButton>
                </Tooltip>
              )}
              {isLastAssistant && onRegenerate && !modeSwitch && (
                <Tooltip title="Повторить ответ">
                  <IconButton size="small" onClick={onRegenerate} aria-label="Повторить ответ" sx={{ color: 'text.muted', p: { xs: 1.1, md: 0.5 } }}>
                    <ArrowClockwise size={14} />
                  </IconButton>
                </Tooltip>
              )}
            </>
          )}
        </Box>
      )}
      {!isUser && !editing && parsedSources.length > 0 && (
        <Box sx={{ display: 'flex', alignItems: 'center', mt: 0.75 }}>
          <SourcesCountButton count={parsedSources.length} active={sourcesActive} onClick={() => onOpenSources?.()} />
        </Box>
      )}
    </Box>
  );
});

/**
 * The list re-renders on every state change around a reply (sent, answered, saved, refetched).
 * Without this each of those re-parsed the markdown of every message in the chat. The handlers
 * the parent passes are new functions on every render, so the view gets stable ones that call
 * the latest through a ref; only whether a handler exists (it decides which buttons show) is
 * passed down as a prop.
 */
export function ChatMessage(props: Props) {
  const latest = useRef(props);
  latest.current = props;
  const call = useMemo(
    () => ({
      onRemoveAttachment: () => latest.current.onRemoveAttachment?.(),
      onRegenerate: () => latest.current.onRegenerate?.(),
      onEdit: (text: string) => latest.current.onEdit?.(text),
      onOpenSources: () => latest.current.onOpenSources?.(),
      onEditImage: (url: string) => latest.current.onEditImage?.(url),
      onAcceptMode: (model: string) => latest.current.onAcceptMode?.(model),
    }),
    [],
  );
  return (
    <ChatMessageView
      {...props}
      onRemoveAttachment={props.onRemoveAttachment && call.onRemoveAttachment}
      onRegenerate={props.onRegenerate && call.onRegenerate}
      onEdit={props.onEdit && call.onEdit}
      onOpenSources={props.onOpenSources && call.onOpenSources}
      onEditImage={props.onEditImage && call.onEditImage}
      onAcceptMode={props.onAcceptMode && call.onAcceptMode}
    />
  );
}
