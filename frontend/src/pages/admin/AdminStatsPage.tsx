import { Grid2 as Grid, Typography, Box, Skeleton } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { Users, ChatsCircle, ChatText } from '@phosphor-icons/react';
import { adminApi } from '@/api/adminApi';
import { AdminIsland } from './AdminIsland';

export default function AdminStatsPage() {
  const { data, isLoading, isError } = useQuery({ queryKey: ['admin', 'stats'], queryFn: () => adminApi.getStats() });

  const stats = [
    { label: 'Пользователи', value: data?.total_users, icon: Users },
    { label: 'Беседы', value: data?.total_conversations, icon: ChatsCircle },
    { label: 'Сообщения', value: data?.total_messages, icon: ChatText },
  ];

  if (isError) {
    return (
      <AdminIsland sx={{ p: 4, textAlign: 'center' }}>
        <Typography sx={{ color: 'text.secondary' }}>Не удалось загрузить статистику. Попробуйте обновить страницу.</Typography>
      </AdminIsland>
    );
  }

  return (
    <Grid container spacing={3}>
      {stats.map((s) => {
        const Icon = s.icon;
        return (
          <Grid size={{ xs: 12, md: 4 }} key={s.label}>
            <AdminIsland sx={{ p: 4 }}>
              <Box
                sx={{
                  width: 40,
                  height: 40,
                  borderRadius: 2,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  bgcolor: 'var(--bt-glow)',
                  color: 'primary.light',
                  mb: 2,
                }}
              >
                <Icon size={20} weight="bold" />
              </Box>
              {isLoading ? (
                <Skeleton variant="text" width={100} height={56} sx={{ bgcolor: 'var(--bt-overlay-faint)' }} />
              ) : (
                <Typography variant="h2" sx={{ mb: 0.5, fontSize: '2.5rem' }}>
                  {(s.value ?? 0).toLocaleString('ru-RU')}
                </Typography>
              )}
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                {s.label}
              </Typography>
            </AdminIsland>
          </Grid>
        );
      })}
    </Grid>
  );
}
