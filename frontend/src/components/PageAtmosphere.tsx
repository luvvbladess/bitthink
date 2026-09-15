import { Box } from '@mui/material';

/** Fixed ambient cyan wash + grain. Sits behind the product so the composer can glow on top. */
export function PageAtmosphere() {
  return (
    <>
      <Box
        aria-hidden
        sx={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          pointerEvents: 'none',
          background: `
            radial-gradient(ellipse 80% 55% at 50% -10%, var(--bt-wash-1), transparent 58%),
            radial-gradient(ellipse 45% 35% at 92% 88%, var(--bt-wash-2), transparent 55%),
            radial-gradient(ellipse 30% 24% at 8% 70%, var(--bt-wash-3), transparent 50%)
          `,
        }}
      />
      <Box
        aria-hidden
        sx={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          pointerEvents: 'none',
          opacity: 'var(--bt-grain)',
          mixBlendMode: 'multiply',
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
          '[data-theme="dark"] &': { mixBlendMode: 'overlay' },
        }}
      />
    </>
  );
}
