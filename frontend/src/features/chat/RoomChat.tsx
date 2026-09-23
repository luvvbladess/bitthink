import { useEffect, useRef, useState } from 'react';
import { Box, IconButton, TextField, Typography } from '@mui/material';
import { PaperPlaneTilt, X } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { UserAvatar } from '@/components/UserAvatar';
import { floatingPanelSx } from '@/theme/effects';

interface Aside {
  id: number;
  content: string;
  created_at: string;
  author?: { name: string; avatar_url?: string | null } | null;
  mine: boolean;
}

function clock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

/** People-only thread for one shared conversation. The assistant never sees it. */
export function RoomChat({
  conversationId,
  open,
  onClose,
}: {
  conversationId: string;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const scroller = useRef<HTMLDivElement>(null);
  const drafts = useRef<Record<string, string>>({});
  const [text, setText] = useState('');
  const { data: notes = [] } = useQuery<Aside[]>({
    queryKey: ['asides', conversationId],
    queryFn: () => apiFetch(`/conversations/${conversationId}/asides`),
    enabled: open && !!conversationId,
    refetchInterval: open ? 4000 : false,
  });

  useEffect(() => {
    setText(drafts.current[conversationId] || '');
  }, [conversationId]);

  useEffect(() => {
    const node = scroller.current;
    if (!node || !open) return;
    node.scrollTop = node.scrollHeight;
  }, [notes, open, conversationId]);

  const send = useMutation({
    mutationFn: (content: string) =>
      apiFetch(`/conversations/${conversationId}/asides`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),
    onSuccess: () => {
      drafts.current[conversationId] = '';
      setText('');
      queryClient.invalidateQueries({ queryKey: ['asides', conversationId] });
    },
  });

  const submit = () => {
    const content = text.trim();
    if (!content || send.isPending) return;
    send.mutate(content);
  };

  if (!open) return null;

  return (
    <Box
      role="dialog"
      aria-label="Переписка между людьми"
      sx={{
        position: 'relative',
        zIndex: 4,
        width: { xs: 'min(100% - 24px, 380px)', lg: 340 },
        flexShrink: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        overflow: 'hidden',
        ...floatingPanelSx,
        '@media (prefers-reduced-motion: no-preference)': {
          animation: 'room-chat-in 0.2s cubic-bezier(0.23, 1, 0.32, 1)',
        },
        '@keyframes room-chat-in': {
          from: { opacity: 0, transform: 'translateY(8px)' },
          to: { opacity: 1, transform: 'translateY(0)' },
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, pt: 1.5, pb: 1 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={{ fontSize: '0.9375rem', fontWeight: 650, textWrap: 'balance', letterSpacing: '-0.02em' }}>
            Между собой
          </Typography>
          <Typography sx={{ fontSize: '0.75rem', color: 'text.secondary', textWrap: 'pretty', lineHeight: 1.35 }}>
            Только люди этой беседы. Ассистент не видит и не отвечает.
          </Typography>
        </Box>
        <IconButton
          onClick={onClose}
          aria-label="Закрыть переписку"
          sx={{
            width: 44,
            height: 44,
            color: 'text.primary',
            bgcolor: 'var(--bt-elevated)',
            border: '1px solid var(--bt-hairline)',
            '&:hover': { bgcolor: 'color-mix(in srgb, var(--bt-elevated) 78%, #21a0ce)' },
            '&:active': { transform: 'scale(0.96)' },
          }}
        >
          <X size={16} />
        </IconButton>
      </Box>
      <Box ref={scroller} sx={{ flex: 1, minHeight: 0, overflowY: 'auto', px: 1.5, py: 0.5, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        {notes.length === 0 && (
          <Typography sx={{ fontSize: '0.8125rem', color: 'text.secondary', textWrap: 'pretty', px: 0.5, py: 2 }}>
            Напишите здесь друг другу. Это не попадёт в диалог с ассистентом.
          </Typography>
        )}
        {notes.map((note) => (
          <Box key={note.id} sx={{ display: 'flex', flexDirection: note.mine ? 'row-reverse' : 'row', gap: 0.75, alignItems: 'flex-end' }}>
            <UserAvatar
              user={{ first_name: note.author?.name, avatar_url: note.author?.avatar_url }}
              sx={{ width: 28, height: 28, fontSize: '0.75rem', outline: '1px solid rgba(255,255,255,0.12)', outlineOffset: -1 }}
            />
            <Box sx={{ maxWidth: '78%', minWidth: 0 }}>
              {!note.mine && (
                <Typography sx={{ fontSize: '0.6875rem', fontWeight: 650, color: 'text.secondary', mb: 0.25, px: 0.5, textWrap: 'balance' }}>
                  {note.author?.name || 'Участник'}
                </Typography>
              )}
              <Box
                sx={{
                  px: 1.25,
                  py: 0.85,
                  borderRadius: '14px',
                  bgcolor: note.mine ? 'primary.main' : 'var(--bt-elevated)',
                  color: note.mine ? 'primary.contrastText' : 'text.primary',
                  border: note.mine ? 'none' : '1px solid var(--bt-hairline)',
                }}
              >
                <Typography sx={{ fontSize: '0.875rem', lineHeight: 1.45, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {note.content}
                </Typography>
              </Box>
              <Typography sx={{ fontSize: '0.6875rem', color: 'text.secondary', mt: 0.25, px: 0.5, textAlign: note.mine ? 'right' : 'left', fontVariantNumeric: 'tabular-nums' }}>
                {clock(note.created_at)}
              </Typography>
            </Box>
          </Box>
        ))}
      </Box>
      <Box
        component="form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        sx={{ display: 'flex', gap: 0.75, p: 1.25 }}
      >
        <TextField
          value={text}
          onChange={(event) => {
            const next = event.target.value;
            drafts.current[conversationId] = next;
            setText(next);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Написать людям…"
          multiline
          maxRows={4}
          fullWidth
          size="small"
          aria-label="Сообщение людям этой беседы, без ассистента"
          sx={{ '& .MuiOutlinedInput-root': { borderRadius: '14px' } }}
        />
        <IconButton
          type="submit"
          disabled={!text.trim() || send.isPending}
          aria-label="Отправить людям"
          sx={{
            alignSelf: 'flex-end',
            width: 44,
            height: 44,
            color: 'primary.contrastText',
            bgcolor: 'primary.main',
            '&:hover': { bgcolor: 'primary.dark' },
            '&:active': { transform: 'scale(0.96)' },
            '&.Mui-disabled': { bgcolor: 'var(--bt-overlay)', color: 'text.disabled' },
          }}
        >
          <PaperPlaneTilt size={18} weight="fill" />
        </IconButton>
      </Box>
    </Box>
  );
}
