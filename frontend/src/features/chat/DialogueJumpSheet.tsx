import { Box, SwipeableDrawer, Typography } from '@mui/material';
import { MapTrifold } from '@phosphor-icons/react';
import { useReducedMotion } from 'framer-motion';
import { type DialogueTick, snippetQuestion } from './dialogueNav';

export function DialogueJumpChip({ count, onClick }: { count: number; onClick: () => void }) {
  const reduce = useReducedMotion();
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      aria-label={`Вопросы в этом диалоге, ${count}`}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.7,
        minHeight: 40,
        px: 1.25,
        borderRadius: '999px',
        border: '1px solid var(--bt-hairline)',
        bgcolor: 'var(--bt-elevated)',
        boxShadow: 'var(--bt-shadow)',
        color: 'text.secondary',
        font: 'inherit',
        fontSize: '0.8125rem',
        fontWeight: 600,
        letterSpacing: '-0.02em',
        cursor: 'pointer',
        WebkitTapHighlightColor: 'transparent',
        transition: reduce ? 'none' : 'background-color 0.16s cubic-bezier(0.22, 1, 0.36, 1), color 0.16s cubic-bezier(0.22, 1, 0.36, 1), border-color 0.16s cubic-bezier(0.22, 1, 0.36, 1)',
        '@media (hover: hover) and (pointer: fine)': {
          '&:hover': {
            color: 'primary.light',
            bgcolor: 'var(--bt-glow)',
            borderColor: 'var(--bt-line)',
          },
        },
        '@media (hover: none), (pointer: coarse)': {
          '&:hover': {
            color: 'text.secondary',
            bgcolor: 'var(--bt-elevated)',
            borderColor: 'var(--bt-hairline)',
          },
        },
        '&:focus-visible': {
          color: 'primary.light',
          bgcolor: 'var(--bt-glow)',
          borderColor: 'var(--bt-line)',
        },
        '&:active': {
          transform: reduce ? 'none' : 'scale(0.97)',
          bgcolor: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
          backdropFilter: 'blur(18px) saturate(1.2)',
          WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
        },
      }}
    >
      <MapTrifold size={16} weight="bold" />
      Вопросы
      <Box
        component="span"
        sx={{
          minWidth: 18,
          height: 18,
          px: 0.45,
          borderRadius: 99,
          display: 'grid',
          placeItems: 'center',
          fontSize: '0.6875rem',
          fontVariantNumeric: 'tabular-nums',
          bgcolor: 'var(--bt-glow)',
          color: 'primary.light',
        }}
      >
        {count}
      </Box>
    </Box>
  );
}

interface Props {
  open: boolean;
  questions: DialogueTick[];
  onClose: () => void;
  onOpen: () => void;
  onJump: (id: string) => void;
}

export function DialogueJumpSheet({ open, questions, onClose, onOpen, onJump }: Props) {
  const reduce = useReducedMotion();

  return (
    <SwipeableDrawer
      anchor="bottom"
      open={open}
      onClose={onClose}
      onOpen={onOpen}
      disableDiscovery
      PaperProps={{
        sx: {
          height: 'min(72vh, 560px)',
          borderTopLeftRadius: '18px',
          borderTopRightRadius: '18px',
          bgcolor: 'var(--bt-paper)',
          backgroundImage: 'none',
          border: '1px solid var(--bt-hairline)',
        },
      }}
      BackdropProps={{ sx: { bgcolor: 'var(--bt-scrim)' } }}
    >
      <Box sx={{ width: 40, height: 4, borderRadius: 99, bgcolor: 'var(--bt-overlay-strong)', mx: 'auto', mt: 1.25, mb: 0.5 }} />
      <Typography sx={{ px: 2, py: 1, fontWeight: 600, fontSize: '1rem', letterSpacing: '-0.02em' }}>
        Вопросы в диалоге
      </Typography>
      <Box sx={{ overflow: 'auto', pb: 'max(16px, env(safe-area-inset-bottom))' }}>
        {questions.map((item, index) => (
          <Box
            key={item.id}
            component="button"
            type="button"
            onClick={() => {
              onJump(item.id);
              onClose();
            }}
            sx={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 1.25,
              width: '100%',
              minHeight: 52,
              px: 2,
              py: 1.25,
              border: 0,
              bgcolor: 'transparent',
              color: 'text.primary',
              textAlign: 'left',
              font: 'inherit',
              cursor: 'pointer',
              WebkitTapHighlightColor: 'transparent',
              transition: reduce ? 'none' : 'background-color 0.18s cubic-bezier(0.22, 1, 0.36, 1)',
              '&:hover, &:focus-visible': { bgcolor: 'var(--bt-glow)' },
              '&:active': { bgcolor: 'var(--bt-glow-strong)' },
            }}
          >
            <Box
              sx={{
                width: 22,
                height: 22,
                borderRadius: '7px',
                flexShrink: 0,
                mt: '1px',
                display: 'grid',
                placeItems: 'center',
                fontSize: '0.6875rem',
                fontWeight: 700,
                fontVariantNumeric: 'tabular-nums',
                color: 'primary.light',
                bgcolor: 'var(--bt-glow)',
              }}
            >
              {index + 1}
            </Box>
            <Box sx={{ fontSize: '0.9375rem', lineHeight: 1.45, letterSpacing: '-0.01em' }}>
              {snippetQuestion(item.label, 140)}
            </Box>
          </Box>
        ))}
      </Box>
    </SwipeableDrawer>
  );
}
