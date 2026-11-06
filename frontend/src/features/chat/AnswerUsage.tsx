import { useId, useState } from 'react';
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import { DotsThree } from '@phosphor-icons/react';
import type { SearchItem } from './clarify';

export const USAGE_QUERY = '__answer_usage__';
type ModelUsage = { model: string; calls: number; input: number; output: number; cached: number; cache_write: number; units: number; retained: number; unknown_tokens: number; unknown_units: number };

export function answerUsage(search?: SearchItem[]): ModelUsage[] | null {
  const item = search?.find(row => row.query === USAGE_QUERY);
  if (!item || item.summary.length > 20000) return null;
  try {
    const data = JSON.parse(item.summary);
    if (data?.version !== 1 || !Array.isArray(data.models) || !data.models.length || data.models.length > 32) return null;
    const keys = ['calls', 'input', 'output', 'cached', 'cache_write', 'units', 'retained', 'unknown_tokens', 'unknown_units'] as const;
    if (!data.models.every((row: ModelUsage) => row && typeof row.model === 'string' && row.model.length <= 128
      && keys.every(key => Number.isSafeInteger(row[key]) && row[key] >= 0)
      && row.calls > 0 && row.cached + row.cache_write <= row.input && row.retained <= row.units && row.unknown_tokens <= row.calls && row.unknown_units <= row.calls)) return null;
    if (!keys.every(key => Number.isSafeInteger(data.models.reduce((sum: number, row: ModelUsage) => sum + row[key], 0)))) return null;
    return data.models;
  } catch { return null; }
}

const number = (value: number) => value.toLocaleString('ru-RU');

export function AnswerUsage({ search }: { search?: SearchItem[] }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const id = useId();
  const rows = answerUsage(search);
  if (!rows) return null;
  const units = rows.reduce((sum, row) => sum + row.units, 0);
  const incomplete = rows.some(row => row.unknown_units > 0);
  return <>
    <Tooltip title="Ещё">
      <IconButton size="small" aria-label="Меню ответа" aria-haspopup="menu" aria-expanded={anchor ? true : undefined} aria-controls={anchor ? `${id}-menu` : undefined} onClick={event => setAnchor(event.currentTarget)} sx={{ color: 'text.muted', p: { xs: 1.1, md: .5 } }}>
        <DotsThree size={16} />
      </IconButton>
    </Tooltip>
    <Menu id={`${id}-menu`} anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
      <MenuItem onClick={() => { setAnchor(null); setOpen(true); }}>Расход лимита</MenuItem>
    </Menu>
    <Dialog open={open} onClose={() => setOpen(false)} aria-labelledby={`${id}-title`} fullWidth maxWidth="sm">
      <DialogTitle id={`${id}-title`}>Расход лимита</DialogTitle>
      <DialogContent sx={{ color: 'text.secondary', fontSize: 14, overflowWrap: 'anywhere' }}>
      <Box sx={{ mb: 1, fontWeight: 600, color: 'text.primary' }}>{incomplete ? 'Данные неполные' : `${number(units)} ед.`}</Box>
    <Box sx={{ pt: .5, maxWidth: '65ch', lineHeight: 1.6 }}>
      <Box component="p" sx={{ m: 0, mb: 1 }}>Текстовая часть ответа. Изображения, фоновое обновление памяти и другие платные действия здесь не учтены.</Box>
      {rows.map((row, index) => <Box key={`${row.model}-${index}`} sx={{ mb: 1 }}>
        <Box sx={{ color: 'text.primary', fontWeight: 500 }}>{row.model === 'other' ? 'Другие модели' : row.model}</Box>
        <Box>Вызовов: {number(row.calls)}</Box>
        {row.unknown_tokens < row.calls && <>
          <Box>{row.unknown_tokens ? 'Подтверждено: ' : ''}Вход: {number(row.input)} · Ответ: {number(row.output)} токенов</Box>
          <Box>Из входных в кеше: {number(row.cached)} · Записано в кеш: {number(row.cache_write)}</Box>
        </>}
        <Box>Лимит: {row.unknown_units ? 'учёт неполный' : `${number(row.units)} ед.`}</Box>
        {row.unknown_tokens > 0 && <Box>Для части вызовов провайдер не сообщил количество токенов.</Box>}
        {row.retained > 0 && <Box>Включён резерв без подтверждения провайдера: {number(row.retained)} ед.</Box>}
      </Box>)}
      <Box component="p" sx={{ m: 0 }}>Токены — объём текста, единицы лимита учитывают модель и кеш. Суточное число ответов здесь не учитывается. Расшифровка относится только к этому ответу.</Box>
    </Box>
      </DialogContent>
      <DialogActions><Button onClick={() => setOpen(false)}>Закрыть</Button></DialogActions>
    </Dialog>
  </>;
}
