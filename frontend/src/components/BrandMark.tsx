import { Box } from '@mui/material';
import { Link } from 'react-router-dom';
import { BRAND_FONT, BRAND_NAME, BRAND_WORDMARK } from '@/brand';
import { useAuthStore } from '@/stores/authStore';

const MARK_PATH =
  'M126.84 45.8611C136.317 45.8611 144 53.5282 144 62.9861V123.875C144 133.333 136.317 141 126.84 141H62.9667C53.4895 141 45.8067 133.333 45.8067 123.875V99.1389H82.0333C91.5105 99.1389 99.1933 91.4718 99.1933 82.0139V45.8611H126.84ZM82.0333 4C91.5105 4 99.1933 11.6671 99.1933 21.125V45.8611H62.9667C53.4895 45.8611 45.8067 53.5282 45.8067 62.9861V99.1389H18.16C8.6828 99.1389 1 91.4718 1 82.0139V21.125C1 11.6671 8.68279 4 18.16 4H82.0333Z';

export type BrandVariant = 'nav' | 'sidebar' | 'footer' | 'hero' | 'empty';

const VARIANT: Record<
  BrandVariant,
  { icon: number; word: number; gap: number; weight: 400 | 500 }
> = {
  nav: { icon: 28, word: 18, gap: 10, weight: 500 },
  sidebar: { icon: 28, word: 18, gap: 10, weight: 500 },
  footer: { icon: 22, word: 15, gap: 8, weight: 500 },
  hero: { icon: 52, word: 34, gap: 16, weight: 400 },
  empty: { icon: 36, word: 22, gap: 12, weight: 400 },
};

interface MarkProps {
  variant?: BrandVariant;
}

export function BrandIcon({ size = 28 }: { size?: number }) {
  return (
    <Box
      component="svg"
      viewBox="0 0 144 144"
      width={size}
      height={size}
      aria-hidden
      sx={{ display: 'block', flexShrink: 0 }}
    >
      <path d={MARK_PATH} fill="#21A0CE" />
    </Box>
  );
}

export function BrandMark({ variant = 'nav' }: MarkProps) {
  const { icon, word, gap, weight } = VARIANT[variant];
  const isHero = variant === 'hero';

  return (
    <Box
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: `${gap}px`,
        lineHeight: 0,
        color: 'text.primary',
      }}
    >
      <BrandIcon size={icon} />
      <Box
        component="span"
        sx={{
          fontFamily: BRAND_FONT,
          fontWeight: weight,
          fontSize: isHero ? { xs: 28, sm: 34 } : word,
          letterSpacing: isHero ? '-0.02em' : '-0.015em',
          lineHeight: 1,
          whiteSpace: 'nowrap',
          userSelect: 'none',
        }}
      >
        {BRAND_WORDMARK}
      </Box>
    </Box>
  );
}

export function BrandLink({ variant = 'nav' }: { variant?: BrandVariant }) {
  const token = useAuthStore((s) => s.accessToken);
  return (
    <Box
      component={Link}
      to={token ? '/chat?new=1' : '/'}
      aria-label={BRAND_NAME}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        minHeight: 44,
        textDecoration: 'none',
        color: 'inherit',
        lineHeight: 0,
        borderRadius: '8px',
        opacity: 1,
        transition: 'opacity 0.18s cubic-bezier(0.23, 1, 0.32, 1)',
        '&:hover': { opacity: 0.86 },
      }}
    >
      <BrandMark variant={variant} />
    </Box>
  );
}
