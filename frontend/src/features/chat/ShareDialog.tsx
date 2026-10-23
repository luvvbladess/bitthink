import { useEffect, useState } from 'react';
import { Alert, Box, Button, Dialog, DialogContent, DialogTitle, IconButton, TextField, Typography } from '@mui/material';
import { Copy, Check, LinkBreak, Users, X } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { UserAvatar } from '@/components/UserAvatar';
import { PrimaryButton } from '@/components/IslandButton';

interface Person {
  name: string;
  avatar_url?: string | null;
  owner?: boolean;
}

interface ShareStatus {
  shared: boolean;
  token: string | null;
  role: 'owner' | 'member';
  people: Person[];
}

export function ShareDialog({ conversationId, open, onClose }: { conversationId: string; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setError(''); setCopied(false); }, [open, conversationId]);
  const { data, error: loadError, isPending, refetch } = useQuery<ShareStatus>({
    queryKey: ['share', conversationId],
    queryFn: () => apiFetch(`/conversations/${conversationId}/share`),
    enabled: open && !!conversationId,
  });

  const refresh = () => {
    setError('');
    queryClient.invalidateQueries({ queryKey: ['share', conversationId] });
    queryClient.invalidateQueries({ queryKey: ['conversations'] });
  };

  const createLink = useMutation({
    mutationFn: () => apiFetch(`/conversations/${conversationId}/share`, { method: 'POST' }),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message || 'Не удалось создать ссылку'),
  });
  const revoke = useMutation({
    mutationFn: () => apiFetch(`/conversations/${conversationId}/share`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message || 'Не удалось закрыть доступ'),
  });

  const link = data?.token ? `${window.location.origin}/join/${data.token}` : '';
  const isOwner = data?.role === 'owner';

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true); setError('');
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError('Не удалось скопировать ссылку. Выделите и скопируйте её из поля вручную.');
    }
  };
  // Phones: the system share sheet (Telegram, WhatsApp, mail) beats copy and paste.
  const canShare = typeof navigator !== 'undefined' && typeof navigator.share === 'function';
  const shareLink = async () => {
    if (!link) return;
    try {
      await navigator.share({ title: 'Общий диалог в Bit-Think', text: 'Присоединяйся к диалогу', url: link });
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError('Не удалось открыть меню отправки. Скопируйте ссылку из поля.');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs" aria-labelledby="share-dialog-title">
      <DialogTitle id="share-dialog-title" sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 1 }}>
        <Users size={20} />
        <Box component="span" sx={{ flex: 1 }}>Общий диалог</Box>
        <IconButton onClick={onClose} aria-label="Закрыть" sx={{ color: 'text.primary', bgcolor: 'var(--bt-elevated)', border: '1px solid var(--bt-hairline)', '&:hover': { bgcolor: 'color-mix(in srgb, var(--bt-elevated) 78%, #21a0ce)' } }}>
          <X size={18} />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {isPending && <Typography role="status" sx={{ mb: 2 }}>Загружаем настройки доступа…</Typography>}
        {loadError && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={() => void refetch()}>Повторить</Button>}>Не удалось загрузить доступ к диалогу.</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Typography sx={{ fontSize: '0.875rem', color: 'text.secondary', mb: 2 }}>
          По ссылке люди видят всю историю, пишут ассистенту своим режимом и прикладывают файлы. Расход идёт с того, кто отправил сообщение.
        </Typography>
        {data?.people?.length ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
            {data.people.map((person) => (
              <Box key={person.name + (person.owner ? '-owner' : '')} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <UserAvatar user={{ first_name: person.name, avatar_url: person.avatar_url }} sx={{ width: 28, height: 28, fontSize: '0.8rem' }} />
                <Typography sx={{ fontSize: '0.875rem' }}>
                  {person.name}{person.owner ? ' · владелец' : ''}
                </Typography>
              </Box>
            ))}
          </Box>
        ) : null}
        {isOwner && !data?.token && (
          <PrimaryButton onClick={() => createLink.mutate()} disabled={createLink.isPending}>
            Создать ссылку
          </PrimaryButton>
        )}
        {link && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <TextField label="Ссылка на диалог" value={link} size="small" InputProps={{ readOnly: true }} onFocus={event => event.target.select()} sx={{ flex: 1, minWidth: 0 }} />
            <IconButton onClick={copy} aria-label="Скопировать ссылку" sx={{ width: 44, height: 44 }}>
              {copied ? <Check size={18} /> : <Copy size={18} />}
            </IconButton>
          </Box>
        )}
        {link && canShare && (
          <Box sx={{ mt: 1.5 }}>
            <PrimaryButton onClick={shareLink} fullWidth>
              Отправить ссылку
            </PrimaryButton>
          </Box>
        )}
        {isOwner && data?.token && (
          <Box
            component="button"
            disabled={revoke.isPending || createLink.isPending}
            onClick={() => revoke.mutate()}
            sx={{ mt: 2, display: 'inline-flex', alignItems: 'center', gap: 0.75, border: 0, bgcolor: 'transparent', color: 'var(--bt-danger)', cursor: 'pointer', font: 'inherit', p: 0 }}
          >
            <LinkBreak size={16} />
            Закрыть доступ
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
}
