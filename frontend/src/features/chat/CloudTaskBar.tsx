import { useState } from 'react';
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { activitySummary } from '@/components/ActivityFeed';

export type CloudTask = { id: string; status: string; conversation_id: string | null; enabled: boolean; prompt: string; progress: string; error: string; run_number: number };
const labels: Record<string, string> = { queued: 'Задача в очереди', running: 'Задача выполняется в фоне', paused: 'Задача на паузе', interrupted: 'Выполнение прервано', failed: 'Не удалось завершить задачу', blocked: 'Задаче нужен доступ или лимит' };

export function CloudTaskBar({ task }: { task: CloudTask }) {
  const client = useQueryClient();
  const [steering, setSteering] = useState(false);
  const [text, setText] = useState('');
  const [notice, setNotice] = useState('');
  const control = useMutation({ mutationFn: ({ action, data }: { action: string; data?: unknown }) => apiFetch(`/computer/tasks/${task.id}/${action}`, { method: 'POST', ...(data ? { body: JSON.stringify(data) } : {}) }),
    onSuccess: (_, args) => { client.invalidateQueries({ queryKey: ['computer-tasks'] }); if (args.action === 'steer') { setSteering(false); setText(''); setNotice('Уточнение сохранено. Будет учтено на следующем шаге, уже выполняющийся вызов завершится как обычно.'); } }, });
  if (!labels[task.status]) return null;
  const active = task.status === 'running' || task.status === 'queued';
  const progress = task.status === 'running' ? activitySummary(task.progress) : null;
  return <Box component="section" aria-label="Фоновая задача" sx={{ mb: 1, p: 1.25, maxHeight: '25dvh', overflowY: 'auto', border: '1px solid var(--bt-hairline)', borderRadius: '12px', bgcolor: 'var(--bt-panel)' }}>
    <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{labels[task.status]}</Typography>
    {progress && <Box role="status" sx={{ mt: .5 }}><Typography sx={{ fontSize: 13 }}>{progress.title}</Typography>{progress.detail && <Typography sx={{ fontSize: 12, color: 'text.secondary', overflowWrap: 'anywhere' }}>{progress.detail}</Typography>}</Box>}
    <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: .5 }}>{active ? 'Можно закрыть вкладку и вернуться позже.' : task.error || 'Можно продолжить с сохранённого состояния. Неподтверждённые внешние действия автоматически не повторяются.'}</Typography>
    <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: .75 }}>
      <Button size="small" disabled={control.isPending} onClick={() => control.mutate({ action: active ? 'pause' : 'resume' })}>{active ? 'Приостановить' : 'Продолжить задачу'}</Button>
      <Button size="small" color="inherit" disabled={control.isPending} onClick={() => setSteering(value => !value)}>Добавить уточнение</Button>
    </Stack>
    {steering && <Stack gap={1} sx={{ mt: 1 }}><TextField fullWidth multiline minRows={2} label="Уточнение к задаче" value={text} inputProps={{ maxLength: 2000 }} disabled={control.isPending} onChange={e => setText(e.target.value)} /><Button size="small" disabled={!text.trim() || control.isPending} onClick={() => control.mutate({ action: 'steer', data: { text } })}>Передать уточнение</Button></Stack>}
    {notice && <Typography role="status" sx={{ mt: 1, color: 'text.secondary', fontSize: 12 }}>{notice}</Typography>}
    {control.error && <Alert severity="error" sx={{ mt: 1 }}>{control.error.message}</Alert>}
  </Box>;
}
