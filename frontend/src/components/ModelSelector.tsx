import { useEffect, useRef, useState } from 'react';
import { Box, Popover, Button, Typography, Tooltip } from '@mui/material';
import { CaretDown, Check, Sparkle, MagnifyingGlass, Books, Desktop, Presentation, Atom, FileText } from '@phosphor-icons/react';
import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { composerChipSelectedSx, composerChipSx } from '@/theme/effects';
import { GlowSwitch } from '@/components/GlowSwitch';
import { ASTRA_LABEL, PILOT_LABEL, STUDIO_LABEL, DOCGEN_LABEL } from '@/constants/modes';

interface Model {
  id: string;
  name: string;
  description: string;
  available: boolean;
  multiplier?: number;
}

interface ModelsCache {
  models: Model[];
  selected: string;
  reasoningEffort: string;
  reasoningEfforts?: string[];
  xhighCapable?: boolean;
  supportsReasoningEffort?: boolean;
  researchModel?: string | null;
  computerAvailable?: boolean;
  studioAvailable?: boolean;
  docgenAvailable?: boolean;
  astraAvailable?: boolean;
  multipliers?: Record<string, number>;
}

const ANSWER_MODES = [
  { id: 'auto', label: 'Авто', description: 'Подберёт модель по задаче', model: 'auto', icon: Sparkle },
  { id: 'search', label: 'Поиск', description: 'Свежие ответы с источниками', model: 'kimi-k2.6', icon: MagnifyingGlass },
  { id: 'research', label: 'Исследование', description: 'Глубокий разбор источников на Sol', model: 'gpt-6-sol', icon: Books },
  { id: 'astra', label: ASTRA_LABEL, description: 'Песочница GPT-6: код, договоры, файлы', model: 'gpt-6-astra', icon: Atom },
  { id: 'studio', label: STUDIO_LABEL, description: 'Живой холст: картинки, слайды, лендинг', model: 'studio', icon: Presentation },
  { id: 'docgen', label: DOCGEN_LABEL, description: 'Большой .docx или комплект документов по Word, PDF, Excel и архивам', model: 'docgen', icon: FileText },
  { id: 'computer', label: PILOT_LABEL, description: 'Сам зайдёт на сайт, почту или сервер', model: 'director', icon: Desktop },
] as const;

const REASONING_CAPABLE = new Set([
  'auto',
  'gpt-5-nano',
  'gpt-6-luna',
  'gpt-6-sol',
  'gpt-6-astra',
]);
const XHIGH_CAPABLE = new Set(['gpt-6-sol', 'gpt-6-astra']);

function useModelsQuery() {
  return useQuery({ queryKey: ['models'], queryFn: () => apiFetch('/models'), staleTime: 10_000 });
}

function patchModelsCache(queryClient: QueryClient, patch: Partial<ModelsCache>) {
  queryClient.setQueryData(['models'], (old: ModelsCache | undefined) => {
    if (!old) return old;
    const next = { ...old, ...patch };
    const selected = next.selected;
    return {
      ...next,
      supportsReasoningEffort: REASONING_CAPABLE.has(selected),
      xhighCapable: XHIGH_CAPABLE.has(selected),
    };
  });
}

export function useSelectModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (model: string) => apiFetch('/models/select', { method: 'POST', body: JSON.stringify({ model }) }),
    onMutate: async (model) => {
      const previous = queryClient.getQueryData(['models']);
      patchModelsCache(queryClient, { selected: model });
      await queryClient.cancelQueries({ queryKey: ['models'] });
      return { previous };
    },
    onError: (_err, _model, ctx) => {
      if (ctx?.previous) queryClient.setQueryData(['models'], ctx.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['models'] }),
  });
}

export function useIsComputer() {
  const { data } = useModelsQuery();
  return data?.selected === 'director';
}

export function useSelectedModel() {
  const { data } = useModelsQuery();
  return data?.selected || 'auto';
}

export function SearchModeSelector() {
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const normalizationStarted = useRef(false);
  const { data } = useModelsQuery();
  const selected = data?.selected || 'auto';
  const researchModel = data?.researchModel || null;
  const computerAvailable = Boolean(data?.computerAvailable);
  const studioAvailable = Boolean(data?.studioAvailable);
  const docgenAvailable = Boolean(data?.docgenAvailable);
  const astraAvailable = Boolean(data?.astraAvailable);
  const multipliers = data?.multipliers || {};
  const modes = ANSWER_MODES.map((mode) => {
    if (mode.id === 'research') {
      return { ...mode, model: researchModel || 'gpt-6-sol', description: 'Глубокий разбор на Sol' };
    }
    return mode;
  });
  const matchedMode = modes.find((mode) => {
    if (mode.id === 'research') {
      return selected === researchModel || selected === 'gpt-6-sol' || selected === 'gpt-5.6-sol' || selected === 'gpt-5.6-terra' || selected === 'gpt-5.6-sol-pro';
    }
    return mode.model === selected;
  });
  const selectedMode = matchedMode || modes[0];
  const ActiveIcon = selectedMode.icon;
  const select = useSelectModel();

  useEffect(() => {
    if (data?.selected && !matchedMode && !normalizationStarted.current) {
      normalizationStarted.current = true;
      select.mutate('auto');
    }
  }, [data?.selected, matchedMode]);

  const lit = selectedMode.id !== 'auto';

  return (
    <>
      <Button
        type="button"
        variant="text"
        onClick={(e) => setAnchor(e.currentTarget)}
        aria-label={`Режим ответа: ${selectedMode.label}`}
        aria-haspopup="dialog"
        aria-expanded={Boolean(anchor)}
        sx={{
          ...composerChipSx,
          ...(lit ? composerChipSelectedSx : {}),
          minWidth: { xs: 44, sm: 0 },
          maxWidth: { xs: 44, sm: 'none' },
          px: { xs: 0, sm: 1.1 },
          overflow: 'hidden',
        }}
      >
        <ActiveIcon size={18} weight={selectedMode.id === 'computer' || selectedMode.id === 'studio' || selectedMode.id === 'astra' || selectedMode.id === 'docgen' ? 'fill' : 'bold'} />
        <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>{selectedMode.label}</Box>
        <Box component="span" sx={{ display: { xs: 'none', sm: 'inline-flex' }, flexShrink: 0, lineHeight: 0 }}>
          <CaretDown size={14} weight="bold" />
        </Box>
      </Button>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        slotProps={{
          paper: {
            sx: {
              mb: 1,
              p: 1,
              width: 336,
              maxWidth: 'calc(100vw - 24px)',
              bgcolor: 'surface.elevated',
              backgroundImage: 'none',
              border: '1px solid var(--bt-glow-strong)',
              borderRadius: '18px',
              boxShadow: '0 24px 60px var(--bt-scrim), 0 0 40px var(--bt-glow)',
            },
          },
        }}
      >
        <Typography sx={{ px: 1, pt: 0.5, pb: 1, color: 'text.secondary', fontSize: '0.75rem', fontWeight: 600 }}>
          Как отвечать
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {modes.map((mode) => {
            const Icon = mode.icon;
            const available =
              mode.id === 'auto' ||
              mode.id === 'search' ||
              (mode.id === 'research' && Boolean(researchModel)) ||
              (mode.id === 'astra' && astraAvailable) ||
              (mode.id === 'studio' && studioAvailable) ||
              (mode.id === 'docgen' && docgenAvailable) ||
              (mode.id === 'computer' && computerAvailable);
            const isActive = selectedMode.id === mode.id;
            const factor =
              mode.id === 'search'
                ? multipliers['kimi-k2.6']
                : mode.id === 'research'
                  ? multipliers[mode.model]
                  : mode.id === 'astra'
                    ? multipliers['gpt-6-astra']
                    : mode.id === 'studio'
                      ? multipliers['studio']
                      : mode.id === 'auto'
                        ? 1
                        : undefined;
            const lockedHint =
              mode.id === 'astra'
                ? 'Нужен Ultra'
                : mode.id === 'docgen'
                  ? 'Нужен Creator'
                  : mode.id === 'studio' || mode.id === 'computer'
                    ? 'Нужен Pro'
                    : 'Нужен Pro+';
            return (
              <Box
                key={mode.id}
                component="button"
                type="button"
                disabled={!available}
                aria-pressed={isActive}
                onClick={() => {
                  if (mode.model !== selected) select.mutate(mode.model);
                  setAnchor(null);
                }}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1.15,
                  width: '100%',
                  p: 1.1,
                  minHeight: 56,
                  textAlign: 'left',
                  borderRadius: '14px',
                  border: '1px solid',
                  borderColor: isActive ? 'primary.main' : 'var(--bt-overlay)',
                  bgcolor: isActive ? 'var(--bt-glow)' : 'var(--bt-overlay-faint)',
                  boxShadow: 'none',
                  color: 'text.primary',
                  font: 'inherit',
                  cursor: available ? 'pointer' : 'not-allowed',
                  opacity: available ? 1 : 0.45,
                  transition: 'border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
                  '&:hover': available ? { borderColor: 'primary.light', bgcolor: 'var(--bt-glow)' } : undefined,
                  '&:active': available ? { transform: 'scale(0.98)' } : undefined,
                }}
              >
                <Box
                  sx={{
                    width: 32,
                    height: 32,
                    borderRadius: '10px',
                    flexShrink: 0,
                    display: 'grid',
                    placeItems: 'center',
                    bgcolor: isActive ? 'primary.main' : 'var(--bt-overlay)',
                    color: isActive ? 'primary.contrastText' : 'primary.light',
                  }}
                >
                  <Icon size={16} />
                </Box>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography sx={{ fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.2 }}>
                    {mode.label}
                    {typeof factor === 'number' && (
                      <Box component="span" sx={{ ml: 0.6, color: 'text.secondary', fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
                        ×{factor}
                      </Box>
                    )}
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', fontSize: '0.75rem', lineHeight: 1.35, mt: 0.2 }}>
                    {available ? mode.description : lockedHint}
                  </Typography>
                </Box>
                {isActive && <Check size={16} weight="bold" color="currentColor" />}
              </Box>
            );
          })}
        </Box>
      </Popover>
    </>
  );
}

export function ReasoningEffortSelector() {
  const queryClient = useQueryClient();
  const { data } = useModelsQuery();
  const selectEffort = useMutation({
    mutationFn: (effort: string) => apiFetch('/models/reasoning', { method: 'POST', body: JSON.stringify({ effort }) }),
    onMutate: async (effort) => {
      const previous = queryClient.getQueryData(['models']);
      patchModelsCache(queryClient, { reasoningEffort: effort });
      await queryClient.cancelQueries({ queryKey: ['models'] });
      return { previous };
    },
    onError: (_err, _effort, ctx) => {
      if (ctx?.previous) queryClient.setQueryData(['models'], ctx.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['models'] }),
  });

  const selected = data?.selected || 'auto';
  const currentEffort = data?.reasoningEffort || 'none';
  const supportsEffort = !!data?.supportsReasoningEffort;
  const isAstra = selected === 'gpt-6-astra';
  const enabled = isAstra ? currentEffort === 'max' : currentEffort !== 'none';

  if (!supportsEffort) return null;

  const tooltip = isAstra
    ? enabled
      ? 'Снизить до обычной глубины Astra'
      : 'Включить максимальную глубину Astra'
    : enabled
      ? 'Выключить глубокий многошаговый анализ и снизить расход'
      : 'Включить глубокий многошаговый анализ';

  return (
    <Tooltip title={tooltip} disableTouchListener enterDelay={500}>
      <Box
        component="button"
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Глубокие размышления"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() =>
          selectEffort.mutate(
            isAstra
              ? enabled
                ? 'high'
                : 'max'
              : enabled
                ? 'none'
                : selected === 'gpt-6-sol' || selected === 'gpt-5.6-sol'
                  ? 'high'
                  : 'medium',
          )
        }
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 0.7,
          flexShrink: 0,
          height: { xs: 44, sm: 36 },
          minWidth: { xs: 44, sm: 0 },
          pl: { xs: 0, sm: 0.75 },
          pr: { xs: 0, sm: 0.35 },
          border: 'none',
          bgcolor: 'transparent',
          color: enabled ? 'text.primary' : 'text.secondary',
          font: 'inherit',
          fontSize: '0.75rem',
          fontWeight: 600,
          cursor: 'pointer',
          userSelect: 'none',
          WebkitTapHighlightColor: 'transparent',
          '&:focus': { outline: 'none' },
          '&:focus-visible': {
            outline: '2px solid',
            outlineColor: 'primary.main',
            outlineOffset: 2,
            borderRadius: '999px',
          },
          '&:hover .glow-switch-track': {
            bgcolor: enabled ? 'primary.light' : 'var(--bt-overlay-strong)',
          },
          '&:active': { transform: 'scale(0.98)' },
        }}
      >
        <Box component="span" sx={{ display: { xs: 'none', sm: 'inline' } }}>Размышления</Box>
        <GlowSwitch checked={enabled} />
      </Box>
    </Tooltip>
  );
}
