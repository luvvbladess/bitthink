/** Shared chrome tokens. Colors come from theme CSS variables so both modes stay in family. */

export const GLOW = {
  cyan: 'var(--bt-glow-strong)',
  cyanStrong: 'var(--bt-glow-strong)',
  cyanLine: 'var(--bt-line)',
  ink: 'var(--bt-scrim)',
};

/** Hover only for mouse. Touch keeps :hover after tap and punches a hole through the button. */
export const HOVER_FINE = '@media (hover: hover) and (pointer: fine)';

/** Press: frost the content behind, never drop to a see-through fill. */
export const tapPressSx = {
  WebkitTapHighlightColor: 'transparent',
  '&:active': {
    transform: 'scale(0.97)',
    bgcolor: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
    backdropFilter: 'blur(18px) saturate(1.2)',
    WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
  },
  '@media (prefers-reduced-motion: reduce)': {
    '&:active': { transform: 'none' },
  },
  '@media (prefers-reduced-transparency: reduce)': {
    '&:active': {
      bgcolor: 'var(--bt-elevated)',
      backdropFilter: 'none',
      WebkitBackdropFilter: 'none',
    },
  },
} as const;

export const composerIconBtnSx = {
  width: { xs: 44, sm: 36 },
  height: { xs: 44, sm: 36 },
  borderRadius: '10px',
  color: 'text.secondary',
  flexShrink: 0,
  ...tapPressSx,
  transition: 'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
  [HOVER_FINE]: {
    '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay)' },
  },
  '@media (hover: none), (pointer: coarse)': {
    '&:hover': { color: 'text.secondary', bgcolor: 'transparent' },
  },
  '&:focus-visible': {
    outline: '2px solid',
    outlineColor: 'primary.main',
    outlineOffset: 2,
  },
} as const;

/** Quiet pill for modes inside the composer. Selected = tint, not a second CTA. */
export const composerChipSx = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  height: { xs: 44, sm: 36 },
  minHeight: { xs: 44, sm: 36 },
  minWidth: 0,
  px: { xs: 1, sm: 1.1 },
  borderRadius: '999px',
  border: '1px solid var(--bt-hairline)',
  bgcolor: 'transparent',
  color: 'text.secondary',
  boxShadow: 'none',
  font: 'inherit',
  fontSize: '0.8125rem',
  fontWeight: 600,
  textTransform: 'none' as const,
  gap: 0.6,
  cursor: 'pointer',
  flexShrink: 0,
  ...tapPressSx,
  transition:
    'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
  [HOVER_FINE]: {
    '&:hover': {
      color: 'text.primary',
      bgcolor: 'var(--bt-overlay-faint)',
      borderColor: 'var(--bt-hairline)',
    },
  },
  '@media (hover: none), (pointer: coarse)': {
    '&:hover': {
      color: 'text.secondary',
      bgcolor: 'transparent',
      borderColor: 'var(--bt-hairline)',
    },
  },
  '&:focus-visible': {
    outline: '2px solid',
    outlineColor: 'primary.main',
    outlineOffset: 2,
  },
} as const;

export const composerChipSelectedSx = {
  color: 'primary.light',
  bgcolor: 'var(--bt-glow)',
  borderColor: 'var(--bt-line)',
  [HOVER_FINE]: {
    '&:hover': {
      color: 'primary.light',
      bgcolor: 'var(--bt-glow-strong)',
      borderColor: 'var(--bt-line)',
    },
  },
  '&:active': {
    transform: 'scale(0.97)',
    bgcolor: 'var(--bt-glow-strong)',
    backdropFilter: 'blur(18px) saturate(1.2)',
    WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
  },
} as const;

/** Chrome actions: sidebar, export, account. Same family as composer icons. */
export const headerIconBtnSx = {
  width: 44,
  height: 44,
  borderRadius: '12px',
  color: 'text.primary',
  bgcolor: 'var(--bt-elevated)',
  border: '1px solid var(--bt-hairline)',
  boxShadow: 'var(--bt-shadow)',
  flexShrink: 0,
  ...tapPressSx,
  transition:
    'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
  [HOVER_FINE]: {
    '&:hover': {
      color: 'primary.light',
      bgcolor: 'var(--bt-glow)',
      borderColor: 'var(--bt-line)',
    },
  },
  '@media (hover: none), (pointer: coarse)': {
    '&:hover': {
      color: 'text.primary',
      bgcolor: 'var(--bt-elevated)',
      borderColor: 'var(--bt-hairline)',
    },
  },
  '&:focus-visible': {
    outline: '2px solid',
    outlineColor: 'primary.main',
    outlineOffset: 2,
  },
  '&.Mui-disabled': {
    color: 'text.disabled',
    bgcolor: 'var(--bt-overlay-faint)',
    borderColor: 'var(--bt-hairline)',
    opacity: 1,
  },
} as const;

/** Static floating island: composer and clarify list share this shell. */
export const floatingPanelSx = {
  borderRadius: '22px',
  bgcolor: 'var(--bt-panel)',
  backgroundImage: 'linear-gradient(180deg, var(--bt-glow) 0%, transparent 46%)',
  border: '1px solid',
  borderColor: 'var(--bt-line)',
  boxShadow: 'var(--bt-composer-shadow)',
} as const;

export const composerShellSx = {
  ...floatingPanelSx,
  transition: 'border-color 0.22s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.22s cubic-bezier(0.23, 1, 0.32, 1)',
  '@media (prefers-reduced-motion: no-preference)': {
    animation: 'composer-breathe 4.8s ease-in-out infinite',
  },
  '@keyframes composer-breathe': {
    '0%, 100%': { boxShadow: 'var(--bt-composer-shadow)' },
    '50%': { boxShadow: 'var(--bt-composer-shadow-mid)' },
  },
  '&:focus-within': {
    animation: 'none',
    borderColor: 'primary.light',
    boxShadow: 'var(--bt-composer-shadow-focus)',
  },
} as const;
