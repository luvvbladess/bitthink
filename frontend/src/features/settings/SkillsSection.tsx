import { useMemo, useState } from 'react';
import { Alert, Box, Button, Collapse, Stack, TextField, Typography } from '@mui/material';
import { CaretDown, Plus } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { GlowSwitch } from '@/components/GlowSwitch';
import { HOVER_FINE } from '@/theme/effects';

type Skill = {
  name: string;
  title: string;
  description: string;
  body: string;
  triggers: string;
  enabled: boolean;
  origin: 'builtin' | 'custom';
  scope?: 'chat' | 'sandbox';
  updated_at: number;
};

type SkillsPayload = {
  items: Skill[];
  custom_count: number;
  custom_limit: number;
};

type Draft = {
  name: string;
  title: string;
  description: string;
  triggers: string;
  body: string;
};

const emptyDraft = (): Draft => ({ name: '', title: '', description: '', triggers: '', body: '' });

const fieldSx = {
  '& .MuiInputBase-input': { fontSize: '16px' },
  '& .MuiInputLabel-root': { fontSize: '1rem' },
  '& .MuiFormHelperText-root': { mx: 0, fontSize: '0.75rem' },
} as const;

function slugify(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, '_').replace(/[^a-z0-9_]/g, '');
}

export function SkillsSection() {
  const queryClient = useQueryClient();
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [editing, setEditing] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Draft>(emptyDraft());
  const [openName, setOpenName] = useState<string | null>(null);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [query, setQuery] = useState('');

  const { data, isLoading } = useQuery<SkillsPayload>({
    queryKey: ['skills'],
    queryFn: () => apiFetch('/skills'),
  });

  const save = useMutation({
    mutationFn: (payload: Draft) =>
      apiFetch('/skills', {
        method: 'POST',
        body: JSON.stringify({
          name: slugify(payload.name),
          title: payload.title.trim(),
          description: payload.description.trim(),
          triggers: payload.triggers.trim(),
          body: payload.body.trim(),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setAdding(false);
      setDraft(emptyDraft());
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось сохранить скил'),
  });

  const patch = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: Record<string, unknown> }) =>
      apiFetch(`/skills/${encodeURIComponent(name)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setEditing(null);
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось обновить скил'),
  });

  const remove = useMutation({
    mutationFn: (name: string) => apiFetch(`/skills/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось удалить скил'),
  });

  const builtin = useMemo(() => (data?.items || []).filter((item) => item.origin === 'builtin'), [data]);
  const custom = useMemo(() => (data?.items || []).filter((item) => item.origin === 'custom'), [data]);
  const filteredBuiltin = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return builtin;
    return builtin.filter((skill) => {
      const scopeLabel = skill.scope === 'chat' ? 'везде' : 'песочница';
      return [skill.name, skill.title, skill.description, scopeLabel].some((part) =>
        part.toLowerCase().includes(needle),
      );
    });
  }, [builtin, query]);
  const busy = save.isPending || patch.isPending || remove.isPending;
  const customLimit = data?.custom_limit ?? 20;
  const atLimit = (data?.custom_count ?? 0) >= customLimit;

  return (
    <Stack spacing={2}>
      <Box>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          gap={1}
          sx={{ mb: custom.length || adding ? 1 : 0 }}
        >
          <Typography sx={{ fontWeight: 600, fontSize: '0.8125rem', color: 'text.secondary' }}>
            Ваши{data ? ` · ${data.custom_count} из ${customLimit}` : ''}
          </Typography>
          <Button
            onClick={() => {
              setAdding((value) => !value);
              setError('');
            }}
            disabled={busy || atLimit}
            startIcon={adding ? undefined : <Plus size={16} weight="bold" />}
            sx={{ minHeight: 44, minWidth: 44, px: { xs: 1, sm: 0 }, color: 'primary.light', flexShrink: 0 }}
          >
            {adding ? 'Скрыть' : 'Добавить'}
          </Button>
        </Stack>

        {custom.length === 0 && !adding && !isLoading && (
          <Typography sx={{ color: 'text.secondary', fontSize: '0.9375rem', lineHeight: 1.55 }}>
            Пока пусто. Действуют в любом чате. «запомни как скил» или добавьте здесь.
          </Typography>
        )}

        <Stack spacing={0.75}>
          {custom.map((skill) =>
            editing === skill.name ? (
              <SkillForm
                key={skill.name}
                draft={editDraft}
                onChange={setEditDraft}
                nameLocked
                onCancel={() => setEditing(null)}
                onSubmit={() =>
                  patch.mutate({
                    name: skill.name,
                    payload: {
                      title: editDraft.title.trim(),
                      description: editDraft.description.trim(),
                      triggers: editDraft.triggers.trim(),
                      body: editDraft.body.trim(),
                    },
                  })
                }
                busy={busy}
                submitLabel="Сохранить"
              />
            ) : (
              <CustomSkillRow
                key={skill.name}
                skill={skill}
                open={openName === skill.name}
                onToggle={() => setOpenName((current) => (current === skill.name ? null : skill.name))}
                onEdit={() => {
                  setEditing(skill.name);
                  setEditDraft({
                    name: skill.name,
                    title: skill.title,
                    description: skill.description,
                    triggers: skill.triggers,
                    body: skill.body,
                  });
                }}
                onDelete={() => remove.mutate(skill.name)}
                onEnabled={() => patch.mutate({ name: skill.name, payload: { enabled: !skill.enabled } })}
                busy={busy}
              />
            ),
          )}
        </Stack>

        <Collapse in={adding}>
          <Box sx={{ mt: custom.length ? 1.25 : 1 }}>
            <SkillForm
              draft={draft}
              onChange={setDraft}
              onCancel={() => {
                setAdding(false);
                setDraft(emptyDraft());
              }}
              onSubmit={() => save.mutate(draft)}
              busy={busy}
              submitLabel="Сохранить скил"
            />
          </Box>
        </Collapse>
      </Box>

      <Box>
        <Box
          component="button"
          type="button"
          aria-expanded={catalogOpen}
          onClick={() => setCatalogOpen((value) => !value)}
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1,
            width: '100%',
            minHeight: 44,
            px: 0,
            border: 0,
            bgcolor: 'transparent',
            color: 'text.secondary',
            font: 'inherit',
            textAlign: 'left',
            cursor: 'pointer',
            WebkitTapHighlightColor: 'transparent',
            [HOVER_FINE]: { '&:hover': { color: 'primary.light' } },
          }}
        >
          <Typography sx={{ fontWeight: 600, fontSize: '0.8125rem' }}>
            Общие{builtin.length ? ` · ${builtin.length}` : ''}
          </Typography>
          <CaretDown
            size={16}
            weight="bold"
            style={{ transform: catalogOpen ? 'rotate(180deg)' : undefined, transition: 'transform 0.15s' }}
          />
        </Box>
        {!catalogOpen && (
          <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.45, mt: -0.25 }}>
            Среда подхватывает сама. Везде — обычный чат тоже. Песочница — Пилот и Astra.
          </Typography>
        )}
        <Collapse in={catalogOpen}>
          <TextField
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Найти: договор, слайды, код"
            fullWidth
            inputProps={{ enterKeyHint: 'search' }}
            sx={{ ...fieldSx, mt: 1, mb: 1 }}
          />
          {isLoading ? (
            <Typography sx={{ color: 'text.secondary', minHeight: 44 }}>Загружаю…</Typography>
          ) : (
            <Box
              sx={{
                maxHeight: { xs: 220, sm: 260 },
                overflow: 'auto',
                overscrollBehavior: 'contain',
                WebkitOverflowScrolling: 'touch',
                border: '1px solid var(--bt-hairline)',
                borderRadius: '14px',
                bgcolor: 'var(--bt-overlay-faint)',
              }}
            >
              {filteredBuiltin.length === 0 ? (
                <Typography sx={{ color: 'text.secondary', p: 1.5, fontSize: '0.875rem' }}>Ничего не нашлось</Typography>
              ) : (
                filteredBuiltin.map((skill, index) => (
                  <Box
                    key={skill.name}
                    sx={{
                      px: 1.5,
                      py: 1,
                      minHeight: 44,
                      borderTop: index ? '1px solid var(--bt-hairline)' : 0,
                    }}
                  >
                    <Typography sx={{ fontWeight: 600, fontSize: '0.8125rem', letterSpacing: '-0.02em' }}>
                      {skill.name}
                      <Box component="span" sx={{ ml: 0.75, fontWeight: 500, color: 'text.secondary' }}>
                        {skill.scope === 'chat' ? 'везде' : 'песочница'}
                      </Box>
                    </Typography>
                    <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', lineHeight: 1.4 }}>
                      {skill.description}
                    </Typography>
                  </Box>
                ))
              )}
            </Box>
          )}
        </Collapse>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError('')}>
          {error}
        </Alert>
      )}
    </Stack>
  );
}

function CustomSkillRow({
  skill,
  open,
  onToggle,
  onEdit,
  onDelete,
  onEnabled,
  busy,
}: {
  skill: Skill;
  open: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onEnabled: () => void;
  busy: boolean;
}) {
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: '14px',
        bgcolor: 'var(--bt-overlay-faint)',
        border: '1px solid var(--bt-hairline)',
        opacity: skill.enabled ? 1 : 0.7,
      }}
    >
      <Box
        component="button"
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 1,
          width: '100%',
          minHeight: 44,
          p: 0,
          border: 0,
          bgcolor: 'transparent',
          color: 'inherit',
          font: 'inherit',
          textAlign: 'left',
          cursor: 'pointer',
          WebkitTapHighlightColor: 'transparent',
          [HOVER_FINE]: { '&:hover': { color: 'primary.light' } },
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em', overflowWrap: 'anywhere' }}>
            {skill.title || skill.name}
          </Typography>
          <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', mt: 0.25 }}>
            {skill.description}
            {' · везде'}
          </Typography>
        </Box>
        <CaretDown
          size={16}
          weight="bold"
          style={{ flexShrink: 0, marginTop: 4, transform: open ? 'rotate(180deg)' : undefined, transition: 'transform 0.15s' }}
        />
      </Box>
      <Collapse in={open}>
        <Typography sx={{ whiteSpace: 'pre-wrap', color: 'text.secondary', fontSize: '0.875rem', lineHeight: 1.55, mt: 1.25 }}>
          {skill.body || 'Нет подробных правил.'}
        </Typography>
        {skill.triggers ? (
          <Typography sx={{ color: 'text.secondary', fontSize: '0.75rem', mt: 1, overflowWrap: 'anywhere' }}>
            Слова: {skill.triggers}
          </Typography>
        ) : null}
        <Stack
          direction="row"
          spacing={1}
          flexWrap="wrap"
          useFlexGap
          alignItems="center"
          sx={{ mt: 1.25 }}
        >
          <Box
            component="button"
            type="button"
            role="switch"
            aria-checked={skill.enabled}
            aria-label={skill.enabled ? 'Выключить скил' : 'Включить скил'}
            disabled={busy}
            onClick={onEnabled}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.85,
              minHeight: 44,
              px: 0,
              border: 0,
              bgcolor: 'transparent',
              color: skill.enabled ? 'text.primary' : 'text.secondary',
              font: 'inherit',
              fontSize: '0.875rem',
              cursor: busy ? 'not-allowed' : 'pointer',
            }}
          >
            В работе
            <GlowSwitch checked={skill.enabled} />
          </Box>
          <Button onClick={onEdit} disabled={busy} sx={{ minHeight: 44, minWidth: 44, color: 'primary.light' }}>
            Изменить
          </Button>
          <Button onClick={onDelete} disabled={busy} color="error" sx={{ minHeight: 44, minWidth: 44 }}>
            Удалить
          </Button>
        </Stack>
      </Collapse>
    </Box>
  );
}

function SkillForm({
  draft,
  onChange,
  onCancel,
  onSubmit,
  busy,
  submitLabel,
  nameLocked = false,
}: {
  draft: Draft;
  onChange: (next: Draft) => void;
  onCancel: () => void;
  onSubmit: () => void;
  busy: boolean;
  submitLabel: string;
  nameLocked?: boolean;
}) {
  const set = (field: keyof Draft, value: string) => onChange({ ...draft, [field]: value });
  const ready = Boolean(slugify(draft.name) && draft.description.trim() && draft.body.trim().length >= 12);

  return (
    <Stack spacing={1.25}>
      <TextField
        label="Имя латиницей"
        value={draft.name}
        onChange={(e) => set('name', nameLocked ? draft.name : slugify(e.target.value))}
        disabled={nameLocked || busy}
        placeholder="bitship_tone"
        helperText="С буквы, латиница и _. Например bitship_tone"
        fullWidth
        inputProps={{ autoCapitalize: 'none', autoCorrect: 'off', spellCheck: false, enterKeyHint: 'next' }}
        sx={fieldSx}
      />
      <TextField label="Название" value={draft.title} onChange={(e) => set('title', e.target.value)} disabled={busy} placeholder="Тон для Биципа" fullWidth sx={fieldSx} />
      <TextField
        label="Когда применять"
        value={draft.description}
        onChange={(e) => set('description', e.target.value)}
        disabled={busy}
        placeholder="Письма и договоры: коротко, на ты"
        fullWidth
        sx={fieldSx}
      />
      <TextField
        label="Слова-триггеры"
        value={draft.triggers}
        onChange={(e) => set('triggers', e.target.value)}
        disabled={busy}
        placeholder="бицип, bitship, эрс"
        helperText="Через запятую. Можно опереться на описание."
        fullWidth
        sx={fieldSx}
      />
      <TextField
        label="Правила"
        value={draft.body}
        onChange={(e) => set('body', e.target.value)}
        disabled={busy}
        multiline
        minRows={4}
        placeholder="Обращение на ты. Не канцелярит. Результат в Word, не скрипт."
        fullWidth
        sx={fieldSx}
      />
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <Button
          variant="contained"
          onClick={onSubmit}
          disabled={busy || !ready}
          sx={{ minHeight: 44, borderRadius: '999px', width: { xs: '100%', sm: 'auto' } }}
        >
          {submitLabel}
        </Button>
        <Button onClick={onCancel} disabled={busy} sx={{ minHeight: 44, width: { xs: '100%', sm: 'auto' } }}>
          Отмена
        </Button>
      </Stack>
    </Stack>
  );
}
