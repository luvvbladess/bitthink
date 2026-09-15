import { Box, Container, Typography, Button } from '@mui/material';
import { useEffect } from 'react';
import { Outlet, useLocation, useNavigate, Link as RouterLink } from 'react-router-dom';
import { ShieldWarning, Users, ChartBar, ArrowLeft } from '@phosphor-icons/react';
import { useAuthStore } from '@/stores/authStore';
import { floatingPanelSx } from '@/theme/effects';
import { BRAND_NAME } from '@/brand';
import { applyPageMeta } from '@/seo';

export default function AdminLayout() {
  const isAdmin = useAuthStore((s) => s.isAdmin)();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    applyPageMeta({
      title: `Админ – ${BRAND_NAME}`,
      canonicalPath: '/admin',
      noindex: true,
    });
  }, []);

  if (!isAdmin) {
    return (
      <Box
        sx={{
          minHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 2,
          textAlign: 'center',
          px: 2,
          pt: 10,
        }}
      >
        <Box sx={{ color: 'text.muted', lineHeight: 0 }}>
          <ShieldWarning size={40} weight="duotone" color="currentColor" />
        </Box>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>
          Доступ запрещён
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 360 }}>
          Эта страница доступна только администраторам.
        </Typography>
        <Button component={RouterLink} to="/chat" variant="outlined" sx={{ mt: 1 }}>
          Вернуться в чат
        </Button>
      </Box>
    );
  }

  const tabs = [
    { label: 'Пользователи', path: '/admin/users', icon: <Users size={17} /> },
    { label: 'Статистика', path: '/admin/stats', icon: <ChartBar size={17} /> },
  ];
  const activeTab = tabs.findIndex((t) => location.pathname.startsWith(t.path));

  return (
    <Box sx={{ pt: { xs: 10, md: 11 }, pb: 8 }}>
      <Container maxWidth="lg">
        <Button
          component={RouterLink}
          to="/chat"
          startIcon={<ArrowLeft size={16} />}
          size="small"
          sx={{ color: 'text.muted', mb: 2.5, minHeight: 44, '&:hover': { color: 'text.primary', bgcolor: 'transparent' } }}
        >
          В чат
        </Button>
        <Typography variant="h2" sx={{ mb: 0.75, fontSize: { xs: '1.75rem', md: '2.1rem' } }}>
          Админ-панель
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 3, maxWidth: 520 }}>
          Пользователи, тарифы и статистика. Назначение тарифа всегда идёт с сегодняшнего дня.
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, mb: 4, flexWrap: 'wrap' }}>
          {tabs.map((tab, idx) => {
            const active = (activeTab === -1 ? 0 : activeTab) === idx;
            return (
              <Box
                key={tab.path}
                component="button"
                type="button"
                onClick={() => navigate(tab.path)}
                sx={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 0.85,
                  minHeight: 44,
                  px: 1.6,
                  cursor: 'pointer',
                  font: 'inherit',
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  color: active ? 'primary.light' : 'text.secondary',
                  ...(active
                    ? floatingPanelSx
                    : {
                        borderRadius: '22px',
                        bgcolor: 'var(--bt-overlay-faint)',
                        border: '1px solid var(--bt-overlay)',
                      }),
                  '&:hover': { color: 'text.primary' },
                }}
              >
                {tab.icon}
                {tab.label}
              </Box>
            );
          })}
        </Box>
        <Outlet />
      </Container>
    </Box>
  );
}
