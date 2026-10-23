import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Box, Button, Checkbox, FormControlLabel, Stack, Switch, Typography } from '@mui/material';
import { apiFetch } from '@/api/client';

type Policy = { project_id: string | null; entry_ids: string[] | null; include_memory: boolean; web: boolean;
  last_used: { id: string; title: string; revision: number; kind: string }[] };
type Entry = { id: string; title: string; kind: string };

export function ProjectContextControl({ conversationId, projectId, disabled = false }: { conversationId: string; projectId: string; disabled?: boolean }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Policy | null>(null);
  const [filter, setFilter] = useState('');
  const policy = useQuery<Policy>({ queryKey: ['project-context', conversationId], queryFn: () => apiFetch(`/projects/chat/${conversationId}/context`), refetchInterval: open ? 5000 : 15000 });
  const space = useQuery<{ entries: Entry[] }>({ queryKey: ['project-workspace', projectId], queryFn: () => apiFetch(`/projects/${projectId}/workspace`), enabled: open });
  const save = useMutation({ mutationFn: (value: Policy) => apiFetch(`/projects/chat/${conversationId}/context`, { method: 'PUT', body: JSON.stringify(value) }),
    onSuccess: () => { setDraft(null); setOpen(false); client.invalidateQueries({ queryKey: ['project-context', conversationId] }); } });
  const data = draft || policy.data;
  if (!data) return policy.error ? <Alert severity="error">Не удалось получить настройки контекста.</Alert> : null;
  const entries = space.data?.entries || [];
  const change = (value: Partial<Policy>) => setDraft({ ...data, ...value });
  return <Box sx={{ mb: 1, minWidth: 0 }}>
    <Button size="small" color="inherit" disabled={disabled} aria-expanded={open} onClick={() => { setOpen(value => !value); save.reset(); }} sx={{ color: 'text.secondary', px: .5 }}>
      Контекст проекта · {data.entry_ids === null ? 'все материалы' : `${data.entry_ids.length} выбрано`} · {data.web ? 'с интернетом' : 'без интернета'}
    </Button>
    {open && <Box sx={{ p: 1.5, maxHeight: '35dvh', overflowY: 'auto', border: '1px solid var(--bt-hairline)', borderRadius: '12px', bgcolor: 'var(--bt-panel)' }}>
      <FormControlLabel control={<Switch checked={data.web} disabled={save.isPending} onChange={e => change({ web: e.target.checked })} />} label="Поиск в интернете" />
      <FormControlLabel control={<Switch checked={data.include_memory} disabled={save.isPending} onChange={e => change({ include_memory: e.target.checked })} />} label="Требования и решения проекта" />
      <FormControlLabel control={<Checkbox checked={data.entry_ids === null} disabled={save.isPending} onChange={e => change({ entry_ids: e.target.checked ? null : [] })} />} label="Все материалы проекта" />
      {data.entry_ids !== null && <>
        <Box component="input" aria-label="Найти материал для контекста" placeholder="Найти материал" value={filter} onChange={e => setFilter(e.target.value)} sx={{ width: '100%', p: 1, my: 1, font: 'inherit', bgcolor: 'var(--bt-elevated)', color: 'text.primary', border: '1px solid var(--bt-hairline)', borderRadius: '8px' }} />
        <Box sx={{ maxHeight: 180, overflowY: 'auto' }}>{entries.filter(e => e.title.toLocaleLowerCase('ru').includes(filter.toLocaleLowerCase('ru'))).map(entry => <FormControlLabel key={entry.id} sx={{ display: 'flex', m: 0 }} label={<Typography sx={{ fontSize: 13, overflowWrap: 'anywhere' }}>{entry.title}</Typography>} control={<Checkbox size="small" checked={data.entry_ids!.includes(entry.id)} disabled={save.isPending || !data.include_memory && ['note', 'decision'].includes(entry.kind)} onChange={e => change({ entry_ids: e.target.checked ? [...data.entry_ids!, entry.id] : data.entry_ids!.filter(id => id !== entry.id) })} />} />)}</Box>
        {!entries.length && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>{space.isLoading ? 'Загружаю материалы…' : 'В проекте пока нет материалов.'}</Typography>}
      </>}
      {!!data.last_used.length && <Box sx={{ mt: 1.5 }}><Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Начальный контекст последнего запроса:</Typography>{data.last_used.map(item => <Typography key={item.id} sx={{ fontSize: 12, overflowWrap: 'anywhere' }}>{item.title} · версия {item.revision}</Typography>)}</Box>}
      <Typography sx={{ mt: 1, fontSize: 12, color: 'text.secondary' }}>Изменения применяются к следующим запросам. История беседы сохраняется; выбор ограничивает подгружаемые материалы проекта. Переданный материал не обязательно был процитирован в ответе.</Typography>
      {(save.error || space.error) && <Alert severity="error" sx={{ mt: 1 }}>{save.error?.message || space.error?.message}</Alert>}
      <Stack direction="row" gap={1} sx={{ mt: 1 }}><Button size="small" disabled={save.isPending} onClick={() => save.mutate(data)}>Сохранить</Button><Button size="small" color="inherit" disabled={save.isPending} onClick={() => { setDraft(null); setOpen(false); }}>Отмена</Button></Stack>
    </Box>}
  </Box>;
}
