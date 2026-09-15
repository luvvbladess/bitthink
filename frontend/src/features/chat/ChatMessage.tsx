import { useRef, useState } from 'react';
import { Box, IconButton, TextField, Tooltip } from '@mui/material';
import { Copy, Check, FileArrowDown, ArrowClockwise, PencilSimple, X } from '@phosphor-icons/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { downloadBlob } from '@/api/client';
import { DocumentAttachment, AttachmentInfo } from './DocumentAttachment';
import { ChatImage } from './ChatImage';
import { CLARIFY_ACK, isClarifyReply, splitSearch } from './clarify';
import { parseSources } from './sources';
import { SourcesCountButton } from './SourcesPanel';
import { ReasoningTrace, SearchItem } from './ReasoningTrace';
import '@/theme/highlight.css';

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
}

const ALLOWED_IMAGE_DATA_URI = /^data:image\/(png|jpe?g|gif|webp);base64,/i;

function normalizeMarkdown(text: string): string {
  const sourceHeading = /^(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?(?:источники|sources)\s*:?\s*(?:\*{1,2}|_{1,2})?\s*$/i;
  const sourceItem = /^(?:[-*+•‣∙·]|\d+[.)])?\s*(?:\*{1,2}|_{1,2})?источник(?:и)?\b/i;
  const sourceList = /^(?:[-*+•‣∙·]|\d+[.)])\s*(?:\[[^\]]+\]\(https?:\/\/|<?https?:\/\/|\[\d+\])/i;
  const isSourceLine = (line: string) => {
    const stripped = line.trim();
    return !stripped || sourceHeading.test(stripped) || sourceItem.test(stripped) || sourceList.test(stripped) || /^\[\d+\]\s+/.test(stripped);
  };
  const lines = text.split('\n');
  let cut = lines.length;
  for (let index = 0; index < lines.length; index += 1) {
    const stripped = lines[index].trim();
    if (!stripped) continue;
    if ((sourceHeading.test(stripped) || sourceItem.test(stripped) || sourceList.test(stripped)) && lines.slice(index).every(isSourceLine)) {
      cut = index;
      break;
    }
  }
  const kept = lines.slice(0, cut);
  while (kept.length && !kept[kept.length - 1].trim()) kept.pop();
  return kept
    .join('\n')
    .replace(/^[ \t]*[•‣∙·][ \t]+/gm, '- ')
    .replace(/^[ \t]*(?:[-*+•‣∙·]|\d+[.)])[ \t]*$/gm, '')
    .replace(/\[([^\]]+)\]\(https?:\/\/[^)]+\)/g, '$1')
    .replace(/(?<!\()https?:\/\/[^\s<>)\]]+/g, '')
    .replace(/\s*\[\d+\]/g, '')
    .replace(/\s*\((?:www\.)?(?:[a-z0-9-]+\.)+(?:xn--[a-z0-9-]+|[a-z]{2,24})(?:\/[^\s)]*)?\)/gi, '')
    .replace(/\(xn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+\)/gi, '')
    .replace(/\bxn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+\b/gi, '')
    .replace(/([A-Za-zА-Яа-яЁё])\.[\u0530-\u058F\u10A0-\u10FF\u0600-\u06FF\u0590-\u05FF\u0900-\u097F\u4E00-\u9FFF\u3040-\u30FF]+/g, '$1')
    .replace(/\n{3,}/g, '\n\n');
}

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

export function ChatMessage({
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
}: Props) {
  const isUser = role === 'user';
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(content);
  const { sources } = splitSearch(search);
  const parsedSources = parseSources(sources);
  const visibleContent = isUser && isClarifyReply(content) ? CLARIFY_ACK : content;

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
        alignItems: isUser ? 'flex-end' : 'flex-start',
        width: '100%',
        minWidth: 0,
        // Clip only user bubbles; assistant lists need room for 10.+ markers.
        overflowX: isUser ? 'clip' : 'visible',
        mb: isUser ? 1.5 : 2,
      }}
    >
      {!isUser && <ReasoningTrace reasoning={reasoning} />}
      {attachment ? (
        attachment.type === 'image' && attachment.status === 'done' && attachment.url ? (
          <ChatImage
            src={attachment.url}
            alt={attachment.name}
            onEdit={attachment.url.startsWith('/uploads/') && onEditImage ? () => onEditImage(attachment.url!) : undefined}
            onRemove={onRemoveAttachment}
          />
        ) : (
          <DocumentAttachment {...attachment} onRemoveFromContext={onRemoveAttachment} />
        )
      ) : editing ? (
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
            '& ul': { pl: 2.5, my: 1 },
            // Outside markers + room for two-digit (and short three-digit) numbers.
            '& ol': { pl: 3.75, my: 1, listStylePosition: 'outside' },
            '& li': { mb: 0.5 },
            '& li:empty, & li:has(> p:only-child:empty)': { display: 'none' },
            '& table': {
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.875rem',
              my: 1.5,
            },
            '& th, & td': { border: '1px solid var(--bt-hairline)', p: 1 },
            '& th': { bgcolor: 'var(--bt-overlay-faint)' },
          }}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            urlTransform={sanitizeUrl}
            components={{
              pre: CodeBlock,
              img: ({ src, alt }) =>
                src ? (
                  <ChatImage
                    src={src}
                    alt={alt}
                    onEdit={src.startsWith('/uploads/') && onEditImage ? () => onEditImage(src) : undefined}
                  />
                ) : null,
            }}
          >
            {normalizeMarkdown(visibleContent)}
          </ReactMarkdown>
        </Box>
      )}
      {visibleContent && !editing && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            mt: 0.5,
            opacity: { xs: 1, md: 0 },
            pointerEvents: { xs: 'auto', md: 'none' },
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
                <IconButton size="small" onClick={startEdit} aria-label="Изменить сообщение" sx={{ color: 'text.muted' }}>
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
                  sx={{ color: 'text.muted' }}
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
                    sx={{ color: 'text.muted' }}
                  >
                    <FileArrowDown size={14} />
                  </IconButton>
                </Tooltip>
              )}
              {isLastAssistant && onRegenerate && (
                <Tooltip title="Повторить ответ">
                  <IconButton size="small" onClick={onRegenerate} aria-label="Повторить ответ" sx={{ color: 'text.muted' }}>
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
}
