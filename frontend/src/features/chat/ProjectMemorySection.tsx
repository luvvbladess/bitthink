import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Box, Button, Collapse, MenuItem, Skeleton, Stack, TextField, Typography } from '@mui/material';
import { apiFetch } from '@/api/client';

type Project = { id: string; name: string };
type Entry = { id: string; title: string; body: string; kind: string; source_url: string; revision: number; current_revision?: number; chars?: number };
type Revision = { revision: number; title: string; created_at: number };

function memoryText(body: string) {
  return body.replace(/^Из сообщения пользователя в беседе [\w-]{1,64}:\n/, 'Из вашего сообщения:\n');
}

function EntryDetails({ pid, entry, onEdit }: { pid: string; entry: Entry; onEdit: (entry: Entry) => void }) {
  const client = useQueryClient();
  const [number, setNumber] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState('');
  const base = `/projects/${pid}/entries/${entry.id}`;
  const detail = useQuery<Entry>({ queryKey: ['project-entry', pid, entry.id, number], queryFn: () => apiFetch(number === null ? base : `${base}/versions/${number}`) });
  const history = useQuery<Revision[]>({ queryKey: ['project-history', pid, entry.id], queryFn: () => apiFetch(`${base}/history`), enabled: showHistory });
  const restore = useMutation({
    mutationFn: () => apiFetch(`${base}/restore`, { method: 'POST', body: JSON.stringify({ revision: number, expected_revision: detail.data?.current_revision }) }),
    onSuccess: () => { setNumber(null); setError(''); client.invalidateQueries({ queryKey: ['project-entry', pid, entry.id] }); client.invalidateQueries({ queryKey: ['project-history', pid, entry.id] }); client.invalidateQueries({ queryKey: ['project-entries', pid] }); },
    onError: (e: Error) => setError(e.message),
  });
  const data = detail.data;
  const download = () => {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([data.body], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `${data.title.replace(/[\\/:*?"<>|]/g, '_')}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <Stack gap={1} sx={{ pt: 1 }}>
    {(error || detail.error || history.error) && <Alert severity="error">{error || detail.error?.message || history.error?.message}</Alert>}
    {detail.isLoading && <Skeleton height={64} />}
    {data && <>
      <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Версия {data.revision} · {data.chars?.toLocaleString('ru-RU')} символов</Typography>
      {data.source_url && <Typography component="a" href={data.source_url} target="_blank" rel="noreferrer" sx={{ fontSize: 13, overflowWrap: 'anywhere', color: 'primary.light' }}>Открыть источник</Typography>}
      <Typography sx={{ fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: 'text.secondary', maxHeight: 320, overflowY: 'auto' }} tabIndex={0}>{memoryText(data.body).slice(0, 20000)}</Typography>
      {data.body.length > 20000 && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Показаны первые 20 000 символов. В поиске участвует весь документ; полный текст можно скачать.</Typography>}
      <Stack direction="row" gap={1} flexWrap="wrap">
        <Button size="small" disabled={detail.isFetching || restore.isPending || number !== null} onClick={() => onEdit(data)}>Редактировать</Button>
        <Button size="small" color="inherit" onClick={download}>Скачать текст</Button>
        <Button size="small" color="inherit" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>История изменений</Button>
      </Stack>
      {showHistory && <>
        {history.isLoading ? <Skeleton height={40} /> : <TextField size="small" select label="Версия материала" value={number ?? ''} disabled={restore.isPending} onChange={e => setNumber(e.target.value ? Number(e.target.value) : null)}>
          <MenuItem value="">Текущая версия</MenuItem>{(history.data || []).map(r => <MenuItem key={r.revision} value={r.revision}>Версия {r.revision} · {new Date(r.created_at * 1000).toLocaleString('ru-RU')}</MenuItem>)}
        </TextField>}
        {number !== null && number !== data.current_revision && <Button size="small" disabled={restore.isPending || detail.isFetching} onClick={() => restore.mutate()}>Восстановить эту версию</Button>}
      </>}
    </>}
  </Stack>;
}

export function ProjectMemorySection({ conversationId: cid }: { conversationId?: string | null }) {
  const client = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState('note');
  const [source, setSource] = useState('');
  const [editing, setEditing] = useState<Entry | null>(null);
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const projects = useQuery<Project[]>({ queryKey: ['projects'], queryFn: () => apiFetch('/projects') });
  const binding = useQuery<{ project_id: string | null }>({ queryKey: ['project-chat', cid], queryFn: () => apiFetch(`/projects/chat/${encodeURIComponent(cid!)}`), enabled: !!cid });
  const pid = selected ?? binding.data?.project_id ?? '';
  const resetEditor = () => { setAdding(false); setEditing(null); setTitle(''); setBody(''); setKind('note'); setSource(''); setError(''); };
  useEffect(() => { setSelected(null); setExpanded(null); setSearch(''); setQuery(''); resetEditor(); }, [cid]);
  const entries = useQuery<Entry[]>({ queryKey: ['project-entries', pid, search], queryFn: () => apiFetch(`/projects/${pid}/entries?q=${encodeURIComponent(search)}`), enabled: !!pid });
  const suggestions = useQuery<Entry[]>({ queryKey: ['project-suggestions', pid], queryFn: () => apiFetch(`/projects/${pid}/suggestions`), enabled: !!pid, refetchInterval: 10000 });
  const docs = useQuery<{ id: number; filename: string }[]>({ queryKey: ['project-docs', cid], queryFn: () => apiFetch(`/projects/chat/${encodeURIComponent(cid!)}/documents`), enabled: !!cid && !!pid });
  const action = useMutation({
    mutationFn: ({ path, method = 'POST', data }: { path: string; method?: string; data?: unknown }) => apiFetch(path, { method, ...(data !== undefined ? { body: JSON.stringify(data) } : {}) }),
    onSuccess: () => { setError(''); client.invalidateQueries({ queryKey: ['projects'] }); client.invalidateQueries({ queryKey: ['project-chat'] }); client.invalidateQueries({ queryKey: ['project-entries'] }); client.invalidateQueries({ queryKey: ['project-entry'] }); client.invalidateQueries({ queryKey: ['project-history'] }); client.invalidateQueries({ queryKey: ['project-suggestions'] }); },
    onError: (e: Error) => setError(e.message),
  });
  const create = async () => {
    const result = await action.mutateAsync({ path: '/projects', data: { name: name.trim() } }) as Project;
    setSelected(result.id); setName('');
  };
  const save = async () => {
    await action.mutateAsync({ path: editing ? `/projects/${pid}/entries/${editing.id}` : `/projects/${pid}/entries`, method: editing ? 'PUT' : 'POST', data: { title: title.trim(), body, kind, source_url: source.trim(), ...(editing ? { expected_revision: editing.revision } : {}) } });
    resetEditor();
  };
  const edit = (entry: Entry) => { setEditing(entry); setAdding(true); setTitle(entry.title); setBody(entry.body); setKind(entry.kind); setSource(entry.source_url || ''); };
  return <Stack gap={1.5} sx={{ pt: 1 }}>
    <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>Требования, решения и документы для следующих задач. Из явных требований в беседе появляются предложения: они станут памятью после сохранения. Доступ есть только у вас.</Typography>
    {(error || projects.error || binding.error || entries.error || docs.error || suggestions.error) && <Alert severity="error">{error || projects.error?.message || binding.error?.message || entries.error?.message || docs.error?.message || suggestions.error?.message}</Alert>}
    {projects.isLoading ? <Skeleton height={48} /> : <TextField select size="small" label="Проект" value={pid} disabled={action.isPending} onChange={e => { setSelected(e.target.value); setSearch(''); setQuery(''); setExpanded(null); resetEditor(); }}>
      <MenuItem value="">Выберите проект</MenuItem>{(projects.data || []).map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
    </TextField>}
    <Stack direction="row" gap={1} alignItems="center"><TextField label="Новый проект" size="small" value={name} onChange={e => setName(e.target.value)} inputProps={{ maxLength: 160 }} sx={{ flex: 1, minWidth: 0 }} /><Button disabled={!name.trim() || action.isPending} onClick={() => { void create().catch(() => {}); }}>Создать</Button></Stack>
    {pid && <>
      {!!suggestions.data?.length && !adding && <Stack gap={1} sx={{ py: 1 }}>
        <Typography sx={{ fontSize: 14, fontWeight: 600 }}>Сохранить из беседы</Typography>
        <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Проверьте формулировку. Отложенные предложения не используются в ответах.</Typography>
        {suggestions.data.map(item => <Box key={item.id} sx={{ borderBottom: '1px solid var(--bt-hairline)', pb: 1 }}>
          <Typography sx={{ fontSize: 13, fontWeight: 600, overflowWrap: 'anywhere' }}>{item.title}</Typography>
          <Typography sx={{ mt: 0.5, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{memoryText(item.body)}</Typography>
          <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
            <Button size="small" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/${pid}/suggestions/${item.id}`, data: { accept: true, expected_revision: item.revision } })}>Сохранить</Button>
            <Button size="small" color="inherit" disabled={action.isPending} onClick={() => edit({ ...item, kind: 'decision', source_url: '' })}>Изменить</Button>
            <Button size="small" color="inherit" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/${pid}/suggestions/${item.id}`, data: { accept: false, expected_revision: item.revision } })}>Не сохранять</Button>
          </Stack>
        </Box>)}
      </Stack>}
      {cid ? <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
        {binding.data?.project_id === pid ? <><Typography sx={{ fontSize: 12, color: 'primary.light' }}>Эта беседа использует память проекта</Typography><Button size="small" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/chat/${encodeURIComponent(cid)}`, method: 'PUT', data: { project_id: null } })}>Отключить</Button></> : <Button size="small" disabled={action.isPending || binding.isLoading || !!binding.error} onClick={() => action.mutate({ path: `/projects/chat/${encodeURIComponent(cid)}`, method: 'PUT', data: { project_id: pid } })}>Использовать в этой беседе</Button>}
      </Stack> : <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Отправьте первое сообщение, затем подключите проект к беседе.</Typography>}
      <Stack direction="row" gap={1} alignItems="center"><TextField label="Поиск по памяти" size="small" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); setSearch(query); } }} inputProps={{ maxLength: 500 }} sx={{ flex: 1, minWidth: 0 }} /><Button size="small" onClick={() => setSearch(query)}>Найти</Button></Stack>
      <Button size="small" sx={{ alignSelf: 'flex-start' }} disabled={action.isPending} onClick={() => { resetEditor(); setAdding(true); }}>Добавить материал</Button>
      <Collapse in={adding}><Stack gap={1} sx={{ pt: 0.5 }}>
        <Typography sx={{ fontSize: 14, fontWeight: 600 }}>{editing ? 'Редактирование материала' : 'Новый материал'}</Typography>
        <TextField size="small" label="Название материала" value={title} onChange={e => setTitle(e.target.value)} inputProps={{ maxLength: 255 }} />
        <TextField size="small" select label="Тип материала" value={kind} disabled={editing?.kind === 'file'} onChange={e => setKind(e.target.value)}><MenuItem value="note">Требования и заметки</MenuItem><MenuItem value="decision">Принятое решение</MenuItem><MenuItem value="source">Источник</MenuItem>{kind === 'file' && <MenuItem value="file">Документ</MenuItem>}</TextField>
        <TextField size="small" multiline minRows={3} maxRows={8} label="Текст материала" value={body} onChange={e => setBody(e.target.value)} inputProps={{ maxLength: kind === 'file' ? 2000000 : 60000 }} />
        <TextField size="small" label="Ссылка на источник (необязательно)" value={source} onChange={e => setSource(e.target.value)} inputProps={{ maxLength: 2048 }} />
        <Stack direction="row" gap={1}><Button disabled={!title.trim() || !body.trim() || action.isPending} onClick={() => { void save().catch(() => {}); }}>Сохранить</Button><Button color="inherit" disabled={action.isPending} onClick={resetEditor}>Отмена</Button></Stack>
        {editing?.kind === 'file' && !!docs.data?.length && <TextField size="small" select label="Заменить документом из беседы" value="" disabled={action.isPending} onChange={e => { void action.mutateAsync({ path: `/projects/${pid}/documents`, data: { conversation_id: cid, document_id: Number(e.target.value), entry_id: editing.id, expected_revision: editing.revision } }).then(resetEditor).catch(() => {}); }}><MenuItem value="">Выберите документ</MenuItem>{docs.data.map(d => <MenuItem key={d.id} value={d.id}>{d.filename}</MenuItem>)}</TextField>}
      </Stack></Collapse>
      {!!docs.data?.length && <TextField size="small" select label="Сохранить документ из этой беседы" value="" onChange={e => action.mutate({ path: `/projects/${pid}/documents`, data: { conversation_id: cid, document_id: Number(e.target.value) } })} disabled={action.isPending}><MenuItem value="">Выберите документ</MenuItem>{docs.data.map(d => <MenuItem value={d.id} key={d.id}>{d.filename}</MenuItem>)}</TextField>}
      {entries.isLoading && <Skeleton height={48} />}
      {!entries.isLoading && !entries.data?.length && <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>{search ? 'Совпадений нет. Попробуйте другое слово.' : 'Память пока пуста. Добавьте важные требования или документ.'}</Typography>}
      {(entries.data || []).map(e => <Box key={e.id} sx={{ borderTop: '1px solid var(--bt-hairline)', py: 1 }}>
        <Stack direction="row" gap={1} alignItems="center"><Button color="inherit" sx={{ flex: 1, minWidth: 0, justifyContent: 'flex-start', textAlign: 'left', overflowWrap: 'anywhere' }} aria-expanded={expanded === e.id} onClick={() => setExpanded(expanded === e.id ? null : e.id)}>{e.title}</Button><Button size="small" color="inherit" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/${pid}/entries/${e.id}`, method: 'DELETE' })}>Удалить</Button></Stack>
        {search && <Typography sx={{ fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: 'text.secondary' }}>{e.body.slice(0, 350)}</Typography>}
        <Collapse in={expanded === e.id} unmountOnExit>{expanded === e.id && <EntryDetails pid={pid} entry={e} onEdit={edit} />}</Collapse>
      </Box>)}
    </>}
  </Stack>;
}
