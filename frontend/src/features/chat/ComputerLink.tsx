import { useState } from 'react';
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';
import { useAuthStore } from '@/stores/authStore';

export type ComputerSession = {
  id: string;
  title: string;
  project_id: string;
  project_name: string;
  status: 'idle' | 'running' | 'needs_approval' | 'offline';
  updated_at: number;
  pending_approval: { tool_id: string; name: string; summary: string } | null;
};

export type ComputerLinkView = {
  online: boolean;
  device_name: string;
  client_version: string;
  approval_mode: string;
  projects: { id: string; name: string }[];
  sessions: ComputerSession[];
};

type ComputerDetail = ComputerSession & {
  online: boolean;
  messages: { id: string; role: 'user' | 'assistant'; content: string; error: string; tools: { name: string; status: string }[] }[];
};

const STATUS: Record<string, string> = { idle: 'Ожидает', running: 'Выполняется', needs_approval: 'Нужно подтверждение', offline: 'Компьютер не в сети' };
const MODE: Record<string, string> = { ask: 'Спрашивает подтверждение', auto: 'Выполняет действия сам', readonly: 'Только чтение' };
const TOOL: Record<string, string> = { pending: 'ждёт', running: 'выполняется', needs_approval: 'ждёт подтверждение', done: 'готово', error: 'ошибка', denied: 'отклонено' };
const NAMES: Record<string, string> = { desktop_run_command: 'Команда', python_run: 'Python', pip_install: 'Пакет Python', workspace_write: 'Запись файла', workspace_edit: 'Правка файла', workspace_delete: 'Удаление файла', workspace_read: 'Чтение файла', desktop_control: 'Управление компьютером', desktop_browser_action: 'Браузер' };

export function useComputerLink(open: boolean, active: boolean) {
  const account = useAuthStore(state => state.user?.email || state.user?.id || '');
  return useQuery<ComputerLinkView>({
    queryKey: ['desktop-link', account],
    queryFn: () => apiFetch('/desktop/link'),
    enabled: open && Boolean(account),
    refetchInterval: open ? (active ? 2000 : 8000) : false,
  });
}

export function ComputerLink() {
  const account = useAuthStore(state => state.user?.email || state.user?.id || '');
  return <ComputerLinkSession key={account} account={account}/>;
}

function ComputerLinkSession({ account }: { account: string }) {
  const client = useQueryClient();
  const link = useComputerLink(true, true);
  const [selectedId, setSelectedId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [text, setText] = useState('');
  const [reply, setReply] = useState('');
  const [error, setError] = useState('');
  const detail = useQuery<ComputerDetail>({
    queryKey: ['desktop-link-session', account, selectedId],
    queryFn: () => apiFetch(`/desktop/link/sessions/${encodeURIComponent(selectedId)}`),
    enabled: Boolean(account && selectedId),
    refetchInterval: selectedId ? 1500 : false,
  });
  const refresh = (id = selectedId) => {
    void client.invalidateQueries({ queryKey: ['desktop-link'] });
    if (id) void client.invalidateQueries({ queryKey: ['desktop-link-session', id] });
  };
  const fail = (reason: Error) => setError(reason.message);
  const create = useMutation({
    mutationFn: async (id: string) => {
      const result = await apiFetch('/desktop/link/sessions', { method: 'POST', body: JSON.stringify({ content: text.trim(), project_id: id }), timeoutMs: 25000 }) as { session_id?: string };
      const sessionId = result?.session_id;
      if (!sessionId) throw new Error('Bit Client не начал задачу.');
      return { session_id: sessionId };
    },
    onSuccess: (result) => { setText(''); setError(''); setSelectedId(result.session_id); refresh(result.session_id); },
    onError: fail,
  });
  const message = useMutation({
    mutationFn: () => apiFetch(`/desktop/link/sessions/${encodeURIComponent(selectedId)}/message`, { method: 'POST', body: JSON.stringify({ content: reply.trim() }), timeoutMs: 25000 }),
    onSuccess: () => { setReply(''); setError(''); refresh(); },
    onError: fail,
  });
  const stop = useMutation({
    mutationFn: (id: string) => apiFetch(`/desktop/link/sessions/${encodeURIComponent(id)}/stop`, { method: 'POST', timeoutMs: 25000 }),
    onSuccess: () => { setError(''); refresh(); },
    onError: fail,
  });
  const approval = useMutation({
    mutationFn: ({ id, toolId, allow }: { id: string; toolId: string; allow: boolean }) => apiFetch(`/desktop/link/sessions/${encodeURIComponent(id)}/approval`, { method: 'POST', body: JSON.stringify({ tool_id: toolId, allow }), timeoutMs: 25000 }),
    onSuccess: () => { setError(''); refresh(); },
    onError: fail,
  });
  const view = link.data;
  const online = Boolean(view?.online);
  const chosen = projectId || view?.projects[0]?.id || '';
  const busy = create.isPending || message.isPending || stop.isPending || approval.isPending;
  const session = detail.data;
  if (link.isLoading) return <Typography sx={{ fontSize: 14, color: 'text.secondary', py: 2 }}>Проверяю компьютер…</Typography>;
  if (link.isError) return <Alert severity="error" sx={{ my: 1 }}>{link.error?.message || 'Не удалось проверить компьютер.'}</Alert>;
  if (!view) return null;
  return <Stack spacing={1.5} sx={{ pt: 1 }}>
    {error && <Alert severity="error">{error}</Alert>}
    <Box>
      <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{online ? (view.device_name || 'Компьютер') : 'Компьютер не в сети'}</Typography>
      <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25 }}>{online ? MODE[view.approval_mode] || 'Спрашивает подтверждение' : view.sessions.length ? 'Последние задачи показаны на момент отключения. Пока Bit Client закрыт, они не продолжаются.' : 'Откройте Bit Client на этом аккаунте и войдите. Пока приложение закрыто, задачи на компьютере не продолжаются.'}</Typography>
    </Box>
    {selectedId ? <>
      <Button size="small" onClick={() => { setSelectedId(''); setReply(''); setError(''); }} sx={{ alignSelf: 'flex-start', color: 'text.secondary' }}>К списку</Button>
      {detail.isLoading && <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>Открываю задачу…</Typography>}
      {detail.isError && <Alert severity="error">{detail.error?.message || 'Задача на компьютере не найдена.'}</Alert>}
      {session && <Stack spacing={1.25}>
        <Box>
          <Typography sx={{ fontSize: 15, fontWeight: 600, overflowWrap: 'anywhere' }}>{session.title}</Typography>
          <Typography sx={{ fontSize: 12, color: session.status === 'running' || session.status === 'needs_approval' ? 'primary.light' : 'text.secondary', mt: 0.25 }}>{[session.project_name, STATUS[session.status] || session.status].filter(Boolean).join(' · ')}</Typography>
        </Box>
        <Stack spacing={1} sx={{ maxHeight: 220, overflowY: 'auto' }}>
          {!session.messages.length && <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>Пока нет сообщений.</Typography>}
          {session.messages.map((item, index) => <Box key={item.id || `${item.role}-${index}`} sx={{ py: 0.75, borderTop: '1px solid var(--bt-hairline)' }}>
            <Typography sx={{ fontSize: 11, color: 'text.secondary' }}>{item.role === 'user' ? 'Вы' : 'Оркестратор'}</Typography>
            {item.content && <Typography sx={{ fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{item.content}</Typography>}
            {item.error && <Typography sx={{ fontSize: 12, color: 'error.main', mt: 0.5 }}>{item.error}</Typography>}
            {!!item.tools?.length && <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.5 }}>{item.tools.map(tool => `${NAMES[tool.name] || 'Действие'} · ${TOOL[tool.status] || tool.status}`).join(', ')}</Typography>}
          </Box>)}
        </Stack>
        {session.pending_approval && session.status === 'needs_approval' && <Box sx={{ p: 1.25, borderRadius: '10px', bgcolor: 'var(--bt-overlay)' }}>
          <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{session.pending_approval.summary || 'Нужно подтверждение'}</Typography>
          {online && <Stack direction="row" gap={1} sx={{ mt: 1 }}>
            <Button size="small" variant="contained" disabled={busy} onClick={() => approval.mutate({ id: session.id, toolId: session.pending_approval!.tool_id, allow: true })}>Разрешить</Button>
            <Button size="small" color="inherit" disabled={busy} onClick={() => approval.mutate({ id: session.id, toolId: session.pending_approval!.tool_id, allow: false })}>Отклонить</Button>
          </Stack>}
        </Box>}
        {online && (session.status === 'running' || session.status === 'needs_approval') && <Button size="small" color="inherit" disabled={busy} onClick={() => stop.mutate(session.id)} sx={{ alignSelf: 'flex-start' }}>Остановить</Button>}
        <TextField size="small" label="Сообщение на компьютер" value={reply} onChange={event => setReply(event.target.value)} multiline minRows={2} disabled={!online || busy} inputProps={{ maxLength: 20000 }} />
        <Button variant="contained" disabled={!online || busy || !reply.trim()} onClick={() => message.mutate()} sx={{ alignSelf: 'flex-start' }}>{message.isPending ? 'Отправляю…' : 'Отправить'}</Button>
      </Stack>}
    </> : <>
      {online && !!view.projects.length && <Stack spacing={1.25}>
        <TextField size="small" select label="Проект" value={chosen} onChange={event => setProjectId(event.target.value)}>
          {view.projects.map(project => <MenuItem key={project.id} value={project.id}>{project.name}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Новая задача" value={text} onChange={event => setText(event.target.value)} multiline minRows={2} disabled={busy} inputProps={{ maxLength: 20000 }} />
        <Button variant="contained" disabled={busy || !text.trim() || !chosen} onClick={() => create.mutate(chosen)} sx={{ alignSelf: 'flex-start' }}>{create.isPending ? 'Отправляю…' : 'Запустить на компьютере'}</Button>
      </Stack>}
      {online && !view.projects.length && <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>В Bit Client пока нет проекта. Откройте папку в приложении — тогда задачу можно запустить отсюда.</Typography>}
      {!view.sessions.length && online && <Typography sx={{ fontSize: 14, color: 'text.secondary' }}>На компьютере ещё нет задач Оркестратора.</Typography>}
      {view.sessions.map(item => <Box key={item.id} sx={{ py: 1.25, borderTop: '1px solid var(--bt-hairline)' }}>
        <Stack direction="row" gap={1} alignItems="flex-start">
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography sx={{ fontSize: 14, fontWeight: 600, overflowWrap: 'anywhere' }}>{item.title}</Typography>
            <Typography sx={{ fontSize: 12, color: item.status === 'running' || item.status === 'needs_approval' ? 'primary.light' : 'text.secondary', mt: 0.25 }}>{[item.project_name, STATUS[item.status] || item.status].filter(Boolean).join(' · ')}</Typography>
            {item.pending_approval && <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.5 }}>{item.pending_approval.summary}</Typography>}
          </Box>
          <Button size="small" aria-label={`Открыть ${item.title}`} onClick={() => { setError(''); setSelectedId(item.id); }}>Открыть</Button>
        </Stack>
        {online && item.status === 'needs_approval' && item.pending_approval && <Stack direction="row" gap={1} sx={{ mt: 1 }}>
          <Button size="small" variant="contained" disabled={busy} onClick={() => approval.mutate({ id: item.id, toolId: item.pending_approval!.tool_id, allow: true })}>Разрешить</Button>
          <Button size="small" color="inherit" disabled={busy} onClick={() => approval.mutate({ id: item.id, toolId: item.pending_approval!.tool_id, allow: false })}>Отклонить</Button>
        </Stack>}
        {online && (item.status === 'running' || item.status === 'needs_approval') && <Button size="small" color="inherit" disabled={busy} onClick={() => stop.mutate(item.id)} sx={{ mt: 0.5 }}>Остановить</Button>}
      </Box>)}
    </>}
  </Stack>;
}
