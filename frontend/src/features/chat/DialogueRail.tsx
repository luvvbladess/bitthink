import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, useMediaQuery, useTheme } from '@mui/material';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { MIN_DIALOGUE_QUESTIONS, type DialogueTick, messageOffset, snippetQuestion } from './dialogueNav';

export type { DialogueTick };

interface Props {
  scroller: HTMLElement | null;
  questions: DialogueTick[];
  onJump: (id: string) => void;
}

const EASE = [0.22, 1, 0.36, 1] as const;
const TRACK_PAD = 10;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function spread(values: number[], minGap: number, lo: number, hi: number) {
  if (values.length < 2) return values;
  const next = [...values];
  for (let pass = 0; pass < 8; pass += 1) {
    for (let i = 1; i < next.length; i += 1) {
      if (next[i] - next[i - 1] < minGap) {
        const mid = (next[i] + next[i - 1]) / 2;
        next[i - 1] = mid - minGap / 2;
        next[i] = mid + minGap / 2;
      }
    }
    next[0] = Math.max(lo, next[0]);
    next[next.length - 1] = Math.min(hi, next[next.length - 1]);
  }
  return next;
}

export function DialogueRail({ scroller, questions, onJump }: Props) {
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up('md'));
  const reduce = useReducedMotion();
  const railRef = useRef<HTMLDivElement>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [layout, setLayout] = useState<{ tops: number[]; viewTop: number; viewH: number; height: number }>({
    tops: [],
    viewTop: 0,
    viewH: 24,
    height: 0,
  });
  const canHover = typeof window !== 'undefined' && window.matchMedia('(hover: hover)').matches;

  const items = useMemo(
    () => questions.map((q) => ({ ...q, preview: snippetQuestion(q.label) })),
    [questions]
  );

  useEffect(() => {
    if (!desktop || !scroller || items.length < MIN_DIALOGUE_QUESTIONS) return;
    let raf = 0;
    const measure = () => {
      raf = 0;
      const height = railRef.current?.clientHeight || 0;
      const track = Math.max(1, height - TRACK_PAD * 2);
      const span = Math.max(1, scroller.scrollHeight);
      const raw = items.map((item) => TRACK_PAD + clamp(messageOffset(scroller, item.id) / span, 0.03, 0.97) * track);
      const tops = spread(raw, 18, TRACK_PAD, TRACK_PAD + track);
      const maxScroll = Math.max(1, scroller.scrollHeight - scroller.clientHeight);
      const viewH = clamp((scroller.clientHeight / span) * track, 18, track * 0.72);
      const viewTop = TRACK_PAD + clamp(scroller.scrollTop / maxScroll, 0, 1) * (track - viewH);
      setLayout({ tops, viewTop, viewH, height });
      const mid = scroller.scrollTop + scroller.clientHeight * 0.38;
      let current = items[0]?.id || null;
      for (const item of items) {
        if (messageOffset(scroller, item.id) <= mid) current = item.id;
      }
      setActiveId(current);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    measure();
    scroller.addEventListener('scroll', schedule, { passive: true });
    const ro = new ResizeObserver(schedule);
    ro.observe(scroller);
    if (railRef.current) ro.observe(railRef.current);
    return () => {
      scroller.removeEventListener('scroll', schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [desktop, scroller, items]);

  if (!desktop || items.length < MIN_DIALOGUE_QUESTIONS) return null;

  const hoveredIndex = items.findIndex((item) => item.id === hoverId);
  const hovered = hoveredIndex >= 0 ? items[hoveredIndex] : null;
  const hoverTop = hoveredIndex >= 0 ? layout.tops[hoveredIndex] : 0;

  return (
    <Box
      ref={railRef}
      aria-label="Вопросы в диалоге"
      sx={{
        position: 'absolute',
        top: 76,
        bottom: 156,
        width: 32,
        zIndex: 2,
        right: { xs: 12, md: 'max(12px, calc((100% - 768px) / 2 - 40px))' },
        pointerEvents: 'none',
      }}
    >
      <motion.div
        initial={reduce ? false : { opacity: 0, x: 10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.35, ease: EASE }}
        style={{ position: 'relative', height: '100%', pointerEvents: 'auto' }}
      >
        <Box
          sx={{
            position: 'absolute',
            top: TRACK_PAD,
            bottom: TRACK_PAD,
            left: '50%',
            width: 2,
            ml: '-1px',
            borderRadius: 99,
            bgcolor: 'var(--bt-overlay-strong)',
          }}
        />
        <Box
          aria-hidden
          sx={{
            position: 'absolute',
            left: '50%',
            width: 4,
            ml: '-2px',
            borderRadius: 99,
            bgcolor: 'primary.main',
            opacity: 0.28,
            top: layout.viewTop,
            height: layout.viewH,
            transition: reduce ? 'none' : 'top 0.2s cubic-bezier(0.22, 1, 0.36, 1), height 0.2s cubic-bezier(0.22, 1, 0.36, 1)',
            pointerEvents: 'none',
          }}
        />

        {items.map((item, index) => {
          const top = layout.tops[index] ?? TRACK_PAD;
          const active = item.id === activeId;
          const lit = active || item.id === hoverId;
          return (
            <Box
              key={item.id}
              component="button"
              type="button"
              aria-label={item.preview}
              aria-current={active ? 'true' : undefined}
              onMouseEnter={() => canHover && setHoverId(item.id)}
              onMouseLeave={() => setHoverId((id) => (id === item.id ? null : id))}
              onFocus={() => setHoverId(item.id)}
              onBlur={() => setHoverId((id) => (id === item.id ? null : id))}
              onClick={() => {
                onJump(item.id);
                setActiveId(item.id);
                setHoverId(item.id);
                window.setTimeout(() => {
                  setHoverId((id) => (id === item.id ? null : id));
                }, 1400);
              }}
              sx={{
                position: 'absolute',
                left: 0,
                top,
                transform: 'translateY(-50%)',
                width: 32,
                height: 28,
                minHeight: 28,
                p: 0,
                border: 0,
                bgcolor: 'transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                WebkitTapHighlightColor: 'transparent',
                touchAction: 'manipulation',
                '&:focus-visible': {
                  outline: '2px solid',
                  outlineColor: 'primary.main',
                  outlineOffset: -2,
                  borderRadius: 1,
                },
              }}
            >
              <Box
                sx={{
                  width: lit ? 16 : 10,
                  height: lit ? 3 : 2,
                  borderRadius: 99,
                  bgcolor: lit ? 'primary.main' : 'text.muted',
                  boxShadow: lit ? 'var(--bt-halo)' : 'none',
                  opacity: lit ? 1 : 0.7,
                  transition: reduce
                    ? 'none'
                    : 'width 0.22s cubic-bezier(0.22, 1, 0.36, 1), height 0.22s cubic-bezier(0.22, 1, 0.36, 1), background-color 0.22s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.22s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.22s cubic-bezier(0.22, 1, 0.36, 1)',
                }}
              />
            </Box>
          );
        })}

        <AnimatePresence>
          {hovered && (
            <Box
              sx={{
                position: 'absolute',
                right: 36,
                top: hoverTop,
                transform: 'translateY(-50%)',
                pointerEvents: 'none',
                zIndex: 3,
              }}
            >
              <motion.div
                key={hovered.id}
                initial={reduce ? { opacity: 1 } : { opacity: 0, x: 14, scale: 0.96 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={reduce ? { opacity: 0 } : { opacity: 0, x: 10, scale: 0.98 }}
                transition={{ duration: 0.22, ease: EASE }}
              >
                <Box
                  sx={{
                    maxWidth: 280,
                    px: 1.35,
                    py: 1,
                    borderRadius: '12px',
                    bgcolor: 'var(--bt-elevated)',
                    border: '1px solid var(--bt-hairline)',
                    boxShadow: 'var(--bt-shadow-menu)',
                    color: 'text.primary',
                    fontSize: '0.8125rem',
                    lineHeight: 1.45,
                    letterSpacing: '-0.01em',
                  }}
                >
                  {hovered.preview}
                </Box>
              </motion.div>
            </Box>
          )}
        </AnimatePresence>
      </motion.div>
    </Box>
  );
}
