import { useState, type MouseEvent } from 'react';
import { Box, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import { Flag } from '@phosphor-icons/react';
import { apiFetch } from '@/api/client';

const reasons = [
  ['incorrect', 'Неверный факт'],
  ['incomplete', 'Не закончил задачу'],
  ['missed_edit', 'Не понял правку'],
  ['slow', 'Слишком долго'],
];

export function AnswerFeedback({ conversationId, messageId }: { conversationId: string; messageId: number }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const open = (event: MouseEvent<HTMLElement>) => setAnchor(event.currentTarget);
  async function report(reason: string) {
    setAnchor(null);
    setStatus('sending');
    try {
      await apiFetch(`/conversations/${encodeURIComponent(conversationId)}/messages/${messageId}/feedback`, {
        method: 'POST', body: JSON.stringify({ reason }),
      });
      setStatus('sent');
    } catch {
      setStatus('error');
    }
  }
  return <>
    <Tooltip title="Сообщить о проблеме">
      <span>
        <IconButton size="small" aria-label="Сообщить о проблеме" aria-haspopup="menu" aria-expanded={!!anchor}
          disabled={status === 'sending' || status === 'sent'} onClick={open} sx={{ color: 'text.muted', p: { xs: 1.1, md: 0.5 } }}>
          <Flag size={14} />
        </IconButton>
      </span>
    </Tooltip>
    <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
      {reasons.map(([reason, title]) => <MenuItem key={reason} onClick={() => void report(reason)}>{title}</MenuItem>)}
    </Menu>
    {status === 'sent' && <Box role="status" sx={{ fontSize: 12, color: 'text.secondary' }}>Спасибо, отзыв отправлен</Box>}
    {status === 'error' && <Box role="alert" sx={{ fontSize: 12, color: 'text.secondary' }}>Не удалось отправить отзыв. Попробуйте ещё раз.</Box>}
  </>;
}
