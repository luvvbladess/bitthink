import { useState } from 'react';
import { Box, Dialog, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material';
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
  const { data } = useQuery<ShareStatus>({
    queryKey: ['share', conversationId],
    queryFn: () => apiFetch(`/conversations/${conversationId}/share`),
    enabled: open && !!conversationId,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['share', conversationId] });
    queryClient.invalidateQueries({ queryKey: ['conversations'] });
  };

  const createLink = useMutation({
    mutationFn: () => apiFetch(`/conversations/${conversationId}/share`, { method: 'POST' }),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: () => apiFetch(`/conversations/${conversationId}/share`, { method: 'DELETE' }),
    onSuccess: refresh,
  });

  const link = data?.token ? `${window.location.origin}/join/${data.token}` : '';
  const isOwner = data?.role !== 'member';

  const copy = async () => {
    if (!link) return;
    await navigator.clipboard.writeText(link);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 1 }}>
        <Users size={20} />
        <Box component="span" sx={{ flex: 1 }}>Общий диалог</Box>
        <IconButton onClick={onClose} aria-label="Закрыть" sx={{ color: 'text.primary', bgcolor: 'var(--bt-elevated)', border: '1px solid var(--bt-hairline)', '&:hover': { bgcolor: 'color-mix(in srgb, var(--bt-elevated) 78%, #21a0ce)' } }}>
          <X size={18} />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <Typography sx={{ fontSize: '0.875rem', color: 'text.secondary', mb: 2 }}>
          По ссылке люди видят всю историю, пишут ассистенту своим режимом и прикладывают файлы. Расход идёт с того, кто отправил сообщение.
        </Typography>
        {data?.people?.length ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 2 }}>
            {data.people.map((person) => (
              <Box key={person.name + (person.owner ? '-owner' : '')} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <UserAvatar user={person} sx={{ width: 28, height: 28, fontSize: '0.8rem' }} />
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
            <Typography sx={{ flex: 1, minWidth: 0, fontSize: '0.8125rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {link}
            </Typography>
            <IconButton onClick={copy} aria-label="Скопировать ссылку">
              {copied ? <Check size={18} /> : <Copy size={18} />}
            </IconButton>
          </Box>
        )}
        {isOwner && data?.token && (
          <Box
            component="button"
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
