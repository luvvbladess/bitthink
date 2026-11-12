import { Box, Container, Typography, Stack, useTheme } from '@mui/material';
import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Check, FileText, Images, MagnifyingGlass, Desktop } from '@phosphor-icons/react';
import { IslandButton } from '@/components/IslandButton';
import { BrandMark, BrandLink } from '@/components/BrandMark';
import { BRAND_FONT, BRAND_NAME, BRAND_SEARCH_NAME } from '@/brand';
import { useAuthStore } from '@/stores/authStore';
import { composerShellSx } from '@/theme/effects';
import { SITE_DESCRIPTION, SITE_FAQ, SITE_OG_TITLE, SITE_TITLE, applyPageMeta } from '@/seo';
import { firstQuestionLimit, firstQuestionRoute, saveFirstQuestion } from '@/features/chat/firstQuestion';

const examples = [
  ['Сравнить варианты', 'Сравни тарифы Cursor и GitHub Copilot. Укажи, за что платишь в каждом, и приложи ссылки на тарифы.'],
  ['Разобрать документ', 'Разбери документ, который я приложу. Кратко выдели главное, сроки и вопросы, которые стоит уточнить.'],
  ['Подготовить ответ', 'Напиши короткое сообщение соседу: попроси предупредить меня заранее, если в выходные будет шумный ремонт. Тон дружелюбный.'],
];

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
    note: 'Sol, Исследование и Оркестратор',
    featured: false,
    items: ['75 млн общих единиц для чата и Оркестратора', 'GPT-6.1 Sol и Исследование', 'Источники, документы и холст в чате', '25 картинок в месяц'],
  },
  {
    name: 'Pro+',
    price: '3 990 ₽',
    note: 'Для сложных задач',
    featured: true,
    items: ['Всё из Pro', '165 млн общих единиц', 'Сложные задачи в Оркестраторе', '40 картинок в месяц'],
  },
  {
    name: 'Ultra',
    price: '12 990 ₽',
    note: 'Самая глубокая проработка',
    featured: false,
    items: ['Всё из Pro+', '510 млн общих единиц', 'Больше ресурсов для больших задач', '80 картинок в месяц'],
  },
];

export default function LandingPage() {
  const theme = useTheme();
  const navigate = useNavigate();
  const { hash } = useLocation();
  const token = useAuthStore((s) => s.accessToken);
  const [question, setQuestion] = useState('');
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
    if (!hash) return;
    let id: string;
    try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
    const el = document.getElementById(id);
    if (!el) return;
    const timer = window.setTimeout(() => el.scrollIntoView({ behavior: reduce ? 'instant' : 'smooth', block: 'start' }), 80);
    return () => window.clearTimeout(timer);
  }, [hash, reduce]);

  const start = question.trim() ? firstQuestionRoute : '/chat';
  const goAsk = () => {
    saveFirstQuestion(question);
    navigate(token ? start : question.trim() ? `/register?next=${encodeURIComponent(start)}` : '/register');
  };

  return (
    <Box sx={{ overflowX: 'hidden', position: 'relative' }}>
      <Box sx={{ minHeight: { xs: 'min(100dvh, 630px)', md: 'min(88dvh, 800px)' }, pt: { xs: 9, md: 12 }, pb: { xs: 5, md: 8 }, display: 'flex', alignItems: 'center' }}>
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
                Спросите, разберитесь, сделайте
              </Typography>
            </motion.div>
            <motion.div {...fade} transition={{ ...fade.transition, delay: 0.05 }}>
              <Typography sx={{ color: 'text.secondary', maxWidth: '42ch', mx: 'auto', fontSize: '1.0625rem', lineHeight: 1.55 }}>
                Bit Think найдёт ответ с источниками, разберёт документ или поможет написать сообщение.
              </Typography>
            </motion.div>
            <motion.div {...fade} transition={{ ...fade.transition, delay: 0.1 }} style={{ width: '100%' }}>
              <Box
                component="form"
                onSubmit={(event) => { event.preventDefault(); goAsk(); }}
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
                  textAlign: 'left',
                  font: 'inherit',
                  boxSizing: 'border-box',
                  '&:focus-within': { borderColor: 'primary.light' },
                }}
              >
                <Box sx={{ color: 'primary.light', display: 'grid', placeItems: 'center' }}>
                  <MagnifyingGlass size={18} />
                </Box>
                <Box component="input" aria-label="Ваш вопрос" placeholder="Задайте вопрос"
                  value={question} maxLength={firstQuestionLimit} onChange={event => setQuestion(event.target.value)}
                  sx={{ flex: 1, minWidth: 0, border: 0, outline: 0, bgcolor: 'transparent', color: 'text.primary', font: 'inherit', '&::placeholder': { color: 'text.secondary' } }} />
                <Box
                  component="button"
                  type="submit"
                  aria-label="Продолжить в чате"
                  sx={{
                    width: 44,
                    height: 44,
                    border: 0,
                    cursor: 'pointer',
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
            <Stack direction="row" flexWrap="wrap" justifyContent="center" gap={0.75} aria-label="Примеры вопросов">
              {examples.map(([label, prompt]) => (
                <IslandButton key={label} type="button" onClick={() => setQuestion(prompt)}>{label}</IslandButton>
              ))}
            </Stack>
            {!token && (
              <motion.div {...fade} transition={{ ...fade.transition, delay: 0.16 }}>
                <IslandButton component={Link} to={question.trim() ? `/login?next=${encodeURIComponent(start)}` : '/login'}
                  onClick={() => saveFirstQuestion(question)}>Уже есть аккаунт</IslandButton>
              </motion.div>
            )}
          </Stack>
        </Container>
      </Box>

      <Box id="features" sx={{ py: { xs: 8, md: 10 }, scrollMarginTop: '72px' }}>
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

      <Box id="pricing" sx={{ py: { xs: 8, md: 10 }, scrollMarginTop: '72px' }}>
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
            Лимиты обновляются автоматически. В кабинете видно, сколько осталось до обновления 5-часового и недельного лимитов.
          </Typography>
          <Box sx={{ textAlign: 'center' }}>
            <IslandButton component={Link} to={token ? '/billing' : '/register'}>Смотреть кабинет</IslandButton>
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
            {BRAND_NAME} – ИИ-чат в браузере: вопрос нейросети, ответ с источниками, документы, картинки и холст для
            слайдов. Также ищут как Bit Think и бит синк. Адрес:{' '}
            <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
              bit-think.space
            </Box>
            .
          </Typography>
        </Container>
      </Box>

      <Box id="faq" component="section" aria-labelledby="faq-heading" sx={{ py: { xs: 7, md: 9 }, scrollMarginTop: '72px' }}>
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
