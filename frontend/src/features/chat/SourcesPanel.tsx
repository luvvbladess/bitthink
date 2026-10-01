import { useMemo, useState } from 'react';
import { Box, IconButton, SwipeableDrawer } from '@mui/material';
import { ArrowSquareOut, CaretDown, MagnifyingGlass, X } from '@phosphor-icons/react';
import type { ParsedSource } from './sources';
import { groupSourcesByDomain, sitesLabel, sourcesLabel, sourceTitle, type SourceGroup } from './sources';

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

const GROUP_PREVIEW = 3;

function SourceGroupBlock({ group }: { group: SourceGroup }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? group.items : group.items.slice(0, GROUP_PREVIEW);
  const hidden = group.items.length - visible.length;
  return (
    <Box component="section" aria-label={group.domain} sx={{ py: 0.75 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.9, px: 1.5, minHeight: 28 }}>
        <Favicon domain={group.domain} src={group.favicon} />
        <Box sx={{ minWidth: 0, flex: 1, color: 'text.secondary', fontSize: '0.75rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {group.domain}
        </Box>
        {group.items.length > 1 && (
          <Box component="span" sx={{ color: 'text.muted', fontSize: '0.75rem', fontVariantNumeric: 'tabular-nums' }}>
            {group.items.length}
          </Box>
        )}
      </Box>
      {visible.map((source) => (
        <Box
          key={`${source.url}-${source.title}`}
          component={source.url ? 'a' : 'div'}
          href={source.url || undefined}
          target={source.url ? '_blank' : undefined}
          rel={source.url ? 'noreferrer' : undefined}
          title={source.title}
          sx={{
            display: 'block',
            mx: 0.75,
            py: 0.6,
            pl: 4.1,
            pr: 0.75,
            borderRadius: '8px',
            color: 'text.primary',
            textDecoration: 'none',
            fontSize: '0.8125rem',
            lineHeight: 1.4,
            transition: 'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
            '&:hover': { bgcolor: 'var(--bt-overlay-faint)' },
            '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
          }}
        >
          {/* The clamp lives on the inner span: on a padded box the hidden third line peeks through the padding. */}
          <Box component="span" sx={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
            {sourceTitle(source)}
          </Box>
        </Box>
      ))}
      {group.items.length > GROUP_PREVIEW && (
        <Box
          component="button"
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          sx={{
            display: 'block',
            mx: 0.75,
            py: 0.5,
            pl: 4.1,
            border: 0,
            bgcolor: 'transparent',
            color: 'text.muted',
            font: 'inherit',
            fontSize: '0.75rem',
            fontWeight: 600,
            cursor: 'pointer',
            textAlign: 'left',
            '&:hover': { color: 'primary.light' },
            '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2, borderRadius: '6px' },
          }}
        >
          {expanded ? 'Свернуть' : `Ещё ${hidden}`}
        </Box>
      )}
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
  const groups = useMemo(() => groupSourcesByDomain(sources), [sources]);
  return (
    <Box
      sx={{
        display: 'flex',
        width: '100%',
        height: 'fit-content',
        // The column starts under the action buttons and may use the rest of the screen.
        maxHeight: 'calc(100dvh - 96px)',
        flexDirection: 'column',
        overflow: 'hidden',
        borderRadius: '16px',
        bgcolor: 'var(--bt-panel)',
        border: '1px solid var(--bt-hairline)',
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
            gap: 0.9,
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
            textAlign: 'left',
            '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2, borderRadius: '14px' },
          }}
        >
          <Box component="span" sx={{ fontSize: '0.875rem', fontWeight: 600, letterSpacing: '-0.02em', whiteSpace: 'nowrap' }}>
            {scoped ? 'Этот ответ' : 'Источники'}
          </Box>
          <Box component="span" sx={{ color: 'text.muted', fontSize: '0.8125rem', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
            {groups.length > 1 && groups.length < sources.length ? `${sources.length} · ${sitesLabel(groups.length)}` : sources.length}
          </Box>
          <Box
            component="span"
            sx={{
              ml: 'auto',
              display: 'inline-flex',
              color: 'text.secondary',
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
              minHeight: 32,
              px: 1.1,
              border: '1px solid var(--bt-hairline)',
              borderRadius: '999px',
              bgcolor: 'transparent',
              color: 'text.secondary',
              font: 'inherit',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay-faint)' },
              '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 },
            }}
          >
            Все {allCount}
          </Box>
        )}
      </Box>
      {open && (
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            overscrollBehavior: 'contain',
            borderTop: '1px solid var(--bt-hairline)',
            pb: 0.75,
            scrollbarWidth: 'thin',
            scrollbarColor: 'var(--bt-line) transparent',
            '&::-webkit-scrollbar': { width: 6 },
            '&::-webkit-scrollbar-track': { background: 'transparent' },
            '&::-webkit-scrollbar-thumb': { bgcolor: 'var(--bt-line)', borderRadius: 99 },
            '&::-webkit-scrollbar-button': { display: 'none', width: 0, height: 0 },
          }}
        >
          {groups.map((group) => (
            <SourceGroupBlock key={group.domain} group={group} />
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
