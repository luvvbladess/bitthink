import { Box, IconButton, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { WarningCircle, X } from '@phosphor-icons/react';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/api/client';
import { formatResetIn, type Subscription, type UsageWindow } from '@/api/billing';

type Notice = {
  id: string;
  text: string;
  resetsAt: number;
};

const STORAGE_PREFIX = 'quota-notice:';

function dismissed(id: string, resetsAt: number): boolean {
  try {
    return localStorage.getItem(`${STORAGE_PREFIX}${id}:${resetsAt}`) === '1';
  } catch {
    return false;
  }
}

function dismiss(id: string, resetsAt: number) {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${id}:${resetsAt}`, '1');
  } catch {
    /* ignore quota / private mode */
  }
}

function windowNotice(id: string, label: string, win?: UsageWindow): Notice | null {
  if (!win?.limit || (win.ratio || 0) < 0.9) return null;
  const resetsAt = win.resets_at || 0;
  const pct = Math.min(100, Math.round((win.ratio || 0) * 100));
  return {
    id,
    resetsAt,
    text: `Потрачено ${pct}% ${label}. Следующий сброс через ${formatResetIn(resetsAt)}.`,
  };
}

function pickNotice(sub?: Subscription, isComputer?: boolean): Notice | null {
  if (!sub || sub.unlimited) return null;
  if (sub.tier === 'free') {
    const used = sub.free_daily?.replies || 0;
    const limit = sub.free_daily?.replies_limit || 0;
    if (!limit || used / limit < 0.9) return null;
    const resetsAt = sub.free_daily?.resets_at || 0;
    const pct = Math.min(100, Math.round((used / limit) * 100));
    return {
      id: 'free.replies',
      resetsAt,
      text: `Потрачено ${pct}% дневной квоты ответов. Следующий сброс через ${formatResetIn(resetsAt)}.`,
    };
  }
  const family = isComputer ? sub.windows?.computer : sub.windows?.chat;
  return (
    windowNotice(`${isComputer ? 'computer' : 'chat'}.session`, isComputer ? 'пятичасовой квоты Пилота' : 'пятичасовой квоты', family?.session) ||
    windowNotice(`${isComputer ? 'computer' : 'chat'}.week`, isComputer ? 'недельной квоты Пилота' : 'недельной квоты', family?.week) ||
    windowNotice(`${isComputer ? 'computer' : 'chat'}.month`, isComputer ? 'месячной квоты Пилота' : 'месячной квоты', family?.month)
  );
}

export function QuotaNotice() {
  const [hidden, setHidden] = useState(false);
  const { data: sub } = useQuery<Subscription>({
    queryKey: ['subscription'],
    queryFn: () => apiFetch('/billing/subscription'),
    staleTime: 15_000,
  });
  const { data: models } = useQuery<{ selected?: string }>({
    queryKey: ['models'],
    queryFn: () => apiFetch('/models'),
    staleTime: 10_000,
  });
  const notice = useMemo(
    () => pickNotice(sub, models?.selected === 'director'),
    [sub, models?.selected],
  );

  useEffect(() => {
    setHidden(false);
  }, [notice?.id, notice?.resetsAt]);

  if (!notice || hidden || dismissed(notice.id, notice.resetsAt)) return null;

  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        mb: 1,
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        pl: 1.25,
        pr: 0.5,
        py: 0.5,
        minHeight: 44,
        borderRadius: 2,
        bgcolor: 'var(--bt-panel)',
        border: '1px solid var(--bt-line)',
        boxShadow: 'var(--bt-shadow)',
        color: 'primary.light',
      }}
    >
      <WarningCircle size={18} weight="fill" color="currentColor" aria-hidden />
      <Typography
        variant="body2"
        sx={{ flex: 1, minWidth: 0, color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.4 }}
      >
        {notice.text}
      </Typography>
      <IconButton
        aria-label="Скрыть уведомление"
        onClick={() => {
          dismiss(notice.id, notice.resetsAt);
          setHidden(true);
        }}
        sx={{
          width: 44,
          height: 44,
          color: 'text.muted',
          flexShrink: 0,
          '&:hover': { color: 'text.primary' },
        }}
      >
        <X size={16} weight="bold" />
      </IconButton>
    </Box>
  );
}
