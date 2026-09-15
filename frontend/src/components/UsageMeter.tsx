import { Box, LinearProgress, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import { formatTokens } from '@/constants/tiers';

type Props = {
  label: string;
  used: number;
  limit: number;
  remaining?: number | null;
  caption?: string;
  icon?: ReactNode;
  count?: boolean;
};

export function UsageMeter({ label, used, limit, remaining, caption, icon, count }: Props) {
  const left = remaining ?? Math.max(0, limit - used);
  const ratio = limit > 0 ? Math.min(1, used / limit) : 0;
  const leftLabel = count ? String(left) : formatTokens(left);
  const limitLabel = count ? String(limit) : formatTokens(limit);
  const tight = ratio >= 0.9;

  return (
    <Box sx={{ minWidth: 0 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1} sx={{ mb: 0.7 }}>
        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0, color: 'text.secondary' }}>
          {icon}
          <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary', letterSpacing: '-0.015em' }}>
            {label}
          </Typography>
        </Stack>
        <Typography
          variant="body2"
          sx={{
            fontWeight: 600,
            fontVariantNumeric: 'tabular-nums',
            whiteSpace: 'nowrap',
            color: tight ? 'error.main' : 'text.primary',
          }}
        >
          {leftLabel}
          <Box component="span" sx={{ color: 'text.secondary', fontWeight: 500 }}>
            {' '}из {limitLabel}
          </Box>
        </Typography>
      </Stack>
      <LinearProgress
        variant="determinate"
        value={ratio * 100}
        aria-label={`${label}: осталось ${leftLabel} из ${limitLabel}`}
        sx={{
          height: 8,
          borderRadius: 99,
          bgcolor: 'var(--bt-overlay)',
          '& .MuiLinearProgress-bar': {
            borderRadius: 99,
            bgcolor: tight ? 'error.main' : 'primary.main',
          },
        }}
      />
      {caption ? (
        <Typography sx={{ color: 'text.secondary', display: 'block', mt: 0.55, fontSize: '0.75rem', lineHeight: 1.4 }}>
          {caption}
        </Typography>
      ) : null}
    </Box>
  );
}
