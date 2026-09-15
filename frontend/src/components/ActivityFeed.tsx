import { Box, keyframes } from '@mui/material';
import { useReducedMotion } from 'framer-motion';

type Kind = 'search' | 'browse' | 'mail' | 'ssh' | 'api' | 'chart' | 'think';

interface Step {
  kind: Kind;
  text: string;
}

const KINDS = new Set<Kind>(['search', 'browse', 'mail', 'ssh', 'api', 'chart', 'think']);

const pulse = keyframes`
  0%, 100% { opacity: 0.35; }
  50% { opacity: 1; }
`;

function inferKind(line: string): Kind {
  const t = line.toLowerCase();
  if (/ищу|поиск|search/.test(t)) return 'search';
  if (/открываю|читаю|сайт|http|\.\w{2,}/.test(t)) return 'browse';
  if (/почт|письм|gmail/.test(t)) return 'mail';
  if (/сервер|ssh|команд/.test(t)) return 'ssh';
  if (/\b(get|post|put|patch|delete)\b|api/.test(t)) return 'api';
  if (/график|chart/.test(t)) return 'chart';
  return 'think';
}

function capitalize(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return 'Думаю';
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

function humanize(kind: Kind, text: string): string {
  const raw = text.trim();
  if (kind === 'search') {
    if (/^ищу/i.test(raw)) return capitalize(raw);
    return `Ищу: ${raw}`;
  }
  if (kind === 'browse') {
    if (/^читаю|^открываю/i.test(raw)) return capitalize(raw);
    return `Читаю ${raw}`;
  }
  if (kind === 'mail' || kind === 'ssh' || kind === 'think') return capitalize(raw);
  if (kind === 'api') return raw ? `Запрос ${raw}` : 'Запрос';
  if (kind === 'chart') return /^строю/i.test(raw) ? capitalize(raw) : 'Строю график';
  return capitalize(raw);
}

export function latestActivityLabel(statusText?: string): string {
  const steps = parseActivitySteps(statusText || '');
  const last = steps[steps.length - 1];
  if (!last) return 'Собираю макет';
  return humanize(last.kind, last.text);
}

export function parseActivitySteps(statusText: string): Step[] {
  const lines = (statusText || '')
    .split('\n')
    .map((line) => line.replace(/^(Computer|Пилот|Дирижёр):\s*/i, '').trim())
    .filter(Boolean);
  const steps: Step[] = [];
  for (const line of lines) {
    const chunks = line.split(/(?=\[\w+\])/).map((item) => item.trim()).filter(Boolean);
    const pieces = chunks.length ? chunks : [line];
    for (const piece of pieces) {
      const tagged = piece.match(/^\[([a-z]+)\]\s*(.*)$/i);
      if (tagged) {
        const kind = tagged[1].toLowerCase() as Kind;
        const text = tagged[2].trim();
        if (!text) continue;
        steps.push({ kind: KINDS.has(kind) ? kind : inferKind(text), text });
        continue;
      }
      if (/^Раунд\s+\d+/i.test(piece) || piece === 'Computer' || piece === 'Пилот') continue;
      steps.push({ kind: inferKind(piece), text: piece.replace(/^[✅❌⏳🔄▶⚡]\s*/, '') });
    }
  }
  return steps.slice(-12);
}

export function ActivityFeed({ statusText }: { statusText?: string }) {
  const reduce = useReducedMotion();
  const steps = parseActivitySteps(statusText || '');
  const items = (steps.length ? steps : [{ kind: 'think' as const, text: statusText || 'Думаю' }]).map((step) => ({
    ...step,
    label: humanize(step.kind, step.text),
  }));
  const last = items.length - 1;
  const simple = items.length === 1;

  return (
    <Box
      role="status"
      aria-live="polite"
      sx={{
        width: '100%',
        maxWidth: 560,
        py: 0.25,
      }}
    >
      {items.map((step, index) => {
        const active = index === last;
        return (
          <Box
            key={`${index}-${step.kind}-${step.label}`}
            sx={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 1,
              py: simple ? 0.5 : 0.45,
              color: active ? 'text.secondary' : 'text.muted',
              fontSize: '0.875rem',
              lineHeight: 1.45,
              fontStyle: active ? 'italic' : 'normal',
            }}
          >
            <Box
              sx={{
                width: active ? 7 : 6,
                height: active ? 7 : 6,
                borderRadius: '50%',
                bgcolor: active ? 'primary.main' : 'var(--bt-overlay-strong)',
                flexShrink: 0,
                mt: '0.45em',
                animation: active && !reduce ? `${pulse} 1.4s ease-in-out infinite` : 'none',
                '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
              }}
            />
            <Box component="span" sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
              {step.label}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
