import { useState, useEffect } from 'react';
import { Box, Container, Typography, Stack, TextField, Alert, Link as MuiLink, IconButton } from '@mui/material';
import { Eye, EyeSlash } from '@phosphor-icons/react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { GlassSurface } from '@/components/GlassSurface';
import { PrimaryButton } from '@/components/IslandButton';
import { BrandMark } from '@/components/BrandMark';
import { useAuthStore } from '@/stores/authStore';
import { apiFetch, ApiError } from '@/api/client';
import { BRAND_FONT, BRAND_NAME } from '@/brand';
import { applyPageMeta } from '@/seo';
import { loginDestination } from '@/stores/loginDestination';

interface Props {
  mode: 'login' | 'register';
}

export default function LoginPage({ mode }: Props) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [firstName, setFirstName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const isLogin = mode === 'login';
    applyPageMeta({
      title: isLogin ? `Вход – ${BRAND_NAME}` : `Регистрация – ${BRAND_NAME}`,
      description: isLogin
        ? `Войдите в ${BRAND_NAME}, чтобы продолжить чат.`
        : `Создайте аккаунт ${BRAND_NAME} и начните задавать вопросы.`,
      canonicalPath: isLogin ? '/login' : '/register',
      noindex: true,
    });
  }, [mode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      const endpoint = mode === 'login' ? '/auth/login' : '/auth/register';
      const body: Record<string, string> = { email: email.trim(), password };
      if (mode === 'register') body.first_name = firstName.trim();
      const data = await apiFetch(endpoint, { method: 'POST', body: JSON.stringify(body), timeoutMs: 30000 });
      setUser(null);
      setTokens(data.access_token, data.refresh_token);
      // App owns the bounded profile request; committing tokens can unmount this page.
      navigate(loginDestination(searchParams.toString()), { replace: true });
    } catch (err: any) {
      const status = err instanceof ApiError ? err.status : null;
      setError(status === 401 ? 'Неверный email или пароль. Проверьте данные и попробуйте ещё раз.'
        : status === 409 ? 'Аккаунт с этим email уже существует. Перейдите ко входу.'
        : status === 422 ? 'Проверьте email и заполнение полей. Пароль должен содержать не менее 6 символов.'
        : status === 429 ? 'Слишком много попыток. Подождите немного и попробуйте снова.'
        : 'Не удалось подключиться. Проверьте соединение и повторите попытку. Введённые данные сохранены.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', pt: 7, pb: 6 }}>
      <Container maxWidth="sm">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
        >
          <GlassSurface sx={{ p: { xs: 3, md: 5 } }}>
            <Box sx={{ mb: 2.5, display: 'flex', justifyContent: 'center' }}>
              <BrandMark variant="nav" />
            </Box>
            <Typography
              component="h1" variant="h3"
              sx={{
                mb: 1,
                fontFamily: BRAND_FONT,
                fontWeight: 500,
                letterSpacing: '-0.02em',
              }}
            >
              {mode === 'login' ? 'С возвращением' : 'Создать аккаунт'}
            </Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', mb: 4 }}>
              {mode === 'login'
                ? `Войдите, чтобы продолжить работу с ${BRAND_NAME}`
                : 'Создайте аккаунт, чтобы начать беседу. Доступные режимы зависят от тарифа.'}
            </Typography>

            {error && (
              <Alert severity="error" sx={{ mb: 3, borderRadius: 1 }}>
                {error}
              </Alert>
            )}

            <Box component="form" onSubmit={handleSubmit}>
              <Stack spacing={2.5}>
                {mode === 'register' && (
                  <TextField
                    label="Имя"
                    autoComplete="given-name"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    fullWidth
                    required
                  />
                )}
                <TextField
                  label="Email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  fullWidth
                  required
                />
                <TextField
                  label="Пароль"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  fullWidth
                  required
                  inputProps={{ minLength: 6 }}
                  helperText={mode === 'register' ? 'Не менее 6 символов' : undefined}
                  InputProps={{
                    endAdornment: (
                      <IconButton
                        size="small"
                        onClick={() => setShowPassword((v) => !v)}
                        aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                        edge="end"
                      >
                        {showPassword ? <EyeSlash size={18} /> : <Eye size={18} />}
                      </IconButton>
                    ),
                  }}
                />
                {mode === 'login' && (
                  <Typography variant="caption" sx={{ color: 'text.muted', textAlign: 'right', mt: -1.5 }}>
                    Сброс пароля пока недоступен — напишите администратору.
                  </Typography>
                )}
                <PrimaryButton type="submit" fullWidth disabled={loading} size="large">
                  {loading ? 'Загрузка...' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}
                </PrimaryButton>
              </Stack>
            </Box>

            <Box sx={{ mt: 3, textAlign: 'center', color: 'text.secondary', fontSize: '0.875rem' }}>
              {mode === 'login' ? (
                <>
                  Нет аккаунта?{' '}
                  <MuiLink component={Link} to={searchParams.get('next') ? `/register?next=${encodeURIComponent(searchParams.get('next') || '')}` : '/register'} sx={{ color: 'primary.light' }}>
                    Зарегистрироваться
                  </MuiLink>
                </>
              ) : (
                <>
                  Уже есть аккаунт?{' '}
                  <MuiLink component={Link} to={searchParams.get('next') ? `/login?next=${encodeURIComponent(searchParams.get('next') || '')}` : '/login'} sx={{ color: 'primary.light' }}>
                    Войти
                  </MuiLink>
                </>
              )}
            </Box>
          </GlassSurface>
        </motion.div>
      </Container>
    </Box>
  );
}
