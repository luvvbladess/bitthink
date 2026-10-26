import { useState } from 'react';
import { Box } from '@mui/material';
import type { ModeSwitch } from './modeSwitch';
import { useSelectedModel, useModePreferencesBusy } from '@/components/ModelSelector';

interface Props {
  suggestion: ModeSwitch;
  onAccept: () => void | Promise<unknown>;
}

export function ModeSwitchCard({ suggestion, onAccept }: Props) {
  const accepted = useSelectedModel() === suggestion.model;
  const busy = useModePreferencesBusy();
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  return (
    <Box sx={{ mt: 1.25 }}>
      <Box
        component="button"
        type="button"
        disabled={accepted || pending || busy}
        aria-busy={pending || busy}
        aria-label={accepted ? suggestion.done : suggestion.accept}
        onClick={async () => {
          if (accepted || pending || busy) return;
          setPending(true);
          setError('');
          try { await onAccept(); }
          catch { setError('Не удалось подтвердить переключение режима. Проверьте подключение и повторите действие.'); }
          finally { setPending(false); }
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
      {error && !accepted && <Box role="alert" sx={{ fontSize: 13, color: 'text.secondary', mt: 1 }}>{error}</Box>}
    </Box>
  );
}
