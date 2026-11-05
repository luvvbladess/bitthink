import { useState, type ReactNode } from 'react';
import { Box } from '@mui/material';
import { ArrowUpRight, Check, CheckCircle, CheckSquare, Info, Lightbulb, Square, WarningCircle } from '@phosphor-icons/react';
import { parseAnswerCard } from './richAnswerData';

const CALLOUTS = {
  note: { icon: Info, label: 'Обратите внимание', color: 'var(--bt-answer-info)', background: 'var(--bt-answer-info-bg)' },
  tip: { icon: Lightbulb, label: 'Полезный совет', color: 'var(--bt-answer-info)', background: 'var(--bt-answer-info-bg)' },
  success: { icon: CheckCircle, label: 'Готово', color: 'var(--bt-success)', background: 'var(--bt-answer-success-bg)' },
  warning: { icon: WarningCircle, label: 'Важно учесть', color: 'var(--bt-answer-warning)', background: 'var(--bt-answer-warning-bg)' },
  caution: { icon: WarningCircle, label: 'Осторожно', color: 'var(--bt-danger)', background: 'var(--bt-danger-soft)' },
  important: { icon: Info, label: 'Важно', color: 'var(--bt-answer-info)', background: 'var(--bt-answer-info-bg)' },
};

export function AnswerCallout({ children, node }: { children?: ReactNode; node?: { properties?: Record<string, unknown> } }) {
  const kind = node?.properties?.['data-callout'] as keyof typeof CALLOUTS;
  const style = CALLOUTS[kind];
  if (!style) return <blockquote>{children}</blockquote>;
  const Icon = style.icon;
  const title = String(node?.properties?.['data-callout-title'] || style.label);
  return <Box component="aside" data-answer-callout={kind} aria-label={title} sx={{ my: 2, p: { xs: 1.75, sm: 2 }, borderRadius: '12px', bgcolor: style.background, minWidth: 0 }}>
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: .75, color: style.color, fontSize: '.9375rem', fontWeight: 600, lineHeight: 1.5 }}><Icon size={20} style={{ flexShrink: 0, marginTop: 1 }} aria-hidden /><span>{title}</span></Box>
    <Box sx={{ color: 'var(--bt-ink)', fontSize: '.9375rem', '& > :first-child': { mt: 0 }, '& > :last-child': { mb: 0 }, '& p:empty': { display: 'none' } }}>{children}</Box>
  </Box>;
}

export function AnswerCard({ text }: { text: string }) {
  const card = parseAnswerCard(text);
  const [failedImage, setFailedImage] = useState(false);
  if (!card) return <Box component="details" sx={{ my: 2, color: 'text.secondary', fontSize: '.875rem' }}><summary>Карточка не отобразилась. Показать текст</summary><Box component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text}</Box></Box>;
  let domain = '';
  if (card.url) domain = new URL(card.url).hostname.replace(/^www\./, '');
  return <Box component="article" data-answer-card sx={{ display: 'flex', alignItems: 'flex-start', gap: { xs: 1.5, sm: 2 }, py: 2.25, minWidth: 0, borderBottom: '1px solid var(--bt-hairline)', '&:last-child': { borderBottom: 0 } }}>
    {card.image && !failedImage && <Box component="img" src={card.image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailedImage(true)} sx={{ width: { xs: 68, sm: 96 }, height: { xs: 68, sm: 96 }, borderRadius: '12px', objectFit: 'cover', flexShrink: 0, bgcolor: 'var(--bt-overlay-faint)' }} />}
    <Box sx={{ minWidth: 0, flex: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', columnGap: 1, rowGap: .5, mb: .75 }}>
        <Box component="h3" sx={{ m: '0 !important', fontSize: '1rem !important', fontWeight: 600, lineHeight: 1.4 }}>{card.title}</Box>
        {card.badge && <Box component="span" sx={{ display: 'inline-flex', gap: .5, alignItems: 'center', borderRadius: '999px', px: 1, py: .25, bgcolor: 'var(--bt-answer-success-bg)', color: 'var(--bt-success)', fontSize: '.75rem', fontWeight: 600, lineHeight: 1.5 }}><Check size={12} aria-hidden />{card.badge}</Box>}
      </Box>
      <Box sx={{ fontSize: '.9375rem', lineHeight: 1.65, whiteSpace: 'pre-line' }}>{card.description}</Box>
      {card.meta && <Box sx={{ mt: .75, fontSize: '.8125rem', lineHeight: 1.5, color: 'text.secondary' }}>{card.meta}</Box>}
      {card.url && <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1.25, mt: .5 }}>
        <Box component="a" href={card.url} target="_blank" rel="noopener noreferrer" sx={{ display: 'inline-flex', alignItems: 'center', gap: .5, minHeight: 44, fontSize: '.875rem', fontWeight: 500, textDecoration: 'underline', '&:focus-visible': { outline: '2px solid var(--bt-answer-info)', outlineOffset: 3, borderRadius: '4px' } }}>{card.linkLabel || 'Открыть сайт'}<ArrowUpRight size={14} aria-hidden /></Box>
        <Box component="span" sx={{ color: 'text.secondary', fontSize: '.75rem', overflowWrap: 'anywhere' }}>{domain}</Box>
      </Box>}
    </Box>
  </Box>;
}

export function AnswerCheckbox({ checked }: { checked?: boolean }) {
  const Icon = checked ? CheckSquare : Square;
  return <Box component="span" role="img" aria-label={checked ? 'Выполнено' : 'Не выполнено'} sx={{ display: 'inline-flex', verticalAlign: '-.22em', mr: .75, color: checked ? 'var(--bt-success)' : 'var(--bt-ink-muted)' }}><Icon size={19} weight={checked ? 'fill' : 'regular'} aria-hidden /></Box>;
}
