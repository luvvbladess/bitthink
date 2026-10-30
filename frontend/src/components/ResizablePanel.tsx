import { useState, type ReactNode } from 'react';
import { Box, Button } from '@mui/material';
import { ArrowsOut, ArrowsIn } from '@phosphor-icons/react';

/** A shared desktop panel; pointer capture keeps resizing over embedded canvases. */
export function ResizablePanel({ children, expanded, onExpand, label }: {
  children: ReactNode; expanded: boolean; onExpand: (value: boolean) => void; label: string;
}) {
  const [width, setWidth] = useState(60);
  const clamp = (value: number) => Math.min(76, Math.max(36, value));
  return <Box sx={{ position: 'relative', flex: expanded ? '1 1 100%' : `0 0 ${width}%`, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--bt-hairline)' }}>
    {!expanded && <Box role="separator" aria-label={`Ширина панели: ${label}`} aria-orientation="vertical" aria-valuemin={36} aria-valuemax={76} aria-valuenow={Math.round(width)} tabIndex={0}
      onDoubleClick={() => setWidth(60)}
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        setWidth(value => event.key === 'Home' ? 36 : event.key === 'End' ? 76 : clamp(value + (event.key === 'ArrowLeft' ? 2 : -2)));
      }}
      onPointerDown={event => { if (event.button === 0) { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); } }}
      onPointerMove={event => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const bounds = event.currentTarget.parentElement?.parentElement?.getBoundingClientRect();
        if (bounds?.width) setWidth(clamp((bounds.right - event.clientX) / bounds.width * 100));
      }}
      onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
      sx={{ position: 'absolute', left: -5, top: 0, bottom: 0, width: 10, zIndex: 5, cursor: 'col-resize', touchAction: 'none', '&:hover, &:focus-visible': { bgcolor: 'var(--bt-glow-strong)', outline: '2px solid var(--bt-accent, #21a0ce)' } }} />}
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', borderBottom: '1px solid var(--bt-hairline)', px: 1, flexShrink: 0 }}>
      <Button onClick={() => onExpand(!expanded)} startIcon={expanded ? <ArrowsIn size={16} /> : <ArrowsOut size={16} />} sx={{ minHeight: 36, color: 'text.secondary', fontSize: '0.8125rem' }}>{expanded ? 'Вернуть чат' : 'Развернуть на всю ширину'}</Button>
    </Box>
    {children}
  </Box>;
}
