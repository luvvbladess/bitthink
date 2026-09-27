import { useEffect, useState } from 'react';
import { Alert, Box, Button, Stack, Typography } from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '@/api/client';

type Connector = { id: number; type: string; name: string; hint?: string | null };

const RESULT_TEXT: Record<string, { severity: 'success' | 'warning' | 'error'; text: string }> = {
  connected: { severity: 'success', text: 'Google подключён. Пилот видит почту, Диск и календарь, отправляет письма и сохраняет файлы на Диск по вашей просьбе.' },
  partial: { severity: 'warning', text: 'Подключено не всё: на экране Google сняли часть галочек. Отключите и подключите снова, отметив все.' },
  denied: { severity: 'warning', text: 'Доступ не выдан. Можно попробовать ещё раз.' },
  expired: { severity: 'error', text: 'Ссылка устарела или открыта в другом браузере. Нажмите «Подключить Google» ещё раз.' },
  error: { severity: 'error', text: 'Google не ответил. Попробуйте ещё раз через минуту.' },
};

export function GoogleSection() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [error, setError] = useState('');
  const [result, setResult] = useState<string | null>(null);

  const { data, isLoading } = useQuery<Connector[]>({
    queryKey: ['connectors'],
    queryFn: () => apiFetch('/connectors'),
  });
  const google = (data || []).filter((item) => item.type === 'google');

  useEffect(() => {
    const value = params.get('google');
    if (!value) return;
    setResult(value);
    queryClient.invalidateQueries({ queryKey: ['connectors'] });
    params.delete('google');
    setParams(params, { replace: true });
  }, [params, setParams, queryClient]);

  const connect = useMutation({
    mutationFn: () =>
      apiFetch(`/connectors/google/start?origin=${encodeURIComponent(window.location.origin)}`) as Promise<{ url: string }>,
    onSuccess: ({ url }) => window.location.assign(url),
    onError: (err: Error) => setError(err.message || 'Не удалось начать подключение'),
  });

  const disconnect = useMutation({
    mutationFn: (id: number) => apiFetch(`/connectors/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['connectors'] });
      setResult(null);
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось отключить'),
  });

  const busy = connect.isPending || disconnect.isPending;
  const shown = result ? RESULT_TEXT[result] : null;

  return (
    <Box>
      {shown && (
        <Alert severity={shown.severity} sx={{ mb: 1.5 }} onClose={() => setResult(null)}>
          {shown.text}
        </Alert>
      )}

      {google.map((item) => (
        <Stack key={item.id} direction="row" alignItems="center" justifyContent="space-between" gap={1.5} sx={{ minHeight: 44 }}>
          <Typography sx={{ fontSize: '0.9375rem', minWidth: 0, overflowWrap: 'anywhere' }}>{item.hint || item.name}</Typography>
          <Button
            onClick={() => disconnect.mutate(item.id)}
            disabled={busy}
            sx={{ minHeight: 44, px: 0, color: 'text.secondary', flexShrink: 0 }}
          >
            Отключить
          </Button>
        </Stack>
      ))}

      <Button
        variant={google.length ? 'text' : 'contained'}
        onClick={() => connect.mutate()}
        disabled={busy || isLoading}
        sx={{ mt: google.length ? 0.5 : 0, minHeight: 44, borderRadius: '999px', px: google.length ? 0 : 2.5 }}
      >
        {google.length ? 'Подключить заново или другой аккаунт' : 'Подключить Google'}
      </Button>

      {!google.length && (
        <Typography sx={{ mt: 1.25, color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.5 }}>
          Google покажет «Приложение не проверено»: нажмите «Дополнительно» → «Перейти на сайт». Проверка у Google ещё идёт.
        </Typography>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}
    </Box>
  );
}
