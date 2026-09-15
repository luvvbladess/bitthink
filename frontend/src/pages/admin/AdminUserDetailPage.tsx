import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Avatar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid2 as Grid,
  MenuItem,
  Select,
  Skeleton,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Trash, Sparkle } from '@phosphor-icons/react';
import { adminApi } from '@/api/adminApi';
import { AdminIsland, TIER_LABELS, formatExpiry } from './AdminIsland';
import { formatUsd } from '@/constants/tiers';

const TIERS = [
  { id: 'free', label: 'Базовый' },
  { id: 'trial', label: 'Пробный' },
  { id: 'pro', label: 'Pro' },
  { id: 'proplus', label: 'Pro+' },
  { id: 'ultra', label: 'Ultra' },
  { id: 'creator', label: 'Creator' },
];

const roleColors: Record<string, { bg: string; color: string }> = {
  admin: { bg: 'var(--bt-glow-strong)', color: 'primary.light' },
  user: { bg: 'var(--bt-overlay-faint)', color: 'var(--bt-ink-muted)' },
};

function pluralizeRu(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Stack direction="row" justifyContent="space-between" sx={{ py: 0.75 }}>
      <Typography variant="body2" sx={{ color: 'text.muted' }}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={500}>
        {value}
      </Typography>
    </Stack>
  );
}

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const userId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [tier, setTier] = useState('free');
  const [durationDays, setDurationDays] = useState(30);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const { data: user, isLoading } = useQuery({
    queryKey: ['admin', 'user', userId],
    queryFn: () => adminApi.getUser(userId),
  });

  const { data: conversations } = useQuery({
    queryKey: ['admin', 'user', userId, 'conversations'],
    queryFn: () => adminApi.getUserConversations(userId),
    enabled: !isLoading,
  });

  const { data: usage } = useQuery({
    queryKey: ['admin', 'user', userId, 'usage'],
    queryFn: () => adminApi.getUserUsage(userId),
    enabled: !isLoading,
  });

  const setSubscription = useMutation({
    mutationFn: (data: { tier: string; duration_days: number; from_today: boolean }) =>
      adminApi.setSubscription(userId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'user', userId] });
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
      setEditOpen(false);
    },
  });

  const deleteConversation = useMutation({
    mutationFn: (conversationId: string) => adminApi.deleteConversation(userId, conversationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'user', userId, 'conversations'] });
      setConfirmDeleteId(null);
    },
  });

  if (isLoading || !user) {
    return (
      <Stack spacing={2}>
        <Skeleton variant="text" width={240} height={48} sx={{ bgcolor: 'var(--bt-overlay-faint)' }} />
        <Skeleton variant="rounded" height={200} sx={{ bgcolor: 'var(--bt-overlay-faint)' }} />
      </Stack>
    );
  }

  const sub = user.subscription || {};
  const todayUsage: Record<string, { input: number; output: number; images: number; calls: number }> = usage?.day || {};
  const modelUsageRows = Object.entries(todayUsage);

  const openEdit = () => {
    const next = sub.tier === 'start' ? 'pro' : sub.tier === 'max' ? 'ultra' : sub.tier || 'free';
    setTier(next);
    setDurationDays(next === 'trial' ? 7 : 30);
    setEditOpen(true);
  };

  return (
    <Box>
      <Button
        startIcon={<ArrowLeft size={16} />}
        onClick={() => navigate('/admin/users')}
        size="small"
        sx={{ color: 'text.muted', mb: 2, minHeight: 44 }}
      >
        К списку пользователей
      </Button>

      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 4 }}>
        <Avatar sx={{ width: 48, height: 48, bgcolor: 'var(--bt-glow-strong)', color: 'primary.light', fontSize: '1.1rem' }}>
          {(user.first_name || user.email)[0]?.toUpperCase()}
        </Avatar>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h4" sx={{ fontSize: '1.5rem' }} noWrap>
            {user.first_name || user.email.split('@')[0]}
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }} noWrap>
            {user.email}
          </Typography>
        </Box>
        <Chip
          label={user.role}
          size="small"
          sx={{ ml: 'auto', bgcolor: roleColors[user.role]?.bg, color: roleColors[user.role]?.color, fontWeight: 600 }}
        />
      </Stack>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12, md: 6 }}>
          <AdminIsland sx={{ p: 3 }}>
            <Typography variant="h6" sx={{ mb: 1.5, fontSize: '1rem' }}>
              Профиль
            </Typography>
            <StatRow label="ID" value={user.id} />
            <StatRow label="Bot ID" value={user.bot_user_id} />
            <StatRow label="Создан" value={new Date(user.created_at).toLocaleDateString('ru-RU')} />
          </AdminIsland>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <AdminIsland sx={{ p: 3 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
              <Typography variant="h6" sx={{ fontSize: '1rem' }}>
                Подписка
              </Typography>
              <Button variant="contained" size="small" onClick={openEdit} sx={{ minHeight: 40 }}>
                Назначить с сегодня
              </Button>
            </Stack>
            <StatRow label="Тариф" value={sub.name || TIER_LABELS[sub.tier] || sub.tier || 'free'} />
            <StatRow label="Истекает" value={formatExpiry(sub.expires_at)} />
            {sub.unlimited ? (
              <>
                <StatRow label="Сегодня" value={formatUsd(sub.spend?.day?.usd)} />
                <StatRow label="Месяц" value={formatUsd(sub.spend?.month?.usd)} />
              </>
            ) : (
              <>
                <StatRow
                  label="Чат"
                  value={`${(sub.chat?.used ?? sub.chat_tokens_used ?? 0).toLocaleString('ru-RU')} / ${(sub.chat?.limit ?? 0).toLocaleString('ru-RU')}`}
                />
                <StatRow
                  label="Пилот"
                  value={`${(sub.computer?.used ?? sub.computer_tokens_used ?? 0).toLocaleString('ru-RU')} / ${(sub.computer?.limit ?? 0).toLocaleString('ru-RU')}`}
                />
                <StatRow
                  label="Картинки"
                  value={`${sub.images?.used ?? sub.images_used ?? 0} / ${sub.images?.limit ?? 0}`}
                />
              </>
            )}
            {!sub.unlimited && (
              <StatRow label="Nano сегодня" value={`${sub.nano_cushion?.used ?? 0} / ${sub.nano_cushion?.limit ?? 0}`} />
            )}
            {!sub.unlimited && sub.windows?.chat && (
              <>
                <StatRow
                  label="Чат 5 ч"
                  value={`${(sub.windows.chat.session?.used ?? 0).toLocaleString('ru-RU')} / ${(sub.windows.chat.session?.limit ?? 0).toLocaleString('ru-RU')}`}
                />
                <StatRow
                  label="Чат неделя"
                  value={`${(sub.windows.chat.week?.used ?? 0).toLocaleString('ru-RU')} / ${(sub.windows.chat.week?.limit ?? 0).toLocaleString('ru-RU')}`}
                />
              </>
            )}
          </AdminIsland>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <AdminIsland sx={{ p: 3 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
              <Box sx={{ color: 'primary.light', lineHeight: 0 }}>
                <Sparkle size={16} color="currentColor" />
              </Box>
              <Typography variant="h6" sx={{ fontSize: '1rem' }}>
                Использование сегодня
              </Typography>
            </Stack>
            {modelUsageRows.length === 0 ? (
              <Typography variant="body2" sx={{ color: 'text.muted' }}>
                Сегодня запросов не было.
              </Typography>
            ) : (
              modelUsageRows.map(([model, u]) => (
                <Stack key={model} direction="row" justifyContent="space-between" sx={{ py: 0.75 }}>
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    {model}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.muted' }}>
                    {(u.input + u.output).toLocaleString('ru-RU')} токенов
                    {u.images ? ` • ${u.images} изобр.` : ''}
                    {u.calls ? ` • ${u.calls} выз.` : ''}
                  </Typography>
                </Stack>
              ))
            )}
          </AdminIsland>
        </Grid>

        <Grid size={{ xs: 12, md: 6 }}>
          <AdminIsland sx={{ p: 3 }}>
            <Typography variant="h6" sx={{ mb: 1.5, fontSize: '1rem' }}>
              Беседы ({conversations?.items?.length || 0})
            </Typography>
            <Stack spacing={1}>
              {(conversations?.items || []).length === 0 && (
                <Typography variant="body2" sx={{ color: 'text.muted' }}>
                  Бесед пока нет.
                </Typography>
              )}
              {(conversations?.items || []).map((c: { id: string; title: string; message_count: number; document_count: number }) => (
                <Stack
                  key={c.id}
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  sx={{ p: 1.5, borderRadius: 2, bgcolor: 'var(--bt-overlay-faint)' }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={500} noWrap>
                      {c.title}
                    </Typography>
                    <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                      {c.message_count} {pluralizeRu(c.message_count, 'сообщение', 'сообщения', 'сообщений')} •{' '}
                      {c.document_count} {pluralizeRu(c.document_count, 'документ', 'документа', 'документов')}
                    </Typography>
                  </Box>
                  {confirmDeleteId === c.id ? (
                    <Stack direction="row" spacing={0.5}>
                      <Button size="small" color="error" variant="contained" onClick={() => deleteConversation.mutate(c.id)}>
                        Точно?
                      </Button>
                      <Button size="small" onClick={() => setConfirmDeleteId(null)}>
                        Отмена
                      </Button>
                    </Stack>
                  ) : (
                    <Button
                      size="small"
                      color="error"
                      startIcon={<Trash size={16} />}
                      onClick={() => setConfirmDeleteId(c.id)}
                    >
                      Удалить
                    </Button>
                  )}
                </Stack>
              ))}
            </Stack>
          </AdminIsland>
        </Grid>
      </Grid>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} PaperProps={{ sx: { bgcolor: 'var(--bt-paper)', backgroundImage: 'none' } }}>
        <DialogTitle>Назначить тариф с сегодня</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ minWidth: 320, pt: 1 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              Текущий тариф и дата окончания будут сброшены. Новый срок начнётся с сегодняшнего дня, лимиты обнулятся.
            </Typography>
            <Select value={tier} onChange={(e) => setTier(e.target.value)} fullWidth>
              {TIERS.map((t) => (
                <MenuItem key={t.id} value={t.id}>
                  {t.label}
                </MenuItem>
              ))}
            </Select>
            {tier !== 'free' && (
              <TextField
                label="Дней с сегодня"
                type="number"
                value={durationDays}
                onChange={(e) => setDurationDays(Number(e.target.value))}
                fullWidth
              />
            )}
            {setSubscription.isError && (
              <Typography variant="body2" color="error">
                {(setSubscription.error as Error)?.message || 'Не удалось назначить тариф. Попробуйте ещё раз.'}
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Отмена</Button>
          <Button
            variant="contained"
            disabled={setSubscription.isPending}
            onClick={() => setSubscription.mutate({ tier, duration_days: durationDays, from_today: true })}
          >
            {setSubscription.isPending ? 'Сохраняю…' : 'Назначить'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
