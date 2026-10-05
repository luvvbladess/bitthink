import { useMemo, useState } from 'react';
import { Box, IconButton, SwipeableDrawer } from '@mui/material';
import { ArrowSquareOut, MagnifyingGlass, X } from '@phosphor-icons/react';
import type { ParsedSource } from './sources';
import { groupSourcesByDomain, sourcesLabel, sourceTitle, type SourceGroup } from './sources';

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

export function SourcesSheet({
  sources,
  open,
  onClose,
  onOpen,
  scoped,
  allCount,
  onShowAll,
  side = false,
}: {
  sources: ParsedSource[];
  open: boolean;
  onClose: () => void;
  onOpen: () => void;
  scoped?: boolean;
  allCount?: number;
  onShowAll?: () => void;
  /** Wide screens: a panel on the right, grouped by site. Phones: a bottom sheet of cards. */
  side?: boolean;
}) {
  const groups = useMemo(() => groupSourcesByDomain(sources), [sources]);
  return (
    <SwipeableDrawer
      anchor={side ? 'right' : 'bottom'}
      open={open}
      onClose={onClose}
      onOpen={onOpen}
      disableDiscovery
      disableSwipeToOpen
      PaperProps={{
        sx: side
          ? {
              width: 380,
              maxWidth: '100vw',
              bgcolor: 'var(--bt-paper)',
              backgroundImage: 'none',
              borderLeft: '1px solid var(--bt-hairline)',
              boxShadow: 'var(--bt-shadow-menu)',
            }
          : {
              height: 'min(78vh, 640px)',
              borderTopLeftRadius: '18px',
              borderTopRightRadius: '18px',
              bgcolor: 'var(--bt-paper)',
              backgroundImage: 'none',
              border: '1px solid var(--bt-overlay)',
            },
      }}
      // The page behind a side panel stays readable and clickable-through to close, not dimmed.
      BackdropProps={{ sx: side ? { bgcolor: 'transparent' } : { bgcolor: 'var(--bt-scrim)' } }}
    >
      {!side && <Box sx={{ width: 40, height: 4, borderRadius: 99, bgcolor: 'var(--bt-overlay-strong)', mx: 'auto', mt: 1.25, mb: 0.5 }} />}
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
      {side ? (
        <Box sx={{ overflowY: 'auto', overscrollBehavior: 'contain', borderTop: '1px solid var(--bt-hairline)', pb: 1.5 }}>
          {groups.map((group) => (
            <SourceGroupBlock key={group.domain} group={group} />
          ))}
        </Box>
      ) : (
        <Box sx={{ px: 1.5, pb: 'max(16px, env(safe-area-inset-bottom))', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 0.85 }}>
          {sources.map((source) => (
            <SourceCard key={`${source.url}-${source.title}`} source={source} />
          ))}
        </Box>
      )}
    </SwipeableDrawer>
  );
}
