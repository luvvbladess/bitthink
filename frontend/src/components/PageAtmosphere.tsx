import { Box } from '@mui/material';
import { useLocation } from 'react-router-dom';

// The product itself (chat, settings, billing, admin) is a flat canvas: depth comes from tone and
// hairlines, like the assistants people compare it to. Only the public pages get one soft light.
const PUBLIC_PATHS = new Set(['/', '/login', '/register', '/privacy']);

export function PageAtmosphere() {
  const { pathname } = useLocation();
  if (!PUBLIC_PATHS.has(pathname)) return null;
  return (
    <Box
      aria-hidden
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        background: 'radial-gradient(ellipse 70% 42% at 50% -8%, var(--bt-wash-1), transparent 62%)',
      }}
    />
  );
}
