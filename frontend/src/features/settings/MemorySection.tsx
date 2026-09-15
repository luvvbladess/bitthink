import { useState } from 'react';
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { GlowSwitch } from '@/components/GlowSwitch';
import { HOVER_FINE } from '@/theme/effects';

type Memory = {
  notes: string;
  enabled: boolean;
  updated_at: number;
};

export function MemorySection() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState('');
  const { data, isLoading } = useQuery<Memory>({
    queryKey: ['memory'],
    queryFn: () => apiFetch('/memory'),
  });

  const save = useMutation({
    mutationFn: (payload: Partial<Memory>) => apiFetch('/memory', { method: 'PATCH', body: JSON.stringify(payload) }),
    onSuccess: (next) => {
      queryClient.setQueryData(['memory'], next);
      setDraft(null);
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось сохранить память'),
  });

  const clear = useMutation({
    mutationFn: () => apiFetch('/memory', { method: 'DELETE' }),
    onSuccess: (next) => {
      queryClient.setQueryData(['memory'], next);
      setDraft(null);
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось очистить память'),
  });

  const notes = draft ?? data?.notes ?? '';
  const enabled = data?.enabled !== false;
  const editing = draft !== null;
  const busy = save.isPending || clear.isPending;

  return (
    <Box>
      <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1.5} sx={{ mb: 1.5 }}>
        <Box
          component="button"
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={enabled ? 'Выключить память' : 'Включить память'}
          disabled={busy || isLoading}
          onClick={() => save.mutate({ enabled: !enabled })}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.85,
            minHeight: 44,
            px: 0,
            border: 0,
            bgcolor: 'transparent',
            color: enabled ? 'text.primary' : 'text.secondary',
            font: 'inherit',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: busy || isLoading ? 'not-allowed' : 'pointer',
            WebkitTapHighlightColor: 'transparent',
            [HOVER_FINE]: {
              '&:hover .glow-switch-track': {
                bgcolor: enabled ? 'primary.light' : 'var(--bt-overlay-strong)',
              },
            },
          }}
        >
          Запоминать предпочтения
          <GlowSwitch checked={enabled} />
        </Box>
        <Button
          onClick={() => clear.mutate()}
          disabled={busy || !notes}
          sx={{ minHeight: 44, px: 0, color: 'text.secondary' }}
        >
          Очистить
        </Button>
      </Stack>

      {editing ? (
        <Stack spacing={1.25}>
          <TextField
            value={notes}
            onChange={(e) => setDraft(e.target.value)}
            multiline
            minRows={4}
            fullWidth
            placeholder="Например: отвечать коротко, результат в Word, обращение на ты"
          />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" onClick={() => save.mutate({ notes })} disabled={busy} sx={{ minHeight: 44, borderRadius: '999px' }}>
              Сохранить
            </Button>
            <Button onClick={() => setDraft(null)} sx={{ minHeight: 44 }}>
              Отмена
            </Button>
          </Stack>
        </Stack>
      ) : (
        <Box>
          <Typography
            sx={{
              whiteSpace: 'pre-wrap',
              color: notes ? 'text.secondary' : 'text.secondary',
              minHeight: 44,
              fontSize: '0.9375rem',
              lineHeight: 1.55,
              opacity: enabled ? 1 : 0.7,
            }}
          >
            {isLoading ? 'Загружаю…' : notes || 'Пока пусто. Сюда попадёт стиль и формат, если вы об этом скажете. Текущие задачи не запоминаются.'}
          </Typography>
          <Button
            onClick={() => setDraft(data?.notes || '')}
            disabled={isLoading}
            sx={{ mt: 0.5, minHeight: 44, px: 0, color: 'primary.light' }}
          >
            Изменить
          </Button>
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}
    </Box>
  );
}
