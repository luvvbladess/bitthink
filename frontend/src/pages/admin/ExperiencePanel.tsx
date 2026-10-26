import { Alert, Box, Button, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { AdminIsland } from './AdminIsland';

const names: Record<string, string> = { interaction: 'Реакция интерфейса', conversation_open: 'Открытие беседы', list_load: 'Загрузка списка бесед', history_load: 'Загрузка истории', first_token: 'Первый фрагмент ответа', queue_wait: 'Ожидание очереди', reconnect: 'Восстановления связи', disconnect: 'Обрывы связи' };
type Metric = { name: string; device: string; count: number; average_ms: number; fast: number };
export function ExperiencePanel() {
  const query = useQuery<{ days: number; metrics: Metric[] }>({ queryKey: ['admin', 'experience'], queryFn: async () => {
    const result = await apiFetch('/diagnostics/performance');
    if (!Array.isArray(result.metrics)) throw new Error('Измерения временно недоступны');
    return result;
  }, refetchInterval: 60000 });
  return <AdminIsland sx={{ p: { xs: 2, md: 3 } }}>
    <Typography component="h2" sx={{ fontSize: 20, fontWeight: 600 }}>Удобство и скорость · 7 дней</Typography>
    <Typography sx={{ mt: .5, color: 'text.secondary', fontSize: 13 }}>Обезличенные измерения. Содержимое запросов, переписки и адреса страниц не собираются. Реакция интерфейса — худшее измеренное взаимодействие за видимую сессию, не полный расчёт INP.</Typography>
    {query.isError && <Alert severity="error" sx={{ mt: 2 }}>Не удалось загрузить измерения. <Button onClick={() => void query.refetch()}>Повторить</Button></Alert>}
    {query.isPending && <Typography role="status" sx={{ mt: 2 }}>Загружаем измерения…</Typography>}
    {!query.isPending && !query.isError && !query.data?.metrics.length && <Typography sx={{ mt: 2, color: 'text.secondary' }}>Измерения появятся после использования новой версии.</Typography>}
    <Box component="dl" sx={{ m: 0, mt: 2 }}>{query.data?.metrics.map(metric => <Box key={`${metric.name}:${metric.device}`} sx={{ display: 'flex', gap: 2, justifyContent: 'space-between', py: 1.25, borderBottom: '1px solid var(--bt-hairline)', flexWrap: 'wrap' }}>
      <Typography component="dt" sx={{ fontSize: 14 }}>{names[metric.name]} · {metric.device === 'mobile' ? 'Телефон' : metric.device === 'desktop' ? 'Компьютер' : 'Сервер'}</Typography>
      <Typography component="dd" sx={{ m: 0, fontSize: 14, color: 'text.secondary', fontVariantNumeric: 'tabular-nums' }}>{['reconnect', 'disconnect'].includes(metric.name) ? `${metric.count} событий` : `${metric.average_ms} мс в среднем · ${metric.count} замеров`}</Typography>
    </Box>)}</Box>
  </AdminIsland>;
}
