import { Box, Container, Typography, Stack, useTheme } from '@mui/material';
import { useEffect } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Check, FileText, Images, MagnifyingGlass, Desktop } from '@phosphor-icons/react';
import { IslandButton } from '@/components/IslandButton';
import { BrandMark, BrandLink } from '@/components/BrandMark';
import { BRAND_FONT, BRAND_NAME, BRAND_SEARCH_NAME } from '@/brand';
import { useAuthStore } from '@/stores/authStore';
import { composerShellSx } from '@/theme/effects';
import { SITE_DESCRIPTION, SITE_FAQ, SITE_OG_TITLE, SITE_TITLE, applyPageMeta } from '@/seo';

const features = [
  { title: 'Поиск с источниками', desc: 'Свежие факты и ссылки в ответе — ИИ ищет как Perplexity.', icon: MagnifyingGlass },
  { title: 'Документы', desc: 'PDF, Office, таблицы и картинки прямо в чате.', icon: FileText },
  { title: 'Картинки', desc: 'Опишите, что нужно. Изображение появится в той же беседе.', icon: Images },
  { title: 'Оркестратор', desc: 'Раздаёт должности подходящим ИИ-агентам в песочнице (поиск, сверка, сборка файлов) и собирает один ответ.', icon: Desktop },
];

// Numbers mirror backend/app/billing/plans.py. Each plan lists what it ADDS, not the same lines three times.
const plans = [
  {
    name: 'Pro',
    price: '1 990 ₽',
    note: 'Повседневный чат и Оркестратор',
    featured: false,
    items: ['45 млн токенов в чат', '15 млн токенов на Оркестратора', 'Поиск, документы и Студия', '25 картинок в месяц'],
  },
  {
    name: 'Pro+',
    price: '3 990 ₽',
    note: 'Для сложных задач',
    featured: true,
    items: ['Всё из Pro', '81 млн в чат и 50 млн на Оркестратора', 'GPT-6.1 Sol: эксперт и исследование', '40 картинок в месяц'],
  },
  {
    name: 'Ultra',
    price: '12 990 ₽',
    note: 'Самая глубокая проработка',
    featured: false,
    items: ['Всё из Pro+', '270 млн в чат и 135 млн на Оркестратора', 'Astra: песочница для кода, договоров и файлов', '80 картинок в месяц'],
  },
];

export default function LandingPage() {
  const theme = useTheme();
  const navigate = useNavigate();
  const token = useAuthStore((s) => s.accessToken);
  const reduce = useReducedMotion();
  const fade = {
    initial: reduce ? false : { opacity: 0, y: 14 },
    whileInView: { opacity: 1, y: 0 },
    viewport: { once: true, margin: '-60px' },
    transition: { duration: 0.45, ease: [0.23, 1, 0.32, 1] },
  };

  useEffect(() => {
    applyPageMeta({
      title: SITE_TITLE,
      description: SITE_DESCRIPTION,
      ogTitle: SITE_OG_TITLE,
      canonicalPath: '/',
    });
  }, []);

  useEffect(() => {
    const hash = window.location.hash;
    if (hash) {
      const el = document.querySelector(hash);
      if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
    }
  }, []);

  const goAsk = () => navigate(token ? '/chat' : '/register');

  return (
    <Box sx={{ overflowX: 'hidden', position: 'relative' }}>
      <Box sx={{ minHeight: { xs: '100dvh', md: 'min(88dvh, 800px)' }, pt: { xs: 10, md: 12 }, pb: 8, display: 'flex', alignItems: 'center' }}>
        <Container maxWidth="sm" sx={{ px: { xs: 2, sm: 3 } }}>
          <Stack alignItems="center" textAlign="center" spacing={2.25}>
            <motion.div {...fade}>
              <Box sx={{ mb: { xs: 3.25, md: 4 }, display: 'flex', justifyContent: 'center' }}>
                <BrandMark variant="hero" />
              </Box>
              <Typography
                component="h1"
                sx={{
                  fontFamily: BRAND_FONT,
                  fontSize: { xs: '2.15rem', md: '3.15rem' },
                  fontWeight: 500,
                  letterSpacing: '-0.025em',
                  lineHeight: 1.12,
                  textWrap: 'balance',
                  color: 'text.primary',
                }}
              >
                Bit-Think — спросите что угодно
              </Typography>
            </motion.div>
            <motion.div {...fade} transition={{ ...fade.transition, delay: 0.05 }}>
              <Typography sx={{ color: 'text.secondary', maxWidth: '42ch', mx: 'auto', fontSize: '1.0625rem', lineHeight: 1.55 }}>
                Нейросеть в браузере: поиск с источниками, документы, картинки и Студия.
              </Typography>
            </motion.div>
            <motion.div {...fade} transition={{ ...fade.transition, delay: 0.1 }} style={{ width: '100%' }}>
              <Box
                component="button"
                type="button"
                onClick={goAsk}
                aria-label="Перейти к чату"
                sx={{
                  ...composerShellSx,
                  width: '100%',
                  maxWidth: 560,
                  mx: 'auto',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1.5,
                  px: 2,
                  py: 1.6,
                  color: 'text.secondary',
                  cursor: 'pointer',
                  textAlign: 'left',
                  font: 'inherit',
                  boxSizing: 'border-box',
                  '&:hover': { borderColor: 'primary.light' },
                }}
              >
                <Box sx={{ color: 'primary.light', display: 'grid', placeItems: 'center' }}>
                  <MagnifyingGlass size={18} />
                </Box>
                <Box sx={{ flex: 1, minWidth: 0, color: 'text.secondary' }}>Задайте вопрос</Box>
                <Box
                  sx={{
                    width: 34,
                    height: 34,
                    borderRadius: '50%',
                    bgcolor: 'primary.main',
                    color: 'primary.contrastText',
                    display: 'grid',
                    placeItems: 'center',
                    boxShadow: '0 0 18px var(--bt-glow-strong)',
                    flexShrink: 0,
                  }}
                >
                  <ArrowRight size={16} weight="bold" color={theme.palette.primary.contrastText} />
                </Box>
              </Box>
            </motion.div>
            {!token && (
              <motion.div {...fade} transition={{ ...fade.transition, delay: 0.16 }}>
                <Link to="/login" style={{ textDecoration: 'none' }}>
                  <IslandButton>Уже есть аккаунт</IslandButton>
                </Link>
              </motion.div>
            )}
          </Stack>
        </Container>
      </Box>

      <Box id="features" sx={{ py: { xs: 8, md: 10 } }}>
        <Container maxWidth="md" sx={{ px: { xs: 2, sm: 3 } }}>
          <Typography variant="h2" sx={{ mb: 4, textWrap: 'balance', textAlign: 'center' }}>
            ИИ, поиск и файлы в одном окне
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
              gap: 1.25,
            }}
          >
            {features.map((f) => {
              const Icon = f.icon;
              return (
                <Box
                  key={f.title}
                  sx={{
                    p: 2.25,
                    borderRadius: '16px',
                    border: '1px solid',
                    borderColor: 'divider',
                    bgcolor: 'var(--bt-overlay-faint)',
                  }}
                >
                  <Box sx={{ color: 'primary.light', mb: 1.25, display: 'flex' }}>
                    <Icon size={22} />
                  </Box>
                  <Typography sx={{ fontWeight: 600, mb: 0.5, color: 'text.primary' }}>{f.title}</Typography>
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    {f.desc}
                  </Typography>
                </Box>
              );
            })}
          </Box>
        </Container>
      </Box>

      <Box id="pricing" sx={{ py: { xs: 8, md: 10 } }}>
        <Container maxWidth="md" sx={{ px: { xs: 2, sm: 3 } }}>
          <Typography variant="h2" sx={{ mb: 1.5, textAlign: 'center' }}>
            Тарифы
          </Typography>
          <Typography sx={{ color: 'text.secondary', mb: 3, mx: 'auto', maxWidth: '46ch', textAlign: 'center' }}>
            Онлайн-оплату подключим отдельно. Сейчас доступ выдаёт администратор.
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, minmax(0, 1fr))' },
              gap: 1.5,
              mb: 3,
            }}
          >
            {plans.map((plan) => (
              <Box
                key={plan.name}
                sx={{
                  p: 2.25,
                  minWidth: 0,
                  borderRadius: '16px',
                  border: '1px solid',
                  borderColor: plan.featured ? 'var(--bt-line)' : 'divider',
                  bgcolor: 'background.paper',
                  textAlign: 'left',
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 1 }}>
                  <Typography sx={{ fontWeight: 650 }}>{plan.name}</Typography>
                  {plan.featured && (
                    <Box component="span" sx={{ color: 'primary.light', fontSize: '0.75rem', fontWeight: 600 }}>
                      с GPT-6.1 Sol
                    </Box>
                  )}
                </Box>
                <Typography sx={{ fontWeight: 650, fontSize: '1.5rem', letterSpacing: '-0.03em', mt: 0.5 }}>
                  {plan.price}
                  <Box component="span" sx={{ ml: 0.5, color: 'text.secondary', fontSize: '0.8125rem', fontWeight: 500, letterSpacing: 0 }}>
                    / мес
                  </Box>
                </Typography>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1.5 }}>
                  {plan.note}
                </Typography>
                <Stack component="ul" spacing={0.85} sx={{ listStyle: 'none', p: 0, m: 0 }}>
                  {plan.items.map((item) => (
                    <Box key={item} component="li" sx={{ display: 'flex', gap: 1, fontSize: '0.875rem', lineHeight: 1.45 }}>
                      <Check size={16} weight="bold" style={{ flexShrink: 0, marginTop: 2, color: theme.palette.primary.light }} />
                      {item}
                    </Box>
                  ))}
                </Stack>
              </Box>
            ))}
          </Box>
          <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center', mb: 3 }}>
            У каждого тарифа окно 5 часов и недельный лимит, они обновляются сами.
          </Typography>
          <Box sx={{ textAlign: 'center' }}>
            <Link to={token ? '/billing' : '/register'} style={{ textDecoration: 'none' }}>
              <IslandButton>Смотреть кабинет</IslandButton>
            </Link>
          </Box>
        </Container>
      </Box>

      <Box component="section" aria-labelledby="about-bit-think" sx={{ py: { xs: 7, md: 9 } }}>
        <Container maxWidth="sm" sx={{ px: { xs: 2, sm: 3 } }}>
          <Typography
            id="about-bit-think"
            component="h2"
            variant="h2"
            sx={{ mb: 1.5, textAlign: 'center', textWrap: 'balance' }}
          >
            Что такое {BRAND_NAME}
          </Typography>
          <Typography sx={{ color: 'text.secondary', textAlign: 'center', lineHeight: 1.6 }}>
            {BRAND_NAME} – ИИ-чат в браузере: вопрос нейросети, ответ с источниками, документы, картинки и Студия для
            слайдов. Также ищут как Bit Think и бит синк. Адрес:{' '}
            <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
              bit-think.space
            </Box>
            .
          </Typography>
        </Container>
      </Box>

      <Box id="faq" component="section" aria-labelledby="faq-heading" sx={{ py: { xs: 7, md: 9 } }}>
        <Container maxWidth="sm" sx={{ px: { xs: 2, sm: 3 } }}>
          <Typography id="faq-heading" component="h2" variant="h2" sx={{ mb: 3, textAlign: 'center', textWrap: 'balance' }}>
            Вопросы
          </Typography>
          <Stack spacing={2.25}>
            {SITE_FAQ.map((item) => (
              <Box key={item.q}>
                <Typography component="h3" sx={{ fontWeight: 600, mb: 0.6, fontSize: '1.05rem', letterSpacing: '-0.02em' }}>
                  {item.q}
                </Typography>
                <Typography sx={{ color: 'text.secondary', lineHeight: 1.6 }}>{item.a}</Typography>
              </Box>
            ))}
          </Stack>
        </Container>
      </Box>

      <Box sx={{ py: 5, borderTop: '1px solid', borderColor: 'var(--bt-line)' }}>
        <Container maxWidth="sm" sx={{ px: { xs: 2, sm: 3 } }}>
          <Stack alignItems="center" spacing={1.5}>
            <BrandLink variant="footer" />
            <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center' }}>
              © 2026 {BRAND_NAME} · {BRAND_SEARCH_NAME}
              {' · '}
              <Box component="a" href="/privacy" sx={{ color: 'inherit' }}>Конфиденциальность</Box>
            </Typography>
          </Stack>
        </Container>
      </Box>
    </Box>
  );
}
