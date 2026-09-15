import { Box, IconButton, Tooltip } from '@mui/material';
import { Moon, Sun } from '@phosphor-icons/react';
import { useColorMode } from '@/theme/ColorMode';
import { headerIconBtnSx } from '@/theme/effects';

export function ColorModeToggle() {
  const { mode, toggle } = useColorMode();
  const next = mode === 'dark' ? 'светлую' : 'тёмную';
  const label = `Включить ${next} тему`;

  return (
    <Tooltip title={label}>
      <IconButton onClick={toggle} sx={headerIconBtnSx} aria-label={label}>
        {mode === 'dark' ? <Sun size={22} weight="bold" /> : <Moon size={22} weight="bold" />}
      </IconButton>
    </Tooltip>
  );
}

export function ColorModeSwitch() {
  const { preference, setPreference } = useColorMode();
  const options: { id: typeof preference; label: string }[] = [
    { id: 'system', label: 'Система' },
    { id: 'light', label: 'Светлая' },
    { id: 'dark', label: 'Тёмная' },
  ];

  return (
    <Box
      role="radiogroup"
      aria-label="Тема оформления"
      sx={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 0.5,
        p: 0.5,
        borderRadius: '14px',
        bgcolor: 'var(--bt-overlay-faint)',
        border: '1px solid var(--bt-hairline)',
      }}
    >
      {options.map((option) => {
        const selected = preference === option.id;
        return (
          <Box
            key={option.id}
            component="button"
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => setPreference(option.id)}
            sx={{
              minHeight: 44,
              px: 1,
              border: 0,
              cursor: 'pointer',
              font: 'inherit',
              fontSize: '0.875rem',
              fontWeight: selected ? 600 : 500,
              borderRadius: '10px',
              color: selected ? 'primary.contrastText' : 'text.secondary',
              bgcolor: selected ? 'primary.main' : 'transparent',
              WebkitTapHighlightColor: 'transparent',
              transition:
                'background-color 0.18s cubic-bezier(0.23, 1, 0.32, 1), color 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
              '@media (hover: hover) and (pointer: fine)': {
                '&:hover': {
                  color: selected ? 'primary.contrastText' : 'text.primary',
                  bgcolor: selected ? 'primary.dark' : 'var(--bt-overlay)',
                },
              },
              '&:active': {
                transform: 'scale(0.98)',
              },
            }}
          >
            {option.label}
          </Box>
        );
      })}
    </Box>
  );
}
