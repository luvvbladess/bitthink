import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Box, Collapse } from '@mui/material';
import { Brain, CaretDown } from '@phosphor-icons/react';

export interface SearchItem {
  query: string;
  summary: string;
}

interface Props {
  reasoning?: string;
  /** Reasoning is actively streaming in — force the panel open and auto-scroll to the newest text. */
  live?: boolean;
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function CollapsibleSection({
  icon,
  label,
  maxHeight = 280,
  live = false,
  children,
}: {
  icon: ReactNode;
  label: string;
  maxHeight?: number;
  live?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(live);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Force-open (and keep open) while live; user can still collapse manually once it settles.
  useEffect(() => {
    if (live) setOpen(true);
  }, [live]);

  useEffect(() => {
    if (live && open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [live, open, children]);

  return (
    <Box sx={{ mb: 1 }}>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((o) => !o)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          border: 'none',
          borderRadius: 0,
          bgcolor: 'transparent',
          color: 'text.secondary',
          fontFamily: 'inherit',
          fontSize: '0.75rem',
          fontWeight: 500,
          px: 0,
          py: 0.5,
          cursor: 'pointer',
          transition: 'color 0.15s',
          '&:hover': { color: 'text.primary' },
        }}
      >
        {icon}
        {label}
        {live && (
          <Box
            sx={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              bgcolor: 'primary.light',
              animation: 'ds-reasoning-pulse 1.2s ease-in-out infinite',
              '@keyframes ds-reasoning-pulse': {
                '0%, 100%': { opacity: 0.3 },
                '50%': { opacity: 1 },
              },
            }}
          />
        )}
        <CaretDown size={12} style={{ transition: 'transform 0.2s', transform: open ? 'rotate(180deg)' : 'none' }} />
      </Box>
      <Collapse in={open}>
        <Box
          ref={bodyRef}
          sx={{
            mt: 1,
            p: 1.5,
            borderRadius: 2,
            bgcolor: 'var(--bt-overlay-faint)',
            border: '1px solid var(--bt-overlay-faint)',
            fontSize: '0.8125rem',
            color: 'text.secondary',
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            maxHeight,
            overflowY: 'auto',
            // Keep the scroll contained to this box (Kimi/Claude-style panel), not the page.
            overscrollBehavior: 'contain',
          }}
        >
          {children}
        </Box>
      </Collapse>
    </Box>
  );
}

export function ReasoningTrace({ reasoning, live }: Props) {
  if (!reasoning) return null;
  const words = reasoning ? wordCount(reasoning) : 0;
  return (
    <Box sx={{ mb: reasoning ? 1.5 : 0 }}>
      {reasoning && (
        <CollapsibleSection
          icon={<Brain size={14} />}
          label={live ? 'Размышляет...' : `Размышления (~${words} слов)`}
          live={live}
        >
          {reasoning}
        </CollapsibleSection>
      )}
    </Box>
  );
}
