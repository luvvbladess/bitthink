import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Drawer, IconButton, List, ListItem, ListItemButton, Tab, Tabs, TextField, Typography } from '@mui/material';
import { X } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';

export type ToolsMode = 'search' | 'tasks' | 'trash';
type SearchHit = { id: string; title: string; snippet: string; message_id?: number };
type Task = { id: string; conversation_id: string; status: string; prompt: string; progress: string; error?: string; kind?: string };
const labels: Record<string, string> = { queued: 'В очереди', running: 'Выполняется', completed: 'Готово', failed: 'Не удалось завершить', interrupted: 'Прервано', stopped: 'Остановлено', paused: 'На паузе', blocked: 'Нужно ваше действие' };

export function ConversationTools({ mode, initialQuery, onClose, onMode, onSelect }: { mode: ToolsMode | null; initialQuery: string; onClose: () => void; onMode: (mode: ToolsMode) => void; onSelect: (id: string, message?: number) => void }) {
  const client = useQueryClient();
  const [text, setText] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState('');
  const visibleMode = useRef(mode);
  visibleMode.current = mode;
  useEffect(() => { setText(initialQuery); setQuery(initialQuery); setOffset(0); }, [initialQuery]);
  useEffect(() => { setOffset(0); setNotice(''); }, [mode]);
  useEffect(() => { const timer = window.setTimeout(() => { setQuery(text.trim()); setOffset(0); }, 300); return () => clearTimeout(timer); }, [text]);
  const search = useQuery<SearchHit[]>({ queryKey: ['conversation-search', query, offset], queryFn: () => apiFetch(`/conversations/search?q=${encodeURIComponent(query)}&offset=${offset}`), enabled: mode === 'search' && !!query });
  const trash = useQuery<Array<{ id: string; title: string }>>({ queryKey: ['trash', offset], queryFn: () => apiFetch(`/conversations/trash?offset=${offset}`), enabled: mode === 'trash' });
  const tasks = useQuery<Task[]>({ queryKey: ['chat-activity'], queryFn: () => apiFetch('/chat/activity'), enabled: mode === 'tasks', refetchInterval: mode === 'tasks' ? 3000 : false });
  const computer = useQuery<Task[]>({ queryKey: ['computer-tasks'], queryFn: () => apiFetch('/computer/tasks'), enabled: mode === 'tasks', refetchInterval: mode === 'tasks' ? 3000 : false });
  const control = useMutation({ mutationFn: ({ path }: { path: string; origin: ToolsMode }) => apiFetch(path, { method: 'POST' }), onMutate: () => setNotice(''), onSuccess: (_, { origin }) => {
    if (visibleMode.current === origin) setNotice(origin === 'trash' ? 'Беседа восстановлена.' : 'Команда передана. Статус обновится после завершения текущего шага.');
    for (const key of ['trash', 'conversations', 'chat-activity', 'computer-tasks', 'projects']) void client.invalidateQueries({ queryKey: [key] });
  } });
  const open = (id: string, message?: number) => { onSelect(id, message); onClose(); };
  const allTasks = [...(computer.data || []).map(item => ({ ...item, kind: 'computer' })), ...(tasks.data || [])];
  const active = new Set(['queued', 'running', 'external']);
  const sorted = [...allTasks].sort((a, b) => Number(active.has(b.status)) - Number(active.has(a.status)));
  const error = mode === 'search' ? search.error : mode === 'trash' ? trash.error : tasks.error || computer.error;
  const busy = mode === 'search' ? search.isFetching : mode === 'trash' ? trash.isFetching : tasks.isPending || computer.isPending;
  return <Drawer anchor="right" open={mode !== null} onClose={onClose} PaperProps={{ sx: { width: 480, maxWidth: '100vw', bgcolor: 'var(--bt-bg)' } }}>
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2.5, pt: 2 }}><Typography component="h2" variant="h6">Мои беседы и задачи</Typography><IconButton onClick={onClose} aria-label="Закрыть беседы и задачи"><X size={20} /></IconButton></Box>
    <Tabs value={mode || 'search'} onChange={(_, value) => { onMode(value); setNotice(''); }} variant="fullWidth" aria-label="Беседы и задачи"><Tab value="search" label="Поиск" /><Tab value="tasks" label="Задачи" /><Tab value="trash" label="Корзина" /></Tabs>
    <Box sx={{ p: 2.5, overflowY: 'auto', minHeight: 0 }}>
      {mode === 'search' && <TextField autoFocus fullWidth label="В переписке и названиях файлов" value={text} onChange={event => setText(event.target.value)} inputProps={{ maxLength: 200 }} />}
      {mode === 'trash' && <Typography sx={{ color: 'text.secondary', fontSize: 14 }}>Беседы можно восстановить в течение 30 дней. Затем они удаляются окончательно.</Typography>}
      {mode === 'tasks' && <Typography sx={{ color: 'text.secondary', fontSize: 14 }}>Текущие и недавние задачи из ваших бесед. Откройте беседу, чтобы посмотреть результат или добавить уточнение.</Typography>}
      {error && <Alert severity="error" sx={{ mt: 2 }}>Не удалось загрузить данные. <Button onClick={() => void (mode === 'search' ? search.refetch() : mode === 'trash' ? trash.refetch() : Promise.all([tasks.refetch(), computer.refetch()]))}>Повторить</Button></Alert>}
      {control.error && control.variables?.origin === mode && <Alert severity="error" sx={{ mt: 2 }}>{control.error.message}</Alert>}
      {notice && <Alert severity="success" sx={{ mt: 2 }} onClose={() => setNotice('')}>{notice}</Alert>}
      {busy && <Typography role="status" sx={{ mt: 2, color: 'text.secondary' }}>Загружаем…</Typography>}
      {mode === 'search' && !query && <Typography sx={{ mt: 2, color: 'text.secondary' }}>Введите фразу из ответа, название документа или беседы.</Typography>}
      {mode === 'search' && <List>{(search.data || []).map(hit => <ListItem disablePadding key={hit.id}><ListItemButton onClick={() => open(hit.id, hit.message_id)} sx={{ display: 'block', py: 1.5, overflowWrap: 'anywhere' }}><Typography sx={{ fontWeight: 600 }}>{hit.title}</Typography><Typography sx={{ fontSize: 14, color: 'text.secondary', mt: .5 }}>{hit.snippet}</Typography></ListItemButton></ListItem>)}</List>}
      {mode === 'trash' && <List>{(trash.data || []).map(item => <ListItem key={item.id} disableGutters sx={{ gap: 1 }}><Typography sx={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{item.title}</Typography><Button disabled={control.isPending} onClick={() => control.mutate({ path: `/conversations/${item.id}/restore`, origin: 'trash' })}>Восстановить</Button></ListItem>)}</List>}
      {mode === 'tasks' && <List>{sorted.map(task => <ListItem key={`${task.kind}:${task.id}`} disableGutters sx={{ display: 'block', py: 2, borderBottom: '1px solid var(--bt-hairline)' }}>
        <Typography sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{task.prompt || 'Ответ в беседе'}</Typography><Typography sx={{ fontSize: 13, color: 'text.secondary', mt: .5 }}>{labels[task.status] || 'Выполняется'}{task.progress ? ` · ${task.progress}` : ''}</Typography>
        {task.error && <Typography sx={{ fontSize: 13, color: 'text.secondary', mt: .5, overflowWrap: 'anywhere' }}>{task.error}</Typography>}
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: .75 }}>{task.conversation_id && <Button onClick={() => open(task.conversation_id)}>Открыть беседу</Button>}
        {active.has(task.status) && <Button color="inherit" disabled={control.isPending} onClick={() => control.mutate({ path: task.kind === 'computer' ? `/computer/tasks/${task.id}/pause` : `/chat/activity/${task.id}/stop`, origin: 'tasks' })}>{task.kind === 'computer' ? 'Приостановить' : 'Остановить'}</Button>}
        {task.kind === 'computer' && ['paused', 'interrupted', 'failed', 'blocked'].includes(task.status) && <Button disabled={control.isPending} onClick={() => control.mutate({ path: `/computer/tasks/${task.id}/resume`, origin: 'tasks' })}>Продолжить</Button>}</Box>
      </ListItem>)}</List>}
      {!busy && !error && ((mode === 'search' && query && !search.data?.length) || (mode === 'trash' && !trash.data?.length) || (mode === 'tasks' && !allTasks.length)) && <Typography role="status" sx={{ mt: 2, color: 'text.secondary' }}>{mode === 'search' ? 'Ничего не найдено. Попробуйте другую фразу.' : mode === 'trash' ? 'Корзина пуста.' : 'Здесь появятся ваши задачи.'}</Typography>}
      {mode !== 'tasks' && <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>{offset > 0 && <Button onClick={() => setOffset(Math.max(0, offset - (mode === 'trash' ? 50 : 30)))}>Назад</Button>}{(mode === 'search' ? search.data?.length === 30 : trash.data?.length === 50) && <Button onClick={() => setOffset(offset + (mode === 'trash' ? 50 : 30))}>Далее</Button>}</Box>}
    </Box>
  </Drawer>;
}
