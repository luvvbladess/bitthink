import { useState, type ReactNode } from 'react';
import { Box, Button, IconButton, Popover, Typography } from '@mui/material';
import { MagnifyingGlass } from '@phosphor-icons/react';
import type { ParsedSource } from './sources';

export type ProjectCitation = { projectId: string; entryId: string; revision: number; offset: number };
export function projectCitation(href?: string): ProjectCitation | null {
  const match = /^#project\/([a-f0-9]{32})\/([a-f0-9]{32})\/(\d+)\/(\d+)$/.exec(href || '');
  return match ? { projectId: match[1], entryId: match[2], revision: Number(match[3]), offset: Number(match[4]) } : null;
}

export function EvidenceLink({ href, children, sources, onProject }: { href?: string; children?: ReactNode; sources: ParsedSource[]; onProject?: (source: ProjectCitation) => void }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const local = projectCitation(href);
  const source = sources.find(item => item.url === href);
  if (local) return <Box component="button" type="button" onClick={() => onProject?.(local)} disabled={!onProject}
    sx={{ border: 0, p: 0, bgcolor: 'transparent', color: 'primary.light', font: 'inherit', textDecoration: 'underline', textUnderlineOffset: '3px', cursor: 'pointer' }}>{children}</Box>;
  return <>
    <a href={href} target={href?.startsWith('http') ? '_blank' : undefined} rel="noreferrer">{children}</a>
    {source && <IconButton size="small" aria-label={`Подтверждение: ${source.title}`} onClick={e => setAnchor(e.currentTarget)} sx={{ color: 'text.secondary', verticalAlign: 'middle', p: .5 }}><MagnifyingGlass size={13} /></IconButton>}
    <Popover open={Boolean(anchor)} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      slotProps={{ paper: { sx: { p: 2, width: 380, maxWidth: 'calc(100vw - 32px)', maxHeight: '65dvh', bgcolor: 'var(--bt-elevated)', backgroundImage: 'none' } } }}>
      <Typography sx={{ fontSize: 14, fontWeight: 600, overflowWrap: 'anywhere' }}>{source?.title}</Typography>
      <Typography sx={{ fontSize: 12, mt: .75, color: 'text.secondary' }}>{source?.evidenceState === 'read' ? 'Фрагмент прочитанной страницы' : 'Страница не прочитана: доступна только информация поиска'}</Typography>
      {source?.readAt && Number.isFinite(Date.parse(source.readAt)) && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Получено: {new Date(source.readAt).toLocaleString('ru-RU')}</Typography>}
      <Box component="blockquote" sx={{ mx: 0, my: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13 }}>{source?.answerExcerpt || source?.snippet || 'Подтверждающий фрагмент не сохранён.'}</Box>
      <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Фрагмент помогает проверить утверждение; он не подтверждает автоматически все выводы ответа.</Typography>
      <Button size="small" component="a" href={source?.url} target="_blank" rel="noreferrer" sx={{ mt: 1 }}>Открыть источник</Button>
    </Popover>
  </>;
}
