import { Box, keyframes } from '@mui/material';
import { motion } from 'framer-motion';

const bounce = keyframes`
  0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
  40% { transform: translateY(-4px); opacity: 1; }
`;

interface Props {
  statusText?: string;
}

export function ThinkingIndicator({ statusText }: Props) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        {[0, 1, 2].map((i) => (
          <Box
            key={i}
            sx={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              backgroundColor: 'primary.light',
              animation: `${bounce} 1.2s ease-in-out infinite`,
              animationDelay: `${i * 0.15}s`,
            }}
          />
        ))}
      </Box>
      <motion.div
        initial={{ opacity: 0, x: -8 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.3 }}
        style={{ fontSize: '0.875rem', color: 'var(--bt-ink-2)' }}
      >
        {statusText || 'Думаю над ответом...'}
      </motion.div>
    </Box>
  );
}
