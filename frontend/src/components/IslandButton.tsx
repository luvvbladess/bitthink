import { Button, styled } from '@mui/material';
import { HOVER_FINE } from '@/theme/effects';

export const IslandButton = styled(Button)(({ theme }) => ({
  borderRadius: 10,
  padding: '0.5rem 1rem',
  fontWeight: 600,
  background: 'transparent',
  border: `1px solid ${theme.palette.divider}`,
  color: theme.palette.text.primary,
  boxShadow: 'none',
  [HOVER_FINE]: {
    '&:hover': {
      background: 'var(--bt-overlay-faint)',
      boxShadow: 'none',
    },
  },
  '&:active': {
    transform: 'scale(0.98)',
    background: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
    backdropFilter: 'blur(16px) saturate(1.15)',
    WebkitBackdropFilter: 'blur(16px) saturate(1.15)',
  },
}));

export const PrimaryButton = styled(Button)(({ theme }) => ({
  borderRadius: 10,
  padding: '0.55rem 1.15rem',
  fontWeight: 600,
  background: theme.palette.primary.main,
  color: theme.palette.primary.contrastText,
  boxShadow: 'var(--bt-halo)',
  [HOVER_FINE]: {
    '&:hover': {
      background: theme.palette.primary.dark,
      boxShadow: 'var(--bt-halo-strong)',
    },
  },
  '&:active': { transform: 'scale(0.98)' },
}));
