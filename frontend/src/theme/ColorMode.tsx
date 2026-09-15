import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { createAppTheme } from '@/theme';
import { withThemeTransition } from '@/theme/themeTransition';

export const COLOR_MODE_KEY = 'bit-think-color-mode';
export type ColorPreference = 'light' | 'dark' | 'system';
export type ResolvedMode = 'light' | 'dark';

function systemMode(): ResolvedMode {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function readPreference(): ColorPreference {
  try {
    const stored = localStorage.getItem(COLOR_MODE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    /* private mode */
  }
  return 'system';
}

function resolve(preference: ColorPreference): ResolvedMode {
  return preference === 'system' ? systemMode() : preference;
}

function applyDom(mode: ResolvedMode) {
  document.documentElement.dataset.theme = mode;
  document.documentElement.style.colorScheme = mode;
}

function persist(preference: ColorPreference) {
  try {
    localStorage.setItem(COLOR_MODE_KEY, preference);
  } catch {
    /* private mode */
  }
}

interface ColorModeValue {
  preference: ColorPreference;
  mode: ResolvedMode;
  setPreference: (next: ColorPreference) => void;
  toggle: () => void;
}

const ColorModeContext = createContext<ColorModeValue | null>(null);

export function ColorModeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ColorPreference>(readPreference);
  const [mode, setMode] = useState<ResolvedMode>(() => resolve(readPreference()));

  useEffect(() => {
    applyDom(mode);
  }, [mode]);

  const commit = useCallback((nextPref: ColorPreference) => {
    const nextMode = resolve(nextPref);
    setPreferenceState(nextPref);
    setMode(nextMode);
    applyDom(nextMode);
    persist(nextPref);
  }, []);

  const setPreference = useCallback(
    (nextPref: ColorPreference) => {
      if (nextPref === preference) return;
      const nextMode = resolve(nextPref);
      if (nextMode === mode) {
        commit(nextPref);
        return;
      }
      withThemeTransition(() => commit(nextPref));
    },
    [commit, mode, preference]
  );

  useEffect(() => {
    if (preference !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      const nextMode = systemMode();
      if (nextMode === mode) return;
      withThemeTransition(() => {
        setMode(nextMode);
        applyDom(nextMode);
      });
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [preference, mode]);

  const value = useMemo<ColorModeValue>(
    () => ({
      preference,
      mode,
      setPreference,
      toggle: () => setPreference(mode === 'dark' ? 'light' : 'dark'),
    }),
    [preference, mode, setPreference]
  );

  const theme = useMemo(() => createAppTheme(mode), [mode]);

  return (
    <ColorModeContext.Provider value={value}>
      <ThemeProvider theme={theme}>
        <CssBaseline enableColorScheme />
        {children}
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}

export function useColorMode() {
  const ctx = useContext(ColorModeContext);
  if (!ctx) throw new Error('useColorMode must be used inside ColorModeProvider');
  return ctx;
}
