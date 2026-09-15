import { Box, type BoxProps } from '@mui/material';
import { floatingPanelSx } from '@/theme/effects';

export function AdminIsland({ sx, ...props }: BoxProps) {
  return (
    <Box
      {...props}
      sx={{
        ...floatingPanelSx,
        ...sx,
      }}
    />
  );
}

export const TIER_LABELS: Record<string, string> = {
  free: 'Базовый',
  trial: 'Пробный',
  pro: 'Pro',
  proplus: 'Pro+',
  ultra: 'Ultra',
  creator: 'Creator',
  start: 'Pro',
  max: 'Ultra',
};

export function formatExpiry(expiresAt?: number | null): string {
  if (!expiresAt) return 'бессрочно';
  return new Date(expiresAt * 1000).toLocaleDateString('ru-RU');
}
