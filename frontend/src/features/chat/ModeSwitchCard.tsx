import { useState } from 'react';
import { Box } from '@mui/material';
import type { ModeSwitch } from './modeSwitch';

interface Props {
  suggestion: ModeSwitch;
  onAccept: () => void | Promise<void>;
}

export function ModeSwitchCard({ suggestion, onAccept }: Props) {
  const [accepted, setAccepted] = useState(false);
  const [pending, setPending] = useState(false);
  return (
    <Box sx={{ mt: 1.25 }}>
      <Box
        component="button"
        type="button"
        disabled={accepted || pending}
        aria-label={accepted ? suggestion.done : suggestion.accept}
        onClick={() => {
          if (accepted || pending) return;
          setPending(true);
          Promise.resolve(onAccept())
            .then(() => setAccepted(true))
            .finally(() => setPending(false));
        }}
        sx={{
          border: 0,
          borderRadius: '999px',
          px: 2.25,
          py: 1.15,
          minHeight: 44,
          bgcolor: 'primary.main',
          color: '#0b1214',
          font: 'inherit',
          fontWeight: 600,
          fontSize: '0.9375rem',
          letterSpacing: '-0.01em',
          cursor: accepted ? 'default' : 'pointer',
          opacity: accepted ? 0.85 : 1,
          '&:hover': accepted ? undefined : { bgcolor: '#1a9aab' },
          '&:focus-visible': { outline: '2px solid #21A0CE', outlineOffset: 2 },
          '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
        }}
      >
        {accepted ? suggestion.done : suggestion.accept}
      </Box>
    </Box>
  );
}
