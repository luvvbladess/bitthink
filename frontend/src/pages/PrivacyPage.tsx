import { useEffect } from 'react';
import { Box, Container, Typography } from '@mui/material';
import { BRAND_NAME } from '@/brand';
import { applyPageMeta } from '@/seo';

const SECTIONS: { title: string; body: string[] }[] = [
  {
    title: 'Какие данные мы храним',
    body: [
      'Адрес почты и пароль для входа в аккаунт, историю чатов и загруженные файлы, чтобы вы видели их снова.',
      'Доступы, которые вы сами дали: пароли и ключи из чата и подключение Google. Они хранятся зашифрованными и не показываются даже в интерфейсе.',
    ],
  },
  {
    title: 'Google: Gmail, Диск, Календарь',
    body: [
      'Если вы нажали «Подключить Google», ассистент по вашей просьбе читает письма Gmail и файлы Google Диска, смотрит события календаря и добавляет в него события, когда вы об этом просите.',
      'Мы не отправляем письма от вашего имени, не меняем и не удаляем файлы на Диске.',
      'Данные из Google используются только для ответа на вашу текущую просьбу. Мы не продаём их, не используем для рекламы и не обучаем на них модели. Людям они не показываются, кроме случаев, когда вы сами об этом попросили или этого требует закон.',
      `Использование и передача информации, полученной от Google API, в ${BRAND_NAME} соответствует Google API Services User Data Policy, включая требования Limited Use.`,
      'Отключить доступ можно в Настройках → Google или на странице myaccount.google.com/permissions. После отключения ключ доступа удаляется.',
    ],
  },
  {
    title: 'Кому передаём',
    body: [
      'Текст запроса и нужные для ответа фрагменты уходят провайдерам языковых моделей, которые формируют ответ. Они не используют эти данные для обучения по условиям API.',
    ],
  },
  {
    title: 'Удаление',
    body: ['Чаты, файлы и доступы можно удалить в приложении. Удалённое не восстанавливается.'],
  },
];

export default function PrivacyPage() {
  useEffect(() => {
    applyPageMeta({ title: `Конфиденциальность – ${BRAND_NAME}`, canonicalPath: '/privacy' });
  }, []);

  return (
    <Container maxWidth="sm" sx={{ px: { xs: 2, sm: 3 }, py: { xs: 10, sm: 12 } }}>
      <Typography component="h1" sx={{ fontSize: '2rem', fontWeight: 700, letterSpacing: '-0.03em', mb: 1 }}>
        Политика конфиденциальности
      </Typography>
      <Typography sx={{ color: 'text.secondary', mb: 4 }}>{BRAND_NAME} · обновлено 27 сентября 2026</Typography>
      {SECTIONS.map((section) => (
        <Box key={section.title} component="section" sx={{ mb: 4 }}>
          <Typography component="h2" sx={{ fontSize: '1.2rem', fontWeight: 600, mb: 1.25 }}>
            {section.title}
          </Typography>
          {section.body.map((text) => (
            <Typography key={text} sx={{ color: 'text.secondary', lineHeight: 1.65, mb: 1.25 }}>
              {text}
            </Typography>
          ))}
        </Box>
      ))}
    </Container>
  );
}
