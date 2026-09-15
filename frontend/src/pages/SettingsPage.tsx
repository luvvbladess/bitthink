import { useEffect, useRef, useState } from 'react';
import { Box, CircularProgress, Typography, Stack, IconButton, Button, TextField, Alert } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Camera, PencilSimple, Check, X, CaretRight } from '@phosphor-icons/react';
import { apiFetch, apiFormData } from '@/api/client';
import { UserAvatar } from '@/components/UserAvatar';
import { useAuthStore } from '@/stores/authStore';
import { MemorySection } from '@/features/settings/MemorySection';
import { SkillsSection } from '@/features/settings/SkillsSection';
import { AccountPageShell, AccountSection } from '@/features/account/AccountChrome';
import { TIER_LABELS } from '@/constants/tiers';
import { ColorModeSwitch } from '@/components/ColorModeToggle';
import { HOVER_FINE } from '@/theme/effects';
import type { Subscription } from '@/api/billing';
import { BRAND_NAME } from '@/brand';
import { applyPageMeta } from '@/seo';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [newPrompt, setNewPrompt] = useState('');
  const [error, setError] = useState('');
  const [profileError, setProfileError] = useState('');
  const [isEditingName, setIsEditingName] = useState(false);
  const [nameInput, setNameInput] = useState('');
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    applyPageMeta({
      title: `Настройки – ${BRAND_NAME}`,
      canonicalPath: '/settings',
      noindex: true,
    });
  }, []);

  useEffect(() => {
    if (!isEditingName) setNameInput(user?.first_name || '');
  }, [user?.first_name, isEditingName]);

  const { data: prompts } = useQuery({ queryKey: ['prompts'], queryFn: () => apiFetch('/models/prompts') });
  const { data: sub } = useQuery<Subscription>({
    queryKey: ['subscription'],
    queryFn: () => apiFetch('/billing/subscription'),
    staleTime: 30_000,
  });

  const addPrompt = useMutation({
    mutationFn: (prompt: string) => apiFetch('/models/prompts', { method: 'POST', body: JSON.stringify({ prompt }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] });
      setNewPrompt('');
      setError('');
    },
    onError: (err: Error) => setError(err.message || 'Не удалось добавить промпт'),
  });

  const deletePrompt = useMutation({
    mutationFn: (index: number) => apiFetch(`/models/prompts/${index}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['prompts'] }),
  });

  const activatePrompt = useMutation({
    mutationFn: (index: number | null) => apiFetch(`/models/prompts/${index}/activate`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['prompts'] }),
  });

  const updateProfile = useMutation({
    mutationFn: (first_name: string) => apiFetch('/auth/profile', { method: 'PATCH', body: JSON.stringify({ first_name }) }),
    onSuccess: (data) => {
      useAuthStore.getState().updateUser({ first_name: data.first_name, avatar_url: data.avatar_url });
      setProfileError('');
    },
    onError: () => setProfileError('Не удалось сохранить имя'),
  });

  const uploadAvatar = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiFormData('/auth/avatar', formData);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Не удалось загрузить фото');
      }
      return res.json();
    },
    onSuccess: (data) => {
      useAuthStore.getState().updateUser({ avatar_url: data.avatar_url, first_name: data.first_name });
      setProfileError('');
    },
    onError: (err: Error) => setProfileError(err.message || 'Не удалось загрузить фото'),
  });

  const removeAvatar = useMutation({
    mutationFn: () => apiFetch('/auth/avatar', { method: 'DELETE' }),
    onSuccess: (data) => useAuthStore.getState().updateUser({ avatar_url: data.avatar_url }),
  });

  const startEditName = () => {
    setNameInput(user?.first_name || '');
    setIsEditingName(true);
  };

  const saveName = () => {
    const trimmed = nameInput.trim();
    setIsEditingName(false);
    if (trimmed && trimmed !== user?.first_name) {
      updateProfile.mutate(trimmed);
    }
  };

  const tierLabel = sub?.name || (user?.subscription_tier ? TIER_LABELS[user.subscription_tier] || user.subscription_tier : null);

  return (
    <AccountPageShell title="Настройки" lede="Имя, тема, память, скилы и правила для ответов.">
      <AccountSection featured>
        <input
          type="file"
          ref={avatarInputRef}
          accept="image/jpeg,image/png,image/webp"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) uploadAvatar.mutate(file);
            e.target.value = '';
          }}
        />
        <Stack direction="row" spacing={2} alignItems="center">
          <Box sx={{ position: 'relative', width: 72, height: 72, flexShrink: 0 }}>
            <UserAvatar user={user} sx={{ width: 72, height: 72, fontSize: '1.5rem', borderRadius: '16px' }} />
            <Box
              component="button"
              type="button"
              onClick={() => avatarInputRef.current?.click()}
              aria-label="Изменить фото профиля"
              sx={{
                position: 'absolute',
                right: -4,
                bottom: -4,
                width: 44,
                height: 44,
                display: 'grid',
                placeItems: 'center',
                border: '1px solid var(--bt-hairline)',
                borderRadius: '12px',
                bgcolor: 'var(--bt-elevated)',
                color: 'text.primary',
                cursor: 'pointer',
                boxShadow: 'var(--bt-shadow)',
                WebkitTapHighlightColor: 'transparent',
                [HOVER_FINE]: {
                  '&:hover': { color: 'primary.light', bgcolor: 'var(--bt-glow)' },
                },
                '&:active': {
                  transform: 'scale(0.97)',
                  bgcolor: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
                  backdropFilter: 'blur(16px)',
                },
              }}
            >
              {uploadAvatar.isPending ? <CircularProgress size={16} sx={{ color: 'inherit' }} /> : <Camera size={18} weight="bold" />}
            </Box>
          </Box>
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            {isEditingName ? (
              <Stack direction="row" spacing={0.5} alignItems="center">
                <TextField
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  size="small"
                  variant="standard"
                  autoFocus
                  fullWidth
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveName();
                    if (e.key === 'Escape') setIsEditingName(false);
                  }}
                />
                <IconButton onClick={saveName} aria-label="Сохранить имя" sx={{ width: 44, height: 44 }}>
                  <Check size={16} />
                </IconButton>
                <IconButton onClick={() => setIsEditingName(false)} aria-label="Отменить" sx={{ width: 44, height: 44 }}>
                  <X size={16} />
                </IconButton>
              </Stack>
            ) : (
              <Stack direction="row" spacing={0.25} alignItems="center">
                <Typography sx={{ fontWeight: 600, fontSize: '1.125rem', letterSpacing: '-0.025em' }} noWrap>
                  {user?.first_name || user?.email?.split('@')[0]}
                </Typography>
                <IconButton onClick={startEditName} aria-label="Изменить имя" sx={{ color: 'text.secondary', width: 44, height: 44 }}>
                  <PencilSimple size={16} />
                </IconButton>
              </Stack>
            )}
            <Typography sx={{ color: 'text.secondary', fontSize: '0.875rem' }} noWrap>
              {user?.email}
            </Typography>
            {user?.avatar_url && (
              <Button
                size="small"
                onClick={() => removeAvatar.mutate()}
                disabled={removeAvatar.isPending}
                sx={{ color: 'text.secondary', px: 0, minWidth: 0, mt: 0.25, fontSize: '0.8125rem', minHeight: 44 }}
              >
                Удалить фото
              </Button>
            )}
          </Box>
        </Stack>
        {profileError && (
          <Alert severity="error" sx={{ mt: 2 }} onClose={() => setProfileError('')}>
            {profileError}
          </Alert>
        )}
      </AccountSection>

      <Box
        component={RouterLink}
        to="/billing"
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1.5,
          p: { xs: 2, sm: 2.25 },
          minHeight: 64,
          borderRadius: '16px',
          bgcolor: 'var(--bt-panel)',
          border: '1px solid var(--bt-hairline)',
          color: 'text.primary',
          textDecoration: 'none',
          WebkitTapHighlightColor: 'transparent',
          [HOVER_FINE]: {
            '&:hover': { borderColor: 'var(--bt-line)', bgcolor: 'var(--bt-glow)' },
          },
          '&:active': {
            transform: 'scale(0.99)',
            bgcolor: 'color-mix(in srgb, var(--bt-elevated) 88%, transparent)',
            backdropFilter: 'blur(16px)',
          },
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em' }}>Кабинет</Typography>
          <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', mt: 0.25 }}>
            {tierLabel ? `${tierLabel} · остаток и тарифы` : 'Остаток, тарифы и расход'}
          </Typography>
        </Box>
        <CaretRight size={18} weight="bold" />
      </Box>

      <AccountSection title="Оформление" hint="Светлая тема держит тот же циан. Система следует настройке устройства.">
        <ColorModeSwitch />
      </AccountSection>

      <AccountSection
        title="Память"
        hint="Сюда попадают устойчивые предпочтения: тон, формат, язык. Не текущие задачи и не прошлые файлы. Можно выключить, поправить или стереть."
      >
        <MemorySection />
      </AccountSection>

      <AccountSection
        title="Скилы"
        hint="Свои действуют в любом чате. Из общих: часть везде, остальные только в Пилоте и Astra."
      >
        <SkillsSection />
      </AccountSection>

      <AccountSection
        title="Как отвечать"
        hint="Эти правила добавляются ко всем новым ответам. Модель и глубину размышлений выбираете в чате."
      >
        <Stack spacing={1.25}>
          {prompts?.prompts.map((p: string, i: number) => {
            const active = prompts.active === p;
            return (
              <Box
                key={i}
                sx={{
                  p: 1.75,
                  borderRadius: '14px',
                  bgcolor: active ? 'var(--bt-glow)' : 'var(--bt-overlay-faint)',
                  border: '1px solid',
                  borderColor: active ? 'var(--bt-line)' : 'var(--bt-hairline)',
                }}
              >
                <Typography sx={{ mb: 1.25, whiteSpace: 'pre-wrap', fontSize: '0.875rem', lineHeight: 1.5 }}>
                  {p}
                </Typography>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Button
                    size="small"
                    onClick={() => activatePrompt.mutate(i)}
                    variant={active ? 'contained' : 'outlined'}
                    sx={{ minHeight: 44, borderRadius: '999px', px: 1.75 }}
                  >
                    {active ? 'В работе' : 'Включить'}
                  </Button>
                  <Button size="small" color="error" onClick={() => deletePrompt.mutate(i)} sx={{ minHeight: 44 }}>
                    Удалить
                  </Button>
                </Stack>
              </Box>
            );
          })}

          <TextField
            label="Новое правило"
            multiline
            rows={3}
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            fullWidth
          />
          <Button
            variant="contained"
            onClick={() => addPrompt.mutate(newPrompt)}
            disabled={!newPrompt.trim()}
            sx={{ minHeight: 44, borderRadius: '999px', alignSelf: { sm: 'flex-start' }, px: 2.25 }}
          >
            Добавить
          </Button>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </AccountSection>
    </AccountPageShell>
  );
}
