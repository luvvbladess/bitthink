import { useId, useLayoutEffect, useState } from 'react';
import { Alert, Box, Collapse, Drawer, Popover, Button, IconButton, Typography, Tooltip, useMediaQuery } from '@mui/material';
import { CaretDown, Check, Lightning, MagnifyingGlass, Books, Desktop, Presentation, Atom, FileText, Lock, Brain, X, Image as ImageIcon } from '@phosphor-icons/react';
import { useQuery, useMutation, useQueryClient, useIsMutating, useMutationState, type QueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { composerChipSelectedSx, composerChipSx } from '@/theme/effects';
import { GlowSwitch } from '@/components/GlowSwitch';
import { ASTRA_LABEL, DOCGEN_LABEL, EXPRESS_LABEL, PILOT_LABEL, STUDIO_LABEL } from '@/constants/modes';
import { useVisualViewportHeight } from '@/features/chat/useVisualViewportHeight';

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
  selectedName?: string; selectedDescription?: string; searchAvailable?: boolean;
  modeRequirements?: Record<string, string>;
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
  imageQuality?: string;
  imageQualities?: string[];
}

const ANSWER_MODES = [
  { id: 'auto', label: EXPRESS_LABEL, description: 'Быстро и экономно: сам подберёт модель', model: 'auto', icon: Lightning },
  { id: 'search', label: 'Поиск', description: 'Свежие ответы с источниками', model: 'kimi-k2.6', icon: MagnifyingGlass },
  { id: 'research', label: 'Исследование', description: 'Глубокий разбор и проверка источников', model: 'gpt-6-sol', icon: Books },
  { id: 'astra', label: ASTRA_LABEL, description: 'Сложные задачи: код, договоры, файлы', model: 'gpt-6-astra', icon: Atom },
  { id: 'studio', label: STUDIO_LABEL, description: 'Живой холст: картинки, слайды, лендинг', model: 'studio', icon: Presentation },
  { id: 'docgen', label: DOCGEN_LABEL, description: 'Большой .docx или комплект документов по Word, PDF, Excel и архивам', model: 'docgen', icon: FileText },
  { id: 'computer', label: PILOT_LABEL, description: 'Выполняет задачи с файлами, поиском и инструментами', model: 'director', icon: Desktop },
] as const;

interface ModeItem {
  id: string;
  label: string;
  description: string;
  model: string;
  icon: typeof Lightning;
}

/** What the menu shows at first: the everyday modes. The rest sit behind «Ещё». */
const PRIMARY_MODE_IDS = ['auto', 'computer', 'studio'] as const;

const REASONING_CAPABLE = new Set([
  'auto',
  'gpt-5-nano',
  'gpt-6-luna',
  'gpt-6.1-terra',
  'gpt-6-sol',
  'gpt-6-astra',
]);
const XHIGH_CAPABLE = new Set(['gpt-6-sol', 'gpt-6-astra', 'gpt-6.1-terra']);

export function useModelsQuery() {
  return useQuery<ModelsCache>({ queryKey: ['models'], queryFn: ({ signal }) => apiFetch('/models', { signal, timeoutMs: 15000 }), staleTime: 10_000, retry: 1 });
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

export const MODE_PREFERENCES_KEY = ['mode-preferences'];
export function useModePreferencesBusy() { return useIsMutating({ mutationKey: MODE_PREFERENCES_KEY }) > 0; }
export function useModePreferenceError() {
  const { data } = useModelsQuery();
  const mutations = useMutationState({ filters: { mutationKey: MODE_PREFERENCES_KEY }, select: mutation => ({ status: mutation.state.status, submittedAt: mutation.state.submittedAt, setting: mutation.meta?.setting, value: mutation.state.variables }) });
  const latest = mutations.reduce<(typeof mutations)[number] | undefined>((last, current) => !last || current.submittedAt >= last.submittedAt ? current : last, undefined);
  if (latest?.status !== 'error') return '';
  const confirmed = latest.setting === 'selected' ? data?.selected : latest.setting === 'reasoningEffort' ? data?.reasoningEffort : data?.imageQuality;
  if (confirmed === latest.value) return '';
  return latest.setting === 'reasoningEffort' ? 'Не удалось подтвердить настройку размышлений. Проверьте переключатель и повторите действие.'
    : latest.setting === 'imageQuality' ? 'Не удалось подтвердить качество картинок. Проверьте выбранное качество и повторите действие.'
    : 'Не удалось подтвердить выбор режима. Проверьте текущий выбор и повторите действие.';
}

/** Commit only confirmed settings. All three controls share one ordered lane. */
function usePreferenceMutation(path: string, field: 'selected' | 'reasoningEffort' | 'imageQuality', bodyKey: string, resultKey: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { setting: field },
    mutationKey: MODE_PREFERENCES_KEY, scope: { id: 'mode-preferences' },
    mutationFn: (value: string) => apiFetch(path, { method: 'POST', body: JSON.stringify({ [bodyKey]: value }), timeoutMs: 15000 }),
    onMutate: () => queryClient.cancelQueries({ queryKey: ['models'] }),
    onSuccess: (result, value) => patchModelsCache(queryClient, { [field]: result[resultKey] || value }),
    onSettled: () => { void queryClient.invalidateQueries({ queryKey: ['models'] }); },
  });
}

export function useSelectModel() { return usePreferenceMutation('/models/select', 'selected', 'model', 'model'); }

export function useIsComputer() {
  const { data } = useModelsQuery();
  return data?.selected === 'director';
}

export function useSelectedModel() {
  const { data } = useModelsQuery();
  return data?.selected || 'auto';
}

export function SearchModeSelector({ disabled = false }: { disabled?: boolean }) {
  const viewportHeight = useVisualViewportHeight();
  const [anchor, setAnchor] = useState<null | HTMLElement>(null);
  const modelsQuery = useModelsQuery();
  const { data } = modelsQuery;
  const preferencesBusy = useModePreferencesBusy();
  const blocked = disabled || preferencesBusy || !data;
  const selected = data?.selected || 'auto';
  const researchModel = data?.researchModel || null;
  const computerAvailable = Boolean(data?.computerAvailable);
  const studioAvailable = Boolean(data?.studioAvailable);
  const docgenAvailable = Boolean(data?.docgenAvailable);
  const astraAvailable = Boolean(data?.astraAvailable);
  const multipliers = data?.multipliers || {};
  const baseModes: ModeItem[] = ANSWER_MODES.map((mode) => {
    if (mode.id === 'research') {
      return { ...mode, model: researchModel || 'gpt-6-sol', description: 'Глубокий разбор и проверка источников' };
    }
    return mode;
  });
  const currentInCatalog = data?.models?.find(model => model.id === selected);
  const isRepresented = baseModes.some(mode => mode.model === selected)
    || (['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-sol-pro'].includes(selected));
  const customMode: ModeItem | null = selected !== 'auto' && !isRepresented ? {
    id: 'selected-model', model: selected, label: currentInCatalog?.name || data?.selectedName || 'Выбранная модель',
    description: data?.selectedDescription || currentInCatalog?.description || 'Сохранённый выбор для следующих сообщений', icon: Brain,
  } : null;
  const modes = customMode ? [...baseModes, customMode] : baseModes;
  const matchedMode = modes.find(mode => mode.model === selected || (mode.id === 'research' && ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-sol-pro'].includes(selected)));
  const selectedMode = matchedMode || modes[0];
  const ActiveIcon = selectedMode.icon;
  const select = useSelectModel();

  const lit = selectedMode.id !== 'auto';
  const primaryModes = PRIMARY_MODE_IDS.map((id) => modes.find((mode) => mode.id === id)!);
  const moreModes = modes.filter((mode) => !(PRIMARY_MODE_IDS as readonly string[]).includes(mode.id));
  const hiddenSelected = moreModes.some((mode) => mode.id === selectedMode.id);
  // The list is folded away, unless the mode in use lives in it: then it must be visible.
  const [moreOpen, setMoreOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ above: boolean; edge: number; maxHeight: number } | null>(null);
  // Phones get a bottom sheet (thumb reach, no half-covered chat); larger screens keep the popover.
  const isPhone = useMediaQuery('(max-width:599.95px)');
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)');

  // Anchor an edge with CSS, so Collapse cannot push the menu down and then
  // snap it back up. Only the viewport/trigger geometry needs recalculation.
  useLayoutEffect(() => {
    if (!anchor || isPhone) return;
    const place = () => {
      const rect = anchor.getBoundingClientRect();
      const top = window.visualViewport?.offsetTop || 0;
      const bottom = top + viewportHeight;
      const above = rect.top - top >= bottom - rect.bottom;
      setMenuPosition({ above, edge: above ? window.innerHeight - rect.top + 8 : rect.bottom + 8,
        maxHeight: Math.max(0, (above ? rect.top - top : bottom - rect.bottom) - 24) });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    window.visualViewport?.addEventListener('scroll', place);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); window.visualViewport?.removeEventListener('scroll', place); };
  }, [anchor, isPhone, viewportHeight]);

  const renderMode = (mode: ModeItem) => {
            const Icon = mode.icon;
            const available =
              mode.id === 'auto' ||
              (mode.id === 'search' && data?.searchAvailable !== false) ||
              mode.id === 'selected-model' ||
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
            const lockedHint = data?.modeRequirements?.[mode.id] || (
              mode.id === 'astra'
                ? 'Нужен Pro+'
                : mode.id === 'docgen'
                  ? 'Нужен Creator'
                  : mode.id === 'studio' || mode.id === 'computer'
                    ? 'Нужен Pro'
                    : 'Нужен Pro');
            return (
              <Box
                key={mode.id}
                component="button"
                type="button"
                disabled={!available || blocked}
                aria-pressed={isActive}
                onClick={() => {
                  if (mode.model === selected) setAnchor(null);
                  else select.mutate(mode.model, { onSuccess: () => setAnchor(null) });
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
                  borderColor: isActive ? 'primary.main' : available ? 'var(--bt-overlay)' : 'var(--bt-overlay-faint)',
                  bgcolor: isActive ? 'var(--bt-glow)' : available ? 'var(--bt-overlay-faint)' : 'transparent',
                  boxShadow: 'none',
                  // A locked row stays readable (opacity would push the hint below AA contrast).
                  color: available ? 'text.primary' : 'text.secondary',
                  font: 'inherit',
                  cursor: available ? 'pointer' : 'not-allowed',
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
                    color: isActive ? 'primary.contrastText' : available ? 'primary.light' : 'text.secondary',
                  }}
                >
                  <Icon size={16} />
                </Box>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography sx={{ fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.2 }}>
                    {mode.label}
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', fontSize: '0.75rem', lineHeight: 1.35, mt: 0.2 }}>
                    {mode.description}{!available && ` · ${lockedHint}`}
                  </Typography>
                </Box>
                {available && typeof factor === 'number' && <CostDots factor={factor} active={isActive} />}
                {!available && <Lock size={14} weight="bold" aria-hidden />}
                {isActive && <Check size={16} weight="bold" color="currentColor" />}
              </Box>
            );
  };

  const menuContent = (
    <>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><Typography sx={{ px: 1, pt: 0.5, pb: 1, color: 'text.secondary', fontSize: '0.75rem', fontWeight: 600 }}>
          Как отвечать
        </Typography>{isPhone && <IconButton aria-label="Закрыть выбор режима" onClick={() => setAnchor(null)} sx={{ width: 44, height: 44 }}><X size={18} /></IconButton>}</Box>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {primaryModes.map(renderMode)}
        </Box>
        <Typography sx={{ px: 1, pt: 1, fontSize: 12, color: 'text.secondary' }}>Выбор применяется к следующим сообщениям. Текущий ответ продолжит работу.</Typography>
        {select.error && selected !== select.variables && <Alert severity="error" sx={{ mt: 1 }}>Не удалось подтвердить выбор режима. Повторите действие. {select.error.message}</Alert>}
        <ImageQualityControl disabled={disabled} />
        <MoreModes
          modes={moreModes}
          open={moreOpen}
          onToggle={() => setMoreOpen((value) => !value)}
          renderMode={renderMode}
          reduceMotion={reduceMotion}
        />
    </>
  );

  return (
    <>
      <Button
        type="button"
        variant="text"
        onClick={(e) => {
          setMoreOpen(hiddenSelected);
          setAnchor(e.currentTarget);
        }}
        disabled={blocked}
        aria-busy={preferencesBusy}
        aria-label={`Режим ответа: ${selectedMode.label}`}
        aria-haspopup="dialog"
        aria-expanded={Boolean(anchor)}
        sx={{
          ...composerChipSx,
          ...(lit ? composerChipSelectedSx : {}),
          minWidth: 44,
          maxWidth: { xs: 132, sm: 'none' },
          // On very narrow phones the chip may shrink to its icon so Send is never pushed off screen.
          flexShrink: { xs: 1, sm: 0 },
          px: 1.1,
          overflow: 'hidden',
        }}
      >
        <ActiveIcon size={18} weight={selectedMode.id === 'computer' || selectedMode.id === 'studio' || selectedMode.id === 'astra' || selectedMode.id === 'docgen' ? 'fill' : 'bold'} />
        <Box component="span" sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', '@media (max-width:339.95px)': { display: 'none' } }}>{selectedMode.label}</Box>
        <Box component="span" sx={{ display: { xs: 'none', sm: 'inline-flex' }, flexShrink: 0, lineHeight: 0 }}>
          <CaretDown size={14} weight="bold" />
        </Box>
      </Button>
      {modelsQuery.isError && !data && <Button size="small" onClick={() => void modelsQuery.refetch()}>Повторить загрузку режимов</Button>}
      {isPhone ? (
        <Drawer
          anchor="bottom"
          open={Boolean(anchor)}
          onClose={() => setAnchor(null)}
          PaperProps={{
            role: 'dialog',
            'aria-label': 'Выбор режима',
            'aria-modal': true,
            sx: {
              p: 1.5,
              pb: 'max(16px, env(safe-area-inset-bottom))',
              maxHeight: Math.round(viewportHeight * .86),
              bottom: Math.max(0, window.innerHeight - viewportHeight - (window.visualViewport?.offsetTop || 0)),
              bgcolor: 'surface.elevated',
              backgroundImage: 'none',
              border: '1px solid var(--bt-hairline)',
              borderBottom: 'none',
              borderTopLeftRadius: '20px',
              borderTopRightRadius: '20px',
            },
          }}
          BackdropProps={{ sx: { bgcolor: 'var(--bt-scrim)' } }}
        >
          <Box sx={{ width: 40, height: 4, borderRadius: 99, bgcolor: 'var(--bt-overlay-strong)', mx: 'auto', mb: 1 }} />
          {menuContent}
        </Drawer>
      ) : (
        <Popover
          open={Boolean(anchor)}
          anchorEl={anchor}
          transitionDuration={reduceMotion ? 0 : undefined}
          onClose={() => setAnchor(null)}
          anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
          transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          slotProps={{
            paper: {
              role: 'dialog',
              'aria-label': 'Выбор режима',
              'aria-modal': true,
              sx: {
                ...(menuPosition && {
                  top: menuPosition.above ? 'auto !important' : `${menuPosition.edge}px !important`,
                  bottom: menuPosition.above ? `${menuPosition.edge}px` : 'auto',
                  maxHeight: menuPosition.maxHeight,
                  transformOrigin: menuPosition.above ? 'left bottom !important' : 'left top !important',
                }),
                p: 1,
                width: 336,
                maxWidth: 'calc(100vw - 24px)',
                bgcolor: 'surface.elevated',
                backgroundImage: 'none',
                border: '1px solid var(--bt-hairline)',
                borderRadius: '18px',
                boxShadow: 'var(--bt-shadow-menu)',
              },
            },
          }}
        >
  {menuContent}
        </Popover>
      )}
    </>
  );
}

/** The less common modes, folded under one quiet row so the menu opens short. */
function MoreModes({
  modes,
  open,
  onToggle,
  renderMode,
  reduceMotion,
}: {
  modes: readonly ModeItem[];
  open: boolean;
  onToggle: () => void;
  renderMode: (mode: ModeItem) => JSX.Element;
  reduceMotion: boolean;
}) {
  const contentId = useId();
  return (
    <Box sx={{ mt: 1.25, borderTop: '1px solid var(--bt-hairline)' }}>
      <Box
        component="button"
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={onToggle}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          width: '100%',
          minHeight: 48,
          px: 0.75,
          border: 0,
          bgcolor: 'transparent',
          color: 'text.primary',
          font: 'inherit',
          textAlign: 'left',
          cursor: 'pointer',
          WebkitTapHighlightColor: 'transparent',
          '&:hover': { color: 'primary.light' },
          '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2, borderRadius: '10px' },
        }}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography sx={{ fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.2 }}>Ещё</Typography>
            <Typography
              aria-hidden={open}
              sx={{ visibility: open ? 'hidden' : 'visible', color: 'text.secondary', fontSize: '0.75rem', lineHeight: 1.35, mt: 0.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {modes.map((mode) => mode.label).join(', ')}
            </Typography>
        </Box>
        <CaretDown
          size={16}
          weight="bold"
          aria-hidden
          style={{ flexShrink: 0, transform: open ? 'rotate(180deg)' : undefined, transition: 'transform 0.16s cubic-bezier(0.23, 1, 0.32, 1)' }}
        />
      </Box>
      <Collapse in={open} timeout={reduceMotion ? 0 : 180}>
        <Box id={contentId} sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, pt: 0.5 }}>
          {modes.map(renderMode)}
        </Box>
      </Collapse>
    </Box>
  );
}

const IMAGE_QUALITY_OPTIONS = [
  { id: 'low', label: 'Быстро', hint: 'Для простых эскизов и черновиков' },
  { id: 'medium', label: 'Стандарт', hint: 'Баланс скорости и деталей' },
  { id: 'high', label: 'Высокое', hint: 'Максимум деталей, генерация дольше' },
] as const;

/** One dial for every picture the assistant draws: in chat, in Studio, and when editing a picture. */
function ImageQualityControl({ disabled = false }: { disabled?: boolean }) {
  const { data } = useModelsQuery();
  const current = data?.imageQuality || 'high';
  const busy = useModePreferencesBusy();
  const select = usePreferenceMutation('/models/image-quality', 'imageQuality', 'quality', 'quality');
  const active = IMAGE_QUALITY_OPTIONS.find(option => option.id === current) || IMAGE_QUALITY_OPTIONS[2];
  return (
    <Box sx={{ mt: 1.25, pt: 1.25, px: 0.25, borderTop: '1px solid var(--bt-hairline)' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 0.75, pb: 1, color: 'text.secondary' }}>
        <ImageIcon size={14} weight="bold" aria-hidden />
        <Typography id="image-quality-label" sx={{ fontSize: '0.75rem', fontWeight: 600 }}>
          Качество картинок
        </Typography>
      </Box>
      <Box
        role="radiogroup"
        aria-labelledby="image-quality-label"
        sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 0.5, p: 0.4, borderRadius: '12px', bgcolor: 'var(--bt-overlay-faint)', border: '1px solid var(--bt-hairline)' }}
      >
        {IMAGE_QUALITY_OPTIONS.map((option) => {
          const checked = option.id === current;
          return (
            <Box
              key={option.id}
              component="button"
              type="button"
              role="radio"
              disabled={disabled || busy}
              aria-checked={checked}
              onClick={() => {
                if (!checked) select.mutate(option.id);
              }}
              sx={{
                minHeight: { xs: 44, sm: 36 },
                border: '1px solid',
                borderColor: checked ? 'var(--bt-line)' : 'transparent',
                borderRadius: '9px',
                bgcolor: checked ? 'var(--bt-elevated)' : 'transparent',
                color: checked ? 'text.primary' : 'text.secondary',
                font: 'inherit',
                fontSize: '0.8125rem',
                fontWeight: checked ? 600 : 500,
                cursor: 'pointer',
                transition: 'background-color 0.16s cubic-bezier(0.23, 1, 0.32, 1), color 0.16s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.16s cubic-bezier(0.23, 1, 0.32, 1)',
                '&:hover': { color: 'text.primary' },
                '&:active': { transform: 'scale(0.97)' },
                '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 1 },
              }}
            >
              {option.label}
            </Box>
          );
        })}
      </Box>
      {select.error && current !== select.variables && <Alert severity="error" sx={{ mt: 1 }}>Не удалось подтвердить качество картинок. {select.error.message}</Alert>}
      <Typography sx={{ px: 0.75, pt: 0.9, color: 'text.secondary', fontSize: '0.75rem', lineHeight: 1.4 }} aria-live="polite">
        {active.hint}
      </Typography>
    </Box>
  );
}

/** How fast a mode spends the plan, as four dots. The exact multiplier stays in the tooltip. */
function CostDots({ factor, active }: { factor: number; active?: boolean }) {
  const level = factor <= 1 ? 1 : factor <= 10 ? 2 : factor <= 30 ? 3 : 4;
  const words = ['', 'Расходует лимит экономно', 'Расходует лимит заметно', 'Расходует лимит быстро', 'Расходует лимит очень быстро'];
  const label = `${words[level]}: ×${factor} к быстрому режиму`;
  return (
    <Tooltip title={label} placement="left" enterDelay={300}>
      <Box role="img" aria-label={label} sx={{ display: 'flex', gap: '3px', alignItems: 'center', flexShrink: 0, px: 0.25 }}>
        {[1, 2, 3, 4].map((dot) => (
          <Box
            key={dot}
            component="span"
            sx={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              bgcolor: dot <= level ? (active ? 'primary.light' : 'text.secondary') : 'var(--bt-overlay-strong)',
            }}
          />
        ))}
      </Box>
    </Tooltip>
  );
}

export function ReasoningEffortSelector({ disabled = false }: { disabled?: boolean }) {
  const { data } = useModelsQuery();
  const busy = useModePreferencesBusy();
  const selectEffort = usePreferenceMutation('/models/reasoning', 'reasoningEffort', 'effort', 'effort');

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
    <>
    <Tooltip title={tooltip} disableTouchListener enterDelay={500}>
      <Box
        component="button"
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Глубокие размышления"
        disabled={disabled || busy}
        aria-busy={busy}
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
          minWidth: 44,
          pl: 0.75,
          pr: 0.35,
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
          '@media (max-width:439.95px)': {
            px: 1,
            borderRadius: '999px',
            bgcolor: enabled ? 'var(--bt-glow)' : 'transparent',
          },
        }}
      >
        {/* A bare switch next to a mic says nothing: wide phones get the word, narrow ones an icon. */}
        <Box component="span" sx={{ '@media (max-width:439.95px)': { display: 'none' } }}>Размышления</Box>
        <Box component="span" aria-hidden sx={{ display: 'none', lineHeight: 0, color: enabled ? 'primary.light' : 'inherit', '@media (max-width:439.95px)': { display: 'inline-flex' } }}>
          <Brain size={18} weight={enabled ? 'fill' : 'bold'} />
        </Box>
        {/* On phones the brain icon alone carries the state: the track took the width the mode name needs. */}
        <Box component="span" sx={{ display: 'inline-flex', '@media (max-width:439.95px)': { display: 'none' } }}>
          <GlowSwitch checked={enabled} />
        </Box>
      </Box>
    </Tooltip>
    </>
  );
}
