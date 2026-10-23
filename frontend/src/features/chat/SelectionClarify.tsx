import { useEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Box, Button } from '@mui/material';
import { ChatCircleDots, Sparkle } from '@phosphor-icons/react';

export type TextSelection = { text: string; start: number; end: number; messageId?: string };
type Pick = TextSelection & { left: number; top: number };
export const MAX_CLARIFY_CHARS = 6000;

/** One listener for the transcript, restricted to a single finished assistant text. */
export function SelectionClarify({ rootRef, onClarify, onEdit, canEdit }: { rootRef: RefObject<HTMLDivElement | null>; onClarify?: (text: string) => void; onEdit?: (selection: TextSelection) => void; canEdit?: (selection: TextSelection) => boolean }) {
  const [pick, setPick] = useState<Pick | null>(null);
  const callback = useRef({ onClarify, onEdit }); callback.current = { onClarify, onEdit };
  useEffect(() => {
    let timer = 0, dragging = false;
    const hide = () => { window.clearTimeout(timer); setPick(null); };
    const inspect = () => {
      if (dragging) return;
      const selection = window.getSelection(), root = rootRef.current;
      if (!selection || selection.isCollapsed || selection.rangeCount !== 1 || !root) { setPick(null); return; }
      const range = selection.getRangeAt(0);
      const container = (node: Node) => (node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement)?.closest('[data-clarify-text]');
      const start = container(range.startContainer), end = container(range.endContainer);
      const text = selection.toString().trim();
      if (!text || !start || start !== end || !root.contains(start)) { setPick(null); return; }
      const rects = Array.from(range.getClientRects()).filter(r => r.width && r.height);
      const bounds = root.getBoundingClientRect(), viewport = window.visualViewport;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
      const rect = rects.find(r => r.bottom >= Math.max(bounds.top, top + 56) && r.top <= Math.min(bounds.bottom, top + height));
      if (!rect) { setPick(null); return; }
      const prefix = range.cloneRange(); prefix.selectNodeContents(start); prefix.setEnd(range.startContainer, range.startOffset);
      const leading = selection.toString().length - selection.toString().trimStart().length;
      const offset = Array.from(prefix.toString() + selection.toString().slice(0, leading)).length;
      setPick({ text, start: offset, end: offset + Array.from(text).length, messageId: start.closest<HTMLElement>('[data-dialogue-id]')?.dataset.dialogueId, left: Math.max(left + 12, Math.min(rect.left, left + width - (callback.current.onEdit && callback.current.onClarify ? 284 : 204))),
        top: Math.max(top + 64, Math.min(rect.top >= top + 108 ? rect.top - 44 : rect.bottom + 8, top + height - 48)) });
    };
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(inspect, 120); };
    const down = (event: PointerEvent) => { if (event.pointerType === 'mouse') { dragging = true; hide(); } };
    const up = () => { dragging = false; schedule(); };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') hide(); else schedule(); };
    document.addEventListener('selectionchange', schedule);
    rootRef.current?.addEventListener('pointerdown', down);
    document.addEventListener('pointerup', up);
    document.addEventListener('keyup', key);
    document.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    window.addEventListener('blur', hide);
    window.visualViewport?.addEventListener('resize', hide);
    window.visualViewport?.addEventListener('scroll', hide);
    const root = rootRef.current;
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('selectionchange', schedule); root?.removeEventListener('pointerdown', down);
      document.removeEventListener('pointerup', up); document.removeEventListener('keyup', key);
      document.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide);
      window.removeEventListener('blur', hide); window.visualViewport?.removeEventListener('resize', hide); window.visualViewport?.removeEventListener('scroll', hide);
    };
  }, [rootRef]);
  if (!pick) return null;
  const tooLong = Array.from(pick.text).length > MAX_CLARIFY_CHARS;
  const edit = Boolean(onEdit && (!canEdit || canEdit(pick)));
  const action = (kind: 'clarify' | 'edit') => {
    if (kind === 'edit') callback.current.onEdit?.(pick); else callback.current.onClarify?.(pick.text);
    window.getSelection()?.removeAllRanges(); setPick(null);
  };
  const buttonSx = { minHeight: 36, borderRadius: '8px', px: 1.25, color: 'text.primary',
    '&:hover': { bgcolor: 'var(--bt-overlay-faint)' } };
  return createPortal(<Box role="group" aria-label="Действия с выделенным текстом"
    sx={{ position: 'fixed', left: pick.left, top: pick.top, zIndex: theme => theme.zIndex.tooltip,
      display: 'flex', gap: .25, p: .25, maxWidth: 'calc(100vw - 24px)', borderRadius: '10px',
      bgcolor: 'var(--bt-elevated)', border: '1px solid var(--bt-line)' }}>
    {tooLong ? <Button size="small" disabled aria-label="Выделите фрагмент до 6000 символов" sx={buttonSx}>До 6 000 символов</Button> : <>
      {onClarify && <Button size="small" startIcon={<ChatCircleDots size={17} />} aria-label="Уточнить выделенный фрагмент" onMouseDown={e => e.preventDefault()} onClick={() => action('clarify')} sx={buttonSx}>Уточнить</Button>}
      {edit && <Button size="small" startIcon={<Sparkle size={17} />} aria-label="Изменить выделенный фрагмент с ИИ" onMouseDown={e => e.preventDefault()} onClick={() => action('edit')} sx={buttonSx}>Изменить с ИИ</Button>}
    </>}
  </Box>, document.body);
}
