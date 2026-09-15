import { Box } from '@mui/material';

export function GlowSwitch({ checked }: { checked: boolean }) {
  return (
    <Box
      aria-hidden
      className="glow-switch-track"
      sx={{
        position: 'relative',
        width: 44,
        height: 24,
        flexShrink: 0,
        border: '1px solid',
        borderColor: checked ? 'primary.main' : 'var(--bt-overlay-strong)',
        borderRadius: '999px',
        bgcolor: checked ? 'primary.main' : 'var(--bt-overlay)',
        boxShadow: checked ? 'var(--bt-halo)' : 'var(--bt-inset)',
        pointerEvents: 'none',
        transition:
          'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
        '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: 3,
          left: 3,
          width: 16,
          height: 16,
          borderRadius: '50%',
          bgcolor: checked ? 'primary.contrastText' : 'text.primary',
          boxShadow: '0 1px 3px rgba(0, 0, 0, 0.28)',
          transform: checked ? 'translateX(20px)' : 'translateX(0)',
          transition: 'transform 0.16s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
          '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
        }}
      />
    </Box>
  );
}
