import { useState, type MouseEvent } from 'react';
import { Box, Divider, IconButton, ListItemIcon, Menu, MenuItem, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Gear, CreditCard, Moon, ShieldCheck, SignOut, Sun } from '@phosphor-icons/react';
import { useColorMode } from '@/theme/ColorMode';
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
  windows?: {
    chat?: {
      session?: { remaining: number | null; active?: boolean; ratio?: number };
      week?: { ratio?: number };
      month?: { ratio?: number };
    };
  };
  free_daily?: { replies: number; replies_limit: number };
  spend?: { day?: { usd?: number }; month?: { usd?: number } };
};

export function AccountMenu({ variant = 'icon' }: { variant?: 'icon' | 'row' }) {
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const colorMode = useColorMode();
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
      ? `${Math.max(0, (sub.free_daily?.replies_limit || 30) - (sub.free_daily?.replies || 0))} из ${sub.free_daily?.replies_limit || 30} ответов осталось сегодня`
      : sessionLeft != null
        ? `ещё ${formatTokens(sessionLeft)} на 5 часов`
        : sub?.chat?.remaining != null
          ? `ещё ${formatTokens(sub.chat.remaining)}`
          : null;

  const go = (path: string) => {
    setAnchor(null);
    navigate(path);
  };

  // The tightest window is the one that will stop the person first, so that is the meter.
  const meter: number | null = sub?.unlimited
    ? null
    : sub?.tier === 'free'
      ? Math.min(1, (sub.free_daily?.replies || 0) / (sub.free_daily?.replies_limit || 30))
      : sub?.windows?.chat
        ? Math.min(
            1,
            Math.max(
              sub.windows.chat.session?.active ? sub.windows.chat.session?.ratio || 0 : 0,
              sub.windows.chat.week?.ratio || 0,
              sub.windows.chat.month?.ratio || 0,
            ),
          )
        : null;
  const displayName = user?.first_name || user?.email?.split('@')[0] || '';

  return (
    <>
      {variant === 'row' ? (
        <Box
          component="button"
          type="button"
          onClick={(e: MouseEvent<HTMLElement>) => setAnchor(e.currentTarget)}
          aria-label="Аккаунт"
          aria-haspopup="menu"
          aria-expanded={open}
          sx={{
            display: 'block',
            width: '100%',
            p: 1.1,
            border: 0,
            borderRadius: '12px',
            bgcolor: open ? 'var(--bt-overlay)' : 'transparent',
            color: 'text.primary',
            font: 'inherit',
            textAlign: 'left',
            cursor: 'pointer',
            transition: 'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
            '&:hover': { bgcolor: 'var(--bt-overlay)' },
            '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.1 }}>
            <UserAvatar user={user} sx={{ width: 32, height: 32, fontSize: '0.875rem', flexShrink: 0 }} />
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Box sx={{ fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.25, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {displayName}
              </Box>
              <Box sx={{ fontSize: '0.75rem', lineHeight: 1.3, color: 'text.secondary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {tierLabel || 'Аккаунт'}
                {meter !== null &&
                  (sub?.tier === 'free'
                    ? ` · ${sub.free_daily?.replies || 0} из ${sub.free_daily?.replies_limit || 30} сегодня`
                    : ` · ${Math.round(meter * 100)}% лимита`)}
              </Box>
            </Box>
          </Box>
          {meter !== null && (
            <Box
              role="progressbar"
              aria-label="Использовано лимита"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(meter * 100)}
              sx={{ mt: 1, height: 3, borderRadius: 99, bgcolor: 'var(--bt-overlay)', overflow: 'hidden' }}
            >
              <Box
                sx={{
                  height: '100%',
                  width: `${Math.max(2, meter * 100)}%`,
                  borderRadius: 99,
                  bgcolor: meter >= 0.9 ? 'var(--bt-danger)' : 'primary.main',
                  transition: 'width 0.4s cubic-bezier(0.23, 1, 0.32, 1)',
                  '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
                }}
              />
            </Box>
          )}
        </Box>
      ) : (
        <IconButton
          onClick={(e) => setAnchor(e.currentTarget)}
          sx={{
            ...headerIconBtnSx,
            // Just the avatar, no plate: it sits in a phone header next to other bare icons.
            bgcolor: 'transparent',
            borderColor: 'transparent',
            '&:hover': { bgcolor: 'transparent' },
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
      )}
      <Menu
        anchorEl={anchor}
        open={open}
        onClose={() => setAnchor(null)}
        anchorOrigin={variant === 'row' ? { vertical: 'top', horizontal: 'left' } : { vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={variant === 'row' ? { vertical: 'bottom', horizontal: 'left' } : { vertical: 'top', horizontal: 'right' }}
        PaperProps={{
          sx: {
            bgcolor: 'var(--bt-paper)',
            backgroundImage: 'none',
            border: '1px solid var(--bt-hairline)',
            borderRadius: 2,
            mt: variant === 'row' ? -1 : 1,
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
        <MenuItem onClick={() => { setAnchor(null); colorMode.toggle(); }} sx={{ minHeight: 44 }}>
          <ListItemIcon>{colorMode.mode === 'dark' ? <Sun size={20} weight="bold" /> : <Moon size={20} weight="bold" />}</ListItemIcon>
          {colorMode.mode === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        </MenuItem>
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
