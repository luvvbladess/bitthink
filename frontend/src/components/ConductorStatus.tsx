import { Box, Stack, Typography, keyframes } from '@mui/material';
import { Check, Clock, Spinner, X, Desktop } from '@phosphor-icons/react';

interface Round {
  number: number;
  status: 'completed' | 'active' | 'pending' | 'error';
  title: string;
  model?: string;
}

interface Props {
  statusText: string;
}

const pulse = keyframes`
  0% { opacity: 0.6; }
  50% { opacity: 1; }
  100% { opacity: 0.6; }
`;

function computerBody(text: string): string | null {
  const trimmed = text.trim();
  for (const prefix of ['Пилот:', 'Computer:', 'Дирижёр:']) {
    const idx = trimmed.indexOf(prefix);
    if (idx !== -1) return trimmed.slice(idx + prefix.length).trim();
  }
  return null;
}

function parseRounds(text: string): Round[] | null {
  const body = computerBody(text);
  if (body == null) return null;

  const regex = /Раунд\s+(\d+):\s*([\s\S]*?)(?=Раунд\s+\d+:|$)/gi;
  const matches = [...body.matchAll(regex)];
  if (matches.length === 0) return [];

  return matches.map((m) => {
    const number = parseInt(m[1], 10);
    const raw = m[2].trim();

    const separatorIndex = raw.lastIndexOf(' — ');
    let title = raw;
    let model: string | undefined;
    if (separatorIndex !== -1) {
      title = raw.slice(0, separatorIndex).trim();
      model = raw.slice(separatorIndex + 3).trim();
    }

    let status: Round['status'] = 'pending';
    const firstChar = title.charAt(0);
    if (['✅', '✔', '☑'].includes(firstChar)) {
      status = 'completed';
      title = title.slice(1).trim();
    } else if (['⏳', '⏸', '🔲', '⚪'].includes(firstChar)) {
      status = 'pending';
      title = title.slice(1).trim();
    } else if (['🔄', '▶', '▶️', '⏵', '⚡'].includes(firstChar)) {
      status = 'active';
      title = title.slice(1).trim();
    } else if (['❌', '⛔', '❗'].includes(firstChar)) {
      status = 'error';
      title = title.slice(1).trim();
    }

    return { number, status, title, model };
  });
}

const statusConfig = {
  completed: {
    icon: Check,
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.12)',
    label: 'готов',
  },
  active: {
    icon: Spinner,
    color: 'primary.main',
    bg: 'var(--bt-glow)',
    label: 'в работе',
  },
  pending: {
    icon: Clock,
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.12)',
    label: 'ожидает',
  },
  error: {
    icon: X,
    color: '#ef4444',
    bg: 'var(--bt-danger-soft)',
    label: 'ошибка',
  },
};

export function isComputerStatus(text: string): boolean {
  return /Пилот:|Computer:|Дирижёр:/.test(text);
}

export function ConductorStatus({ statusText }: Props) {
  if (!isComputerStatus(statusText)) return null;
  const rounds = parseRounds(statusText) || [];
  const headline = computerBody(statusText) || statusText;

  return (
    <Box
      sx={{
        width: '100%',
        maxWidth: 640,
        bgcolor: 'var(--bt-overlay-faint)',
        border: '1px solid var(--bt-overlay)',
        borderRadius: 1,
        p: 1.5,
      }}
    >
      <Stack spacing={1}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, color: 'text.secondary' }}>
          <Desktop size={18} color="currentColor" />
          <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary' }}>
            Пилот
          </Typography>
        </Box>

        {rounds.length === 0 && (
          <Typography variant="body2" sx={{ color: 'text.secondary', lineHeight: 1.5 }}>
            {headline}
          </Typography>
        )}

        {rounds.map((round) => {
          const config = statusConfig[round.status];
          const Icon = config.icon;
          const isActive = round.status === 'active';

          return (
            <Box
              key={round.number}
              sx={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1.25,
                p: 1,
                borderRadius: 1.5,
                bgcolor: isActive ? config.bg : 'transparent',
                transition: 'background-color 0.2s',
              }}
            >
              <Box
                sx={{
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  mt: 0.125,
                  bgcolor: config.bg,
                  color: config.color,
                  animation: isActive ? `${pulse} 1.5s ease-in-out infinite` : 'none',
                }}
              >
                <Icon size={13} weight="bold" />
              </Box>

              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }}>
                    Раунд {round.number}
                  </Typography>
                  <Typography variant="caption" sx={{ color: config.color, fontWeight: 500 }}>
                    {config.label}
                  </Typography>
                </Box>
                <Typography
                  variant="body2"
                  sx={{ color: 'text.secondary', lineHeight: 1.5, mt: 0.25 }}
                >
                  {round.title}
                </Typography>
                {round.model && (
                  <Typography variant="caption" sx={{ color: 'text.muted', display: 'block', mt: 0.5 }}>
                    {round.model}
                  </Typography>
                )}
              </Box>
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}
