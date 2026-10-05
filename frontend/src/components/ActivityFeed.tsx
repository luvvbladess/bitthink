import { useEffect, useState } from 'react';
import { Box, keyframes } from '@mui/material';
import {
  ChartLineUp,
  Check,
  EnvelopeSimple,
  Globe,
  MagnifyingGlass,
  Plugs,
  Sparkle,
  TerminalWindow,
  type Icon,
} from '@phosphor-icons/react';

type Kind = 'search' | 'browse' | 'mail' | 'ssh' | 'api' | 'chart' | 'think';

interface Step {
  kind: Kind;
  text: string;
}

const KINDS = new Set<Kind>(['search', 'browse', 'mail', 'ssh', 'api', 'chart', 'think']);

const KIND_ICON: Record<Kind, Icon> = {
  search: MagnifyingGlass,
  browse: Globe,
  mail: EnvelopeSimple,
  ssh: TerminalWindow,
  api: Plugs,
  chart: ChartLineUp,
  think: Sparkle,
};

const EASE = 'cubic-bezier(0.23, 1, 0.32, 1)';
const NODE = 22;
const VISIBLE_STEPS = 5;
const CLOCK_AFTER_S = 4;

const spin = keyframes`
  to { transform: rotate(360deg); }
`;
const stepIn = keyframes`
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
`;
const settle = keyframes`
  from { opacity: 0.4; transform: scale(0.85); }
  to { opacity: 1; transform: none; }
`;

function inferKind(line: string): Kind {
  const t = line.toLowerCase();
  if (/^📄/.test(line.trim())) return 'think';
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
    .map((line) => line.replace(/^(Computer|Оркестратор|Пилот|Дирижёр):\s*/i, '').trim())
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
      if (/^Раунд\s+\d+/i.test(piece) || piece === 'Computer' || piece === 'Оркестратор' || piece === 'Пилот') continue;
      steps.push({ kind: inferKind(piece), text: piece.replace(/^[✅❌⏳🔄▶⚡]\s*/, '') });
    }
  }
  return steps.slice(-12);
}

interface Row {
  kind: Kind;
  title: string;
  /** The object of the action (query, site, command), shown quieter under the title. */
  detail?: string;
}

/** A short plain-language action plus, when there is one, what it is aimed at. */
function describe(step: Step): Row {
  const { kind } = step;
  const raw = step.text.trim();
  if (kind === 'search') {
    return /^ищу/i.test(raw) ? { kind, title: capitalize(raw) } : { kind, title: 'Поиск в интернете', detail: raw };
  }
  if (kind === 'browse') {
    return /^(читаю|открываю)/i.test(raw) ? { kind, title: capitalize(raw) } : { kind, title: 'Читаю страницу', detail: raw };
  }
  if (kind === 'ssh') {
    return /^команда на сервере$/i.test(raw) ? { kind, title: 'Команда на сервере' } : { kind, title: 'Команда на сервере', detail: raw };
  }
  if (kind === 'api') return { kind, title: 'Запрос к сервису', detail: raw || undefined };
  if (kind === 'chart') return { kind, title: /^строю/i.test(raw) ? capitalize(raw) : 'Строю график' };
  return { kind, title: capitalize(raw) };
}

function plural(n: number): string {
  const tail = n % 10;
  const teen = n % 100;
  if (tail === 1 && teen !== 11) return 'шаг';
  if (tail >= 2 && tail <= 4 && (teen < 10 || teen >= 20)) return 'шага';
  return 'шагов';
}

function clock(seconds: number): string {
  if (seconds < 60) return `${seconds} с`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Whole seconds since the feed appeared, i.e. since the reply started being worked on. */
function useElapsed(): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, []);
  return seconds;
}

/** In progress: a thin ring turning around the action's icon. */
function ActiveNode({ Glyph }: { Glyph: Icon }) {
  return (
    <Box
      aria-hidden
      sx={{ position: 'relative', width: NODE, height: NODE, color: 'primary.light', display: 'grid', placeItems: 'center' }}
    >
      <Box
        component="svg"
        viewBox="0 0 22 22"
        sx={{
          position: 'absolute',
          inset: 0,
          width: NODE,
          height: NODE,
          animation: `${spin} 0.9s linear infinite`,
          // No motion wanted: a static, closed ring still says "this one is current".
          '@media (prefers-reduced-motion: reduce)': { animation: 'none', '& .arc': { strokeDasharray: 'none' } },
        }}
      >
        <circle cx="11" cy="11" r="9.5" fill="none" stroke="var(--bt-overlay-strong)" strokeWidth="1.5" />
        <circle className="arc" cx="11" cy="11" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="16 44" />
      </Box>
      <Glyph size={11} weight="bold" />
    </Box>
  );
}

/** Finished: a quiet check, so the eye stays on the current action. */
function DoneNode() {
  return (
    <Box
      aria-hidden
      sx={{
        width: NODE,
        height: NODE,
        display: 'grid',
        placeItems: 'center',
        animation: `${settle} 0.18s ${EASE} both`,
      }}
    >
      <Box
        sx={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          display: 'grid',
          placeItems: 'center',
          bgcolor: 'var(--bt-overlay)',
          color: 'text.muted',
        }}
      >
        <Check size={9} weight="bold" />
      </Box>
    </Box>
  );
}

export function ActivityFeed({ statusText }: { statusText?: string }) {
  const elapsed = useElapsed();
  const steps = parseActivitySteps(statusText || '');
  const rows = (steps.length ? steps : [{ kind: 'think' as const, text: statusText || 'Думаю' }]).map(describe);
  const shown = rows.slice(-VISIBLE_STEPS);
  const earlier = rows.length - shown.length;
  const last = shown.length - 1;

  return (
    <Box role="status" aria-live="polite" sx={{ width: '100%', maxWidth: 560, py: 0.25 }}>
      {earlier > 0 && (
        <Box sx={{ pl: `${NODE + 12}px`, pb: 0.75, fontSize: '0.75rem', color: 'text.muted' }}>
          Ранее: {earlier} {plural(earlier)}
        </Box>
      )}
      {shown.map((row, index) => {
        const active = index === last;
        const Glyph = KIND_ICON[row.kind];
        return (
          <Box
            key={`${row.kind}|${row.title}|${row.detail || ''}`}
            sx={{
              position: 'relative',
              display: 'grid',
              gridTemplateColumns: `${NODE}px minmax(0, 1fr)`,
              columnGap: '12px',
              alignItems: 'start',
              pb: active ? 0 : 1.25,
              animation: `${stepIn} 0.22s ${EASE} both`,
              // The rail ties the steps together; it stops at the current one.
              '&:not(:last-of-type)::before': {
                content: '""',
                position: 'absolute',
                left: `${NODE / 2 - 0.5}px`,
                top: `${NODE + 3}px`,
                bottom: '3px',
                width: '1px',
                bgcolor: 'var(--bt-hairline)',
              },
            }}
          >
            {active ? <ActiveNode Glyph={Glyph} /> : <DoneNode />}
            <Box sx={{ minWidth: 0, pt: '1px' }}>
              <Box
                sx={{
                  fontSize: '0.875rem',
                  lineHeight: 1.5,
                  fontWeight: active ? 500 : 400,
                  color: active ? 'text.primary' : 'text.secondary',
                  overflowWrap: 'anywhere',
                  transition: `color 0.18s ${EASE}`,
                }}
              >
                {row.title}
                {active && elapsed >= CLOCK_AFTER_S && (
                  <Box
                    component="span"
                    aria-hidden
                    sx={{ ml: 1, fontSize: '0.75rem', fontWeight: 400, color: 'text.muted', fontVariantNumeric: 'tabular-nums' }}
                  >
                    {clock(elapsed)}
                  </Box>
                )}
              </Box>
              {row.detail && (
                <Box
                  sx={{
                    mt: '1px',
                    fontSize: '0.8125rem',
                    lineHeight: 1.45,
                    color: 'text.muted',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {row.detail}
                </Box>
              )}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
