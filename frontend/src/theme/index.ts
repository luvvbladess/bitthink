import { createTheme, type ThemeOptions } from '@mui/material/styles';
import '@fontsource-variable/inter';
import '@/fonts/stolzl.css';

const common: ThemeOptions = {
  typography: {
    fontFamily: '"Inter Variable", "Inter", system-ui, sans-serif',
    h1: { fontSize: '2.25rem', fontWeight: 600, letterSpacing: '-0.03em', lineHeight: 1.15 },
    h2: { fontSize: '1.75rem', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.2 },
    h3: { fontSize: '1.25rem', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.3 },
    body1: { fontSize: '1rem', lineHeight: 1.65 },
    body2: { fontSize: '0.9375rem', lineHeight: 1.6 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  shape: { borderRadius: 10 },
};

const motionReduce = {
  '@media (prefers-reduced-motion: reduce)': {
    '*, *::before, *::after': {
      animationDuration: '0.01ms !important',
      animationIterationCount: '1 !important',
      transitionDuration: '0.01ms !important',
      scrollBehavior: 'auto !important',
    },
  },
} as const;

declare module '@mui/material/styles' {
  interface Palette {
    surface: { main: string; elevated: string; glass: string };
  }
  interface PaletteOptions {
    surface?: { main: string; elevated: string; glass: string };
  }
  interface TypeText {
    muted: string;
  }
}

export function createAppTheme(mode: 'light' | 'dark') {
  const dark = mode === 'dark';

  return createTheme({
    ...common,
    palette: {
      mode,
      background: {
        default: dark ? '#0c1012' : '#f3f7f8',
        paper: dark ? '#161c1e' : '#ffffff',
      },
      primary: {
        main: '#21A0CE',
        light: dark ? '#4DB3DC' : '#187896',
        dark: '#1B87AE',
        contrastText: '#061014',
      },
      error: {
        main: dark ? '#f87171' : '#c24141',
      },
      success: {
        main: dark ? '#4ade80' : '#15803d',
      },
      text: {
        primary: dark ? '#f2f4f5' : '#122024',
        secondary: dark ? '#c5cbce' : '#3d5157',
        muted: dark ? '#b0b8bb' : '#5a6e74',
      },
      divider: dark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(18, 32, 36, 0.1)',
      action: {
        hover: dark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(18, 32, 36, 0.06)',
        selected: dark ? 'rgba(33, 160, 206, 0.12)' : 'rgba(33, 160, 206, 0.1)',
        disabledBackground: dark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(18, 32, 36, 0.06)',
      },
      surface: {
        main: dark ? '#12181a' : '#e7eef0',
        elevated: dark ? '#1c2427' : '#ffffff',
        glass: dark ? '#161c1e' : '#ffffff',
      },
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            padding: '0.5rem 1rem',
            WebkitTapHighlightColor: 'transparent',
            transition:
              'background-color 0.2s cubic-bezier(0.23, 1, 0.32, 1), color 0.2s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.2s cubic-bezier(0.23, 1, 0.32, 1)',
            '&:active': {
              transform: 'scale(0.98)',
              backdropFilter: 'blur(16px) saturate(1.15)',
              WebkitBackdropFilter: 'blur(16px) saturate(1.15)',
            },
            '@media (prefers-reduced-motion: reduce)': {
              '&:active': { transform: 'none' },
            },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            WebkitTapHighlightColor: 'transparent',
            transition:
              'background-color 0.2s cubic-bezier(0.23, 1, 0.32, 1), color 0.2s cubic-bezier(0.23, 1, 0.32, 1)',
            '&:hover': {
              backgroundColor: 'transparent',
            },
            '@media (hover: hover) and (pointer: fine)': {
              '&:hover': {
                backgroundColor: 'var(--bt-overlay)',
              },
            },
            '&:active': {
              transform: 'scale(0.97)',
              backgroundColor: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
              backdropFilter: 'blur(18px) saturate(1.2)',
              WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
            },
            '@media (prefers-reduced-motion: reduce)': {
              '&:active': { transform: 'none' },
            },
            '@media (prefers-reduced-transparency: reduce)': {
              '&:active': {
                backgroundColor: 'var(--bt-elevated)',
                backdropFilter: 'none',
                WebkitBackdropFilter: 'none',
              },
            },
          },
        },
      },
      MuiCssBaseline: {
        styleOverrides: {
          ...motionReduce,
          ':focus-visible': {
            outline: '2px solid #21A0CE',
            outlineOffset: 2,
          },
          html: {
            WebkitTapHighlightColor: 'transparent',
          },
          body: {
            backgroundColor: 'var(--bt-bg)',
            color: 'var(--bt-ink)',
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            backgroundColor: 'var(--bt-elevated)',
            '& fieldset': { borderColor: 'var(--bt-hairline)' },
            '&:hover fieldset': { borderColor: dark ? 'rgba(255,255,255,0.22)' : 'rgba(18,32,36,0.18)' },
            '&.Mui-focused fieldset': { borderColor: '#21A0CE' },
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: 'var(--bt-elevated)',
            color: 'var(--bt-ink)',
            border: '1px solid var(--bt-hairline)',
            fontSize: '0.8125rem',
            boxShadow: 'var(--bt-shadow)',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
      MuiMenu: {
        styleOverrides: {
          paper: {
            backgroundColor: 'var(--bt-paper)',
            backgroundImage: 'none',
            border: '1px solid var(--bt-hairline)',
            boxShadow: 'var(--bt-shadow-menu)',
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            backgroundColor: 'var(--bt-paper)',
            backgroundImage: 'none',
            border: '1px solid var(--bt-hairline)',
            boxShadow: 'var(--bt-shadow-menu)',
          },
        },
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundColor: 'var(--bt-bg)',
            backgroundImage: 'none',
          },
        },
      },
    },
  });
}

export const darkTheme = createAppTheme('dark');
export const lightTheme = createAppTheme('light');
