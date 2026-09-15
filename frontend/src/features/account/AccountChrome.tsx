import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { motion, useReducedMotion } from 'framer-motion';
import { CHAT_COL } from '@/features/chat/chatColumn';

export const accountPanelSx = {
  p: { xs: 2, sm: 2.25 },
  borderRadius: '16px',
  bgcolor: 'var(--bt-panel)',
  border: '1px solid var(--bt-hairline)',
} as const;

export function AccountPageShell({
  title,
  lede,
  children,
}: {
  title: string;
  lede?: string;
  children: ReactNode;
}) {
  const reduce = useReducedMotion();
  return (
    <Box sx={{ pt: { xs: 9, md: 10 }, pb: { xs: 10, md: 8 } }}>
      <Box sx={{ ...CHAT_COL, maxWidth: 720 }}>
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
        >
          <Typography
            component="h1"
            sx={{
              mb: lede ? 0.75 : 3,
              fontSize: { xs: '1.5rem', md: '1.75rem' },
              fontWeight: 600,
              letterSpacing: '-0.03em',
              lineHeight: 1.2,
              textWrap: 'balance',
            }}
          >
            {title}
          </Typography>
          {lede ? (
            <Typography
              sx={{
                color: 'text.secondary',
                mb: 3,
                maxWidth: '42ch',
                fontSize: '0.9375rem',
                lineHeight: 1.5,
              }}
            >
              {lede}
            </Typography>
          ) : null}
        </motion.div>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>{children}</Box>
      </Box>
    </Box>
  );
}

export function AccountSection({
  title,
  hint,
  action,
  children,
  featured = false,
}: {
  title?: string;
  hint?: string;
  action?: ReactNode;
  children?: ReactNode;
  featured?: boolean;
}) {
  return (
    <Box
      sx={{
        ...accountPanelSx,
        ...(featured && {
          borderColor: 'var(--bt-line)',
          bgcolor: 'var(--bt-panel)',
          backgroundImage: 'linear-gradient(180deg, var(--bt-glow) 0%, transparent 64%)',
        }),
      }}
    >
      {(title || action) && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 1.5,
            mb: children ? 2 : 0,
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            {title ? (
              <Typography sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em' }}>
                {title}
              </Typography>
            ) : null}
            {hint ? (
              <Typography sx={{ color: 'text.secondary', mt: 0.4, fontSize: '0.8125rem', lineHeight: 1.45, maxWidth: '48ch' }}>
                {hint}
              </Typography>
            ) : null}
          </Box>
          {action}
        </Box>
      )}
      {children}
    </Box>
  );
}
