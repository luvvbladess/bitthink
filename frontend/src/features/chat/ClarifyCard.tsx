import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Menu, MenuItem, TextField } from '@mui/material';
import { CaretDown, Check } from '@phosphor-icons/react';
import { floatingPanelSx } from '@/theme/effects';
import { formatClarifyReply, isOtherOption, type ClarifyQuestion } from './clarify';

interface Props {
  questions: ClarifyQuestion[];
  onSubmit: (text: string) => void;
}

const optionRowSx = {
  display: 'flex',
  alignItems: 'center',
  gap: 1.1,
  width: '100%',
  minHeight: 44,
  px: 1.15,
  py: 0.7,
  borderRadius: '14px',
  border: '1px solid transparent',
  textAlign: 'left' as const,
  font: 'inherit',
  fontSize: '0.9375rem',
  cursor: 'pointer',
  transition:
    'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
};

export function ClarifyCard({ questions, onSubmit }: Props) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Array<string | null>>(() => questions.map(() => null));
  const [otherDraft, setOtherDraft] = useState('');
  const [menuEl, setMenuEl] = useState<HTMLElement | null>(null);
  const submitted = useRef(false);
  const customRef = useRef<HTMLInputElement>(null);
  const current = questions[index];
  const total = questions.length;
  const canConfirmCustom = otherDraft.trim().length > 0;

  const selectedCustom = useMemo(() => {
    const value = answers[index];
    if (!value || !current) return false;
    return !current.options.includes(value);
  }, [answers, current, index]);

  useEffect(() => {
    if (!current) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        skipCurrent();
        return;
      }
      const num = Number(event.key);
      if (num >= 1 && num <= (current.options.length || 0)) {
        event.preventDefault();
        pick(current.options[num - 1]);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const finish = (nextAnswers: Array<string | null>) => {
    if (submitted.current) return;
    submitted.current = true;
    onSubmit(formatClarifyReply(questions, nextAnswers));
  };

  const goNext = (nextAnswers: Array<string | null>, from: number) => {
    const upcoming = questions.findIndex((_, i) => i > from && !nextAnswers[i]);
    if (upcoming >= 0) {
      setIndex(upcoming);
      setOtherDraft('');
      return;
    }
    finish(nextAnswers);
  };

  const pick = (label: string) => {
    if (!current) return;
    if (isOtherOption(label)) {
      customRef.current?.focus();
      return;
    }
    const next = [...answers];
    next[index] = label;
    setAnswers(next);
    goNext(next, index);
  };

  const confirmCustom = () => {
    const text = otherDraft.trim();
    if (!text) return;
    const next = [...answers];
    next[index] = text;
    setAnswers(next);
    setOtherDraft('');
    goNext(next, index);
  };

  const skipCurrent = () => {
    const next = [...answers];
    next[index] = next[index] || null;
    setAnswers(next);
    goNext(next, index);
  };

  if (!current) return null;

  return (
    <Box
      role="group"
      aria-label={current.prompt}
      sx={{
        ...floatingPanelSx,
        width: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.85,
        px: { xs: 1.35, sm: 1.6 },
        pt: 1.35,
        pb: 1.15,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.25, px: 0.35 }}>
        <Box sx={{ flex: 1, minWidth: 0, fontSize: '0.9375rem', fontWeight: 600, lineHeight: 1.4, letterSpacing: '-0.02em' }}>
          {current.prompt}
        </Box>
        {total > 1 && (
          <>
            <Box
              component="button"
              type="button"
              onClick={(event) => setMenuEl(event.currentTarget)}
              aria-label={`Вопрос ${index + 1} из ${total}`}
              aria-haspopup="menu"
              sx={{
                flexShrink: 0,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 0.3,
                minHeight: 32,
                px: 0.9,
                borderRadius: '999px',
                border: '1px solid var(--bt-line)',
                bgcolor: 'var(--bt-glow)',
                boxShadow: '0 0 12px var(--bt-glow-strong)',
                color: 'primary.light',
                font: 'inherit',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {index + 1}/{total}
              <CaretDown size={11} />
            </Box>
            <Menu
              anchorEl={menuEl}
              open={Boolean(menuEl)}
              onClose={() => setMenuEl(null)}
              MenuListProps={{ dense: true }}
            >
              {questions.map((question, i) => (
                <MenuItem
                  key={question.prompt}
                  selected={i === index}
                  onClick={() => {
                    setIndex(i);
                    setOtherDraft('');
                    setMenuEl(null);
                  }}
                >
                  {i + 1}. {question.prompt}
                  {answers[i] ? <Check size={14} style={{ marginLeft: 8 }} /> : null}
                </MenuItem>
              ))}
            </Menu>
          </>
        )}
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.45 }}>
        {current.options.map((option, optionIndex) => {
          const selected = answers[index] === option;
          return (
            <Box
              key={option}
              component="button"
              type="button"
              onClick={() => pick(option)}
              aria-label={`${optionIndex + 1}. ${option}`}
              sx={{
                ...optionRowSx,
                bgcolor: selected ? 'var(--bt-glow)' : 'var(--bt-overlay-faint)',
                borderColor: selected ? 'var(--bt-line)' : 'var(--bt-overlay-faint)',
                color: 'text.primary',
                boxShadow: selected ? '0 0 18px var(--bt-glow-strong)' : 'none',
                '&:hover': {
                  bgcolor: selected ? 'var(--bt-glow-strong)' : 'var(--bt-glow)',
                  borderColor: 'var(--bt-line)',
                },
                '&:active': { transform: 'scale(0.99)' },
                '&:focus-visible': {
                  outline: '2px solid',
                  outlineColor: 'primary.main',
                  outlineOffset: 2,
                },
              }}
            >
              <Box
                sx={{
                  width: 26,
                  height: 26,
                  flexShrink: 0,
                  borderRadius: '9px',
                  bgcolor: selected ? 'primary.main' : 'var(--bt-overlay)',
                  color: selected ? 'primary.contrastText' : 'text.muted',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  boxShadow: selected ? '0 0 12px var(--bt-glow-strong)' : 'none',
                }}
              >
                {optionIndex + 1}
              </Box>
              <Box sx={{ minWidth: 0 }}>{option}</Box>
            </Box>
          );
        })}
      </Box>

      <TextField
        inputRef={customRef}
        fullWidth
        placeholder="Свой вариант"
        value={otherDraft}
        onChange={(event) => setOtherDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            event.stopPropagation();
            confirmCustom();
          }
        }}
        variant="standard"
        InputProps={{
          disableUnderline: true,
          sx: {
            minHeight: 44,
            px: 1.15,
            borderRadius: '14px',
            border: '1px solid',
            borderColor: selectedCustom || canConfirmCustom ? 'var(--bt-line)' : 'var(--bt-overlay)',
            bgcolor: selectedCustom || canConfirmCustom ? 'var(--bt-glow)' : 'var(--bt-overlay-faint)',
            boxShadow: canConfirmCustom ? '0 0 16px var(--bt-glow-strong)' : 'none',
            fontSize: '0.9375rem',
            '& input::placeholder': { color: 'text.secondary', opacity: 0.9 },
          },
        }}
        inputProps={{ 'aria-label': 'Свой вариант' }}
      />

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 0.75, pt: 0.15 }}>
        <Box
          component="button"
          type="button"
          onClick={skipCurrent}
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 0.75,
            minHeight: 40,
            px: 1.35,
            borderRadius: '999px',
            border: '1px solid var(--bt-hairline)',
            bgcolor: 'transparent',
            color: 'text.secondary',
            font: 'inherit',
            fontSize: '0.8125rem',
            fontWeight: 600,
            cursor: 'pointer',
            '&:hover': { color: 'text.primary', borderColor: 'var(--bt-overlay-strong)' },
          }}
        >
          Пропустить
          <Box component="span" sx={{ color: 'text.muted', fontWeight: 500, fontSize: '0.75rem' }}>
            Enter
          </Box>
        </Box>
        <Box
          component="button"
          type="button"
          disabled={!canConfirmCustom}
          onClick={confirmCustom}
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            minHeight: 40,
            px: 1.5,
            borderRadius: '999px',
            border: '1px solid',
            borderColor: canConfirmCustom ? 'primary.main' : 'var(--bt-hairline)',
            bgcolor: canConfirmCustom ? 'primary.main' : 'transparent',
            color: canConfirmCustom ? 'primary.contrastText' : 'text.muted',
            boxShadow: canConfirmCustom ? '0 0 18px var(--bt-line)' : 'none',
            font: 'inherit',
            fontSize: '0.8125rem',
            fontWeight: 700,
            cursor: canConfirmCustom ? 'pointer' : 'default',
          }}
        >
          Далее
        </Box>
      </Box>
    </Box>
  );
}
