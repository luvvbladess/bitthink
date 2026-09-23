import { useState } from 'react';
import { Box, IconButton, SwipeableDrawer } from '@mui/material';
import { ArrowSquareOut, CaretDown, MagnifyingGlass, X } from '@phosphor-icons/react';
import { floatingPanelSx } from '@/theme/effects';
import type { ParsedSource } from './sources';
import { sourcesLabel } from './sources';

function Favicon({ domain, src }: { domain: string; src: string }) {
  const [failed, setFailed] = useState(false);
  const letter = (domain || '?').slice(0, 1).toUpperCase();
  if (!src || failed) {
    return (
      <Box
        aria-hidden
        sx={{
          width: 20,
          height: 20,
          borderRadius: '6px',
          flexShrink: 0,
          display: 'grid',
          placeItems: 'center',
          bgcolor: 'var(--bt-glow)',
          color: 'primary.light',
          fontSize: '0.6875rem',
          fontWeight: 700,
        }}
      >
        {letter}
      </Box>
    );
  }
  return (
    <Box
      component="img"
      src={src}
      alt=""
      onError={() => setFailed(true)}
      sx={{ width: 20, height: 20, borderRadius: '5px', flexShrink: 0, bgcolor: 'var(--bt-overlay-faint)' }}
    />
  );
}

function SourceCard({ source, compact }: { source: ParsedSource; compact?: boolean }) {
  const inner = (
    <>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
        <Favicon domain={source.domain} src={source.favicon} />
        <Box sx={{ minWidth: 0, color: 'text.muted', fontSize: '0.6875rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {source.domain}
        </Box>
        {source.url && !compact && <ArrowSquareOut size={13} style={{ marginLeft: 'auto', flexShrink: 0, opacity: 0.55 }} />}
      </Box>
      <Box
        sx={{
          mt: 0.65,
          fontSize: compact ? '0.8125rem' : '0.875rem',
          fontWeight: 600,
          lineHeight: 1.35,
          letterSpacing: '-0.02em',
          display: '-webkit-box',
          WebkitLineClamp: compact ? 2 : 3,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {source.title}
      </Box>
      {source.snippet && !compact && (
        <Box sx={{ mt: 0.5, color: 'text.secondary', fontSize: '0.75rem', lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {source.snippet}
        </Box>
      )}
    </>
  );

  return (
    <Box
      component={source.url ? 'a' : 'div'}
      href={source.url || undefined}
      target={source.url ? '_blank' : undefined}
      rel={source.url ? 'noreferrer' : undefined}
      aria-label={source.title}
      sx={{
        display: 'block',
        minWidth: 0,
        p: compact ? 1.15 : 1.35,
        borderRadius: '14px',
        bgcolor: 'var(--bt-overlay-faint)',
        border: '1px solid var(--bt-overlay)',
        color: 'text.primary',
        textDecoration: 'none',
        boxSizing: 'border-box',
        transition: 'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
        '&:hover': {
          bgcolor: 'var(--bt-glow)',
          borderColor: 'var(--bt-line)',
          boxShadow: '0 0 18px var(--bt-glow-strong)',
        },
        '&:active': { transform: 'scale(0.99)' },
      }}
    >
      {inner}
    </Box>
  );
}

export function SourcesCountButton({ count, onClick, active }: { count: number; onClick: () => void; active?: boolean }) {
  if (count <= 0) return null;
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      aria-label={sourcesLabel(count)}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.6,
        minHeight: 44,
        px: 1.15,
        mr: 0.25,
        border: 0,
        borderRadius: '999px',
        bgcolor: active ? 'var(--bt-glow)' : 'var(--bt-overlay-faint)',
        color: active ? 'primary.light' : 'text.secondary',
        boxShadow: active ? '0 0 16px var(--bt-glow-strong)' : 'none',
        font: 'inherit',
        fontSize: '0.75rem',
        fontWeight: 600,
        cursor: 'pointer',
        '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-glow)' },
      }}
    >
      <MagnifyingGlass size={14} />
      {sourcesLabel(count)}
    </Box>
  );
}

export function SourcesRail({
  sources,
  scoped,
  allCount,
  onShowAll,
}: {
  sources: ParsedSource[];
  scoped?: boolean;
  allCount?: number;
  onShowAll?: () => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <Box
      sx={{
        ...floatingPanelSx,
        display: 'flex',
        width: '100%',
        height: 'fit-content',
        maxHeight: 'min(24rem, calc(100vh - 14rem))',
        flexDirection: 'column',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', minHeight: 48, flexShrink: 0, pr: 0.5 }}>
        <Box
          component="button"
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={open ? 'Свернуть источники' : 'Развернуть источники'}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.75,
            minHeight: 48,
            minWidth: 0,
            flex: 1,
            px: 1.25,
            pl: 1.6,
            border: 0,
            bgcolor: 'transparent',
            color: 'inherit',
            font: 'inherit',
            cursor: 'pointer',
          }}
        >
          <Box sx={{ fontSize: '0.875rem', fontWeight: 600, letterSpacing: '-0.02em', whiteSpace: 'nowrap' }}>
            {scoped ? 'Ответ' : 'Источники'}
          </Box>
          <Box sx={{ color: 'primary.light', fontWeight: 600, fontSize: '0.8125rem' }}>{sources.length}</Box>
          <Box
            component="span"
            sx={{
              ml: 'auto',
              display: 'inline-flex',
              transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
              transition: 'transform 0.16s ease',
              '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
            }}
          >
            <CaretDown size={16} />
          </Box>
        </Box>
        {scoped && onShowAll && (allCount || 0) > sources.length && (
          <Box
            component="button"
            type="button"
            onClick={onShowAll}
            aria-label={`Показать все источники диалога, ${allCount}`}
            sx={{
              flexShrink: 0,
              minHeight: 44,
              px: 1.1,
              border: 0,
              borderRadius: '999px',
              bgcolor: 'var(--bt-glow)',
              color: 'primary.light',
              font: 'inherit',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              '&:hover': { bgcolor: 'var(--bt-glow-strong)' },
            }}
          >
            Все {allCount}
          </Box>
        )}
      </Box>
      {open && (
        <Box
          sx={{
            maxHeight: 'min(18.5rem, calc(100vh - 17.5rem))',
            overflowY: 'auto',
            overscrollBehavior: 'contain',
            px: 1.25,
            pb: 1.25,
            display: 'flex',
            flexDirection: 'column',
            gap: 0.75,
            scrollbarWidth: 'thin',
            scrollbarColor: 'var(--bt-line) transparent',
            '&::-webkit-scrollbar': { width: 6 },
            '&::-webkit-scrollbar-track': { background: 'transparent' },
            '&::-webkit-scrollbar-thumb': { bgcolor: 'var(--bt-line)', borderRadius: 99 },
            '&::-webkit-scrollbar-button': { display: 'none', width: 0, height: 0 },
          }}
        >
          {sources.map((source) => (
            <SourceCard key={`${source.url}-${source.title}`} source={source} compact />
          ))}
        </Box>
      )}
    </Box>
  );
}

export function SourcesSheet({
  sources,
  open,
  onClose,
  onOpen,
  scoped,
  allCount,
  onShowAll,
}: {
  sources: ParsedSource[];
  open: boolean;
  onClose: () => void;
  onOpen: () => void;
  scoped?: boolean;
  allCount?: number;
  onShowAll?: () => void;
}) {
  return (
    <SwipeableDrawer
      anchor="bottom"
      open={open}
      onClose={onClose}
      onOpen={onOpen}
      disableDiscovery
      PaperProps={{
        sx: {
          height: 'min(78vh, 640px)',
          borderTopLeftRadius: '18px',
          borderTopRightRadius: '18px',
          bgcolor: 'var(--bt-paper)',
          backgroundImage: 'none',
          border: '1px solid var(--bt-overlay)',
        },
      }}
      BackdropProps={{ sx: { bgcolor: 'var(--bt-scrim)' } }}
    >
      <Box sx={{ width: 40, height: 4, borderRadius: 99, bgcolor: 'var(--bt-overlay-strong)', mx: 'auto', mt: 1.25, mb: 0.5 }} />
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, minHeight: 48, gap: 0.75 }}>
        <Box sx={{ fontWeight: 600, fontSize: '1rem', letterSpacing: '-0.02em' }}>{scoped ? 'Этот ответ' : 'Источники'}</Box>
        <Box sx={{ color: 'text.muted', fontSize: '0.875rem' }}>{sources.length}</Box>
        {scoped && onShowAll && (allCount || 0) > sources.length && (
          <Box
            component="button"
            type="button"
            onClick={onShowAll}
            aria-label={`Показать все источники диалога, ${allCount}`}
            sx={{
              minHeight: 44,
              px: 1.15,
              border: 0,
              borderRadius: '999px',
              bgcolor: 'var(--bt-glow)',
              color: 'primary.light',
              font: 'inherit',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Все {allCount}
          </Box>
        )}
        <IconButton onClick={onClose} aria-label="Закрыть источники" sx={{ ml: 'auto', width: 44, height: 44, color: 'text.secondary' }}>
          <X size={18} />
        </IconButton>
      </Box>
      <Box sx={{ px: 1.5, pb: 'max(16px, env(safe-area-inset-bottom))', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0.85 }}>
        {sources.map((source) => (
          <SourceCard key={`${source.url}-${source.title}`} source={source} />
        ))}
      </Box>
    </SwipeableDrawer>
  );
}
