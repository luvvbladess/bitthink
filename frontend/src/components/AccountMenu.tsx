import { useState } from 'react';
import { Box, Divider, IconButton, ListItemIcon, Menu, MenuItem, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Gear, CreditCard, ShieldCheck, SignOut } from '@phosphor-icons/react';
import { useAuthStore } from '@/stores/authStore';
import { apiFetch } from '@/api/client';
import { TIER_LABELS, formatTokens, formatUsd } from '@/constants/tiers';
import { headerIconBtnSx } from '@/theme/effects';
import { UserAvatar } from '@/components/UserAvatar';

type SubView = {
  tier?: string;
  name?: string;
  unlimited?: boolean;
  chat?: { remaining: number | null };
  windows?: { chat?: { session?: { remaining: number | null; active?: boolean } } };
  free_daily?: { replies: number; replies_limit: number };
  spend?: { day?: { usd?: number }; month?: { usd?: number } };
};

export function AccountMenu() {
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = useAuthStore((s) => s.isAdmin)();
  const open = Boolean(anchor);
  const { data: sub } = useQuery<SubView>({
    queryKey: ['subscription'],
    queryFn: () => apiFetch('/billing/subscription'),
    staleTime: 30_000,
  });

  const tierKey = sub?.tier || user?.subscription_tier;
  const tierLabel = tierKey ? sub?.name || TIER_LABELS[tierKey] || tierKey : null;
  const sessionLeft = sub?.windows?.chat?.session?.remaining;
  const remaining = sub?.unlimited
    ? `сегодня ${formatUsd(sub.spend?.day?.usd)} · месяц ${formatUsd(sub.spend?.month?.usd)}`
    : sub?.tier === 'free'
      ? `${Math.max(0, (sub.free_daily?.replies_limit || 30) - (sub.free_daily?.replies || 0))} ответов сегодня`
      : sessionLeft != null
        ? `ещё ${formatTokens(sessionLeft)} на 5 часов`
        : sub?.chat?.remaining != null
          ? `ещё ${formatTokens(sub.chat.remaining)}`
          : null;

  const go = (path: string) => {
    setAnchor(null);
    navigate(path);
  };

  return (
    <>
      <IconButton
        onClick={(e) => setAnchor(e.currentTarget)}
        sx={{
          ...headerIconBtnSx,
          ...(open && {
            color: 'primary.light',
            bgcolor: 'var(--bt-glow)',
            borderColor: 'var(--bt-line)',
          }),
        }}
        aria-label="Аккаунт"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <UserAvatar user={user} sx={{ width: 28, height: 28, fontSize: '0.82rem' }} />
      </IconButton>
      <Menu
        anchorEl={anchor}
        open={open}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{
          sx: {
            bgcolor: 'var(--bt-paper)',
            backgroundImage: 'none',
            border: '1px solid var(--bt-hairline)',
            borderRadius: 2,
            mt: 1,
            width: 260,
          },
        }}
      >
        <Box sx={{ px: 2, py: 1.5 }}>
          <Typography variant="body2" fontWeight={600} noWrap>
            {user?.first_name || user?.email?.split('@')[0]}
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.muted' }} noWrap component="div">
            {user?.email}
          </Typography>
          {tierLabel && (
            <Box
              sx={{
                display: 'inline-block',
                mt: 1,
                fontSize: '0.75rem',
                fontWeight: 500,
                color: 'primary.light',
              }}
            >
              {tierLabel}
            </Box>
          )}
          {remaining && (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary', fontVariantNumeric: 'tabular-nums' }}>
              {remaining}
            </Typography>
          )}
        </Box>
        <Divider sx={{ borderColor: 'var(--bt-hairline)' }} />
        <MenuItem onClick={() => go('/settings')} sx={{ minHeight: 44 }}>
          <ListItemIcon>
            <Gear size={20} weight="bold" />
          </ListItemIcon>
          Настройки
        </MenuItem>
        <MenuItem onClick={() => go('/billing')} sx={{ minHeight: 44 }}>
          <ListItemIcon>
            <CreditCard size={20} weight="bold" />
          </ListItemIcon>
          Кабинет
        </MenuItem>
        {isAdmin && (
          <MenuItem onClick={() => go('/admin')} sx={{ minHeight: 44 }}>
            <ListItemIcon>
              <ShieldCheck size={20} weight="bold" />
            </ListItemIcon>
            Админ-панель
          </MenuItem>
        )}
        <Divider sx={{ borderColor: 'var(--bt-hairline)' }} />
        <MenuItem onClick={() => useAuthStore.getState().logout()} sx={{ color: 'var(--bt-danger)', minHeight: 44 }}>
          <ListItemIcon sx={{ color: 'inherit' }}>
            <SignOut size={20} weight="bold" />
          </ListItemIcon>
          Выйти
        </MenuItem>
      </Menu>
    </>
  );
}
