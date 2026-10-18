import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Box, Button, IconButton, Menu, MenuItem, Skeleton, Stack, TextField, Typography } from '@mui/material';
import { ArrowLeft, ArrowsIn, ArrowsOut, Check, DownloadSimple, FileText, FolderSimple, Plus, Table, Presentation, Trash, X } from '@phosphor-icons/react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { apiBlob, apiFetch, apiFormData, downloadBlob } from '@/api/client';
import ReactMarkdown from 'react-markdown';
import { ProjectActions, type ProjectDeleted } from './ProjectActions';
import { ResultTable } from './ResultTable';

export type ProjectItem = { id: string; name: string; chat_ids?: string[] };
type Entry = { id: string; title: string; kind: string; revision: number; body?: string; updated_at?: number; chars?: number; has_original?: boolean };
type Row = { id: string; cells: Record<string, string>; state: string };
type Spec = { type: 'table' | 'report' | 'slides'; title: string; text?: string; columns?: { id: string; label: string }[]; rows?: Row[]; slides?: { id: string; title: string; text: string }[]; workflow?: string };
export type ProjectSpace = { project: ProjectItem; entries: Entry[]; chats: { id: string; title: string }[] };
type Detail = Entry & { body: string; spec?: Spec; source_url?: string; current_revision?: number };
const tabs = ['Материалы', 'Результаты', 'Память'] as const;
const readable = (body: string) => body.replace(/^Из сообщения пользователя в беседе [\w-]{1,64}:\n/, 'Из вашего сообщения:\n');

export function ProjectWorkspace({ projectId: pid, conversationId: cid, onClose, onCreated, onSelectChat, externalError, expanded, onToggleSize, onProjectDeleted }: {
  projectId: string; conversationId?: string; onClose: () => void; onCreated: (project: ProjectItem) => void; onSelectChat: (id: string) => void; externalError?: string; expanded?: boolean; onToggleSize?: () => void; onProjectDeleted?: ProjectDeleted;
}) {
  const client = useQueryClient(); const reduce = useReducedMotion();
  const [tab, setTab] = useState(0); const [selected, setSelected] = useState<string | null>(null);
  const [name, setName] = useState(''); const [filter, setFilter] = useState(''); const [error, setError] = useState('');
  const [editing, setEditing] = useState(false); const [title, setTitle] = useState(''); const [body, setBody] = useState('');
  const [draft, setDraft] = useState<Spec | null>(null); const [revision, setRevision] = useState<number | null>(null);
  const [editingRow, setEditingRow] = useState<string | null>(null);
  const [editRevision, setEditRevision] = useState<number | null>(null);
  const [menu, setMenu] = useState<HTMLElement | null>(null); const [deletePending, setDeletePending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null); const [busy, setBusy] = useState(false);
  const space = useQuery<ProjectSpace>({ queryKey: ['project-workspace', pid], queryFn: () => apiFetch(`/projects/${pid}/workspace`), enabled: !!pid, refetchInterval: 10000 });
  const suggestions = useQuery<Entry[]>({ queryKey: ['project-suggestions', pid], queryFn: () => apiFetch(`/projects/${pid}/suggestions`), enabled: !!pid, refetchInterval: 10000 });
  const detail = useQuery<Detail>({ queryKey: ['project-workspace-detail', pid, selected, revision], queryFn: () => apiFetch(`/projects/${pid}/entries/${selected}${revision ? `/versions/${revision}` : ''}`), enabled: !!pid && !!selected });
  const history = useQuery<{ revision: number; title: string }[]>({ queryKey: ['project-history', pid, selected], queryFn: () => apiFetch(`/projects/${pid}/entries/${selected}/history`), enabled: !!selected });
  const refresh = () => { ['project-workspace', 'project-workspace-detail', 'project-entries', 'project-suggestions', 'project-history'].forEach(key => client.invalidateQueries({ queryKey: [key] })); };
  const action = useMutation({ mutationFn: ({ path, method = 'POST', data }: { path: string; method?: string; data?: unknown }) => apiFetch(path, { method, ...(data ? { body: JSON.stringify(data) } : {}) }), onSuccess: () => { setError(''); refresh(); }, onError: (e: Error) => setError(e.message) });
  useEffect(() => { setSelected(null); setEditing(false); setDraft(null); setRevision(null); setError(''); setDeletePending(false); }, [pid]);
  useEffect(() => { setEditing(false); setDraft(null); setRevision(null); setDeletePending(false); }, [selected]);
  const spec: Spec | null = draft || (() => { try { return detail.data?.kind === 'result' ? JSON.parse(detail.data.body) : null; } catch { return null; } })();
  const entries = (space.data?.entries || []).filter(e => (tab === 0 ? e.kind === 'file' || e.kind === 'source' : tab === 1 ? e.kind === 'result' : ['note', 'decision'].includes(e.kind)) && e.title.toLocaleLowerCase('ru').includes(filter.toLocaleLowerCase('ru')));
  const save = async () => {
    if (!detail.data || !selected) return;
    await action.mutateAsync({ path: detail.data.kind === 'result' ? `/projects/${pid}/results/${selected}` : `/projects/${pid}/entries/${selected}`, method: 'PUT', data: detail.data.kind === 'result' ? { spec, expected_revision: editRevision } : { title, body, kind: detail.data.kind === 'suggestion' ? 'decision' : detail.data.kind, source_url: detail.data.source_url || '', expected_revision: editRevision } });
    setEditing(false); setDraft(null);
  };
  const newResult = async (type: Spec['type']) => {
    setMenu(null);
    const spec: Spec = type === 'table' ? { type, title: 'Новая таблица', columns: [{ id: 'item', label: 'Позиция' }, { id: 'value', label: 'Значение' }], rows: [{ id: crypto.randomUUID(), cells: { item: '', value: '' }, state: 'pending' }] } : type === 'report' ? { type, title: 'Новый отчёт', text: '' } : { type, title: 'Новая презентация', slides: [{ id: crypto.randomUUID(), title: 'Первый слайд', text: '' }] };
    const result = await action.mutateAsync({ path: `/projects/${pid}/results`, data: { spec } }) as Entry;
    setTab(1); setSelected(result.id);
  };
  const upload = async (file: File) => {
    if (!cid) { setError('Сначала откройте беседу проекта.'); return; }
    setBusy(true); setError('');
    try {
      const data = new FormData(); data.append('file', file); data.append('conversation_id', cid);
      await apiFormData('/documents/upload', data);
      const docs = await apiFetch(`/projects/chat/${encodeURIComponent(cid)}/documents`) as { id: number; filename: string }[];
      const matched = docs.filter(item => item.filename === file.name || item.filename.startsWith(file.name + '/'));
      if (!matched.length) throw new Error('Файл загружен в беседу, но текст пока не готов. Сохраните его в проект после обработки.');
      let first = '';
      for (const doc of matched.slice(0, 200)) {
        const entry = await action.mutateAsync({ path: `/projects/${pid}/documents`, data: { conversation_id: cid, document_id: doc.id } }) as Entry;
        first ||= entry.id;
      }
      setTab(0); setSelected(first); client.invalidateQueries({ queryKey: ['messages', cid] });
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const download = async () => {
    if (!spec || !selected) return;
    setBusy(true); try { const format = spec.type === 'table' ? 'xlsx' : spec.type === 'report' ? 'docx' : 'pptx'; downloadBlob(await apiBlob(`/projects/${pid}/results/${selected}/export/${format}`), `${spec.title}.${format}`); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const beginEdit = (rowId: string | null = null) => { if (!detail.data) return; setEditingRow(rowId); setEditRevision(detail.data.revision); setTitle(detail.data.title); setBody(detail.data.body); if (spec) setDraft(structuredClone(spec)); setEditing(true); };
  return <Box component="section" aria-label="Рабочая область проекта" sx={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', bgcolor: 'var(--bt-bg)', minWidth: 0 }}>
    <Stack direction="row" alignItems="center" gap={1.5} sx={{ px: { xs: 2, md: 3 }, py: 2, borderBottom: '1px solid var(--bt-hairline)' }}>
      <FolderSimple size={22} style={{ flexShrink: 0 }} />
      <Box sx={{ flex: 1, minWidth: 0 }}><Typography component="h2" sx={{ m: 0, fontSize: 18, fontWeight: 600, overflowWrap: 'anywhere' }}>{space.data?.project.name || (pid ? 'Проект' : 'Новый проект')}</Typography><Typography sx={{ color: 'text.secondary', fontSize: 12 }}>{pid ? 'Материалы и результаты ваших задач' : 'Отдельное место для одной большой задачи'}</Typography></Box>
      {pid && space.data?.project && <ProjectActions project={space.data.project} onDeleted={onProjectDeleted || (() => onClose())} />}
      {onToggleSize && <IconButton aria-label={expanded ? 'Вернуться к двум колонкам' : 'Развернуть материалы'} onClick={onToggleSize}>{expanded ? <ArrowsIn size={19} /> : <ArrowsOut size={19} />}</IconButton>}
      <IconButton aria-label="Вернуться к беседе" onClick={onClose}><X size={20} /></IconButton>
    </Stack>
    {!pid ? <Stack gap={2} sx={{ p: 3, my: 'auto', maxWidth: 440, alignSelf: 'center', width: '100%' }}><Typography sx={{ fontSize: 24, fontWeight: 600 }}>С чего начнём?</Typography><Typography color="text.secondary">Объедините беседы, документы и готовые результаты. Например, закупку компонентов или материалы заказчика.</Typography><TextField autoFocus label="Название проекта" value={name} onChange={e => setName(e.target.value)} inputProps={{ maxLength: 160 }} onKeyDown={e => { if (e.key === 'Enter' && name.trim() && !action.isPending) void action.mutateAsync({ path: '/projects', data: { name: name.trim() } }).then(result => onCreated(result as ProjectItem)).catch(() => {}); }} /><Button variant="contained" disabled={!name.trim() || action.isPending} onClick={() => { void action.mutateAsync({ path: '/projects', data: { name: name.trim() } }).then(result => onCreated(result as ProjectItem)).catch(() => {}); }}>Создать проект</Button>{error && <Alert severity="error">{error}</Alert>}</Stack> : <>
      <Box sx={{ px: { xs: 2, md: 3 }, pt: 1.5, display: 'flex', gap: 2, borderBottom: '1px solid var(--bt-hairline)' }} role="tablist" aria-label="Разделы проекта">
        {tabs.map((label, index) => <Box component="button" role="tab" type="button" aria-selected={tab === index} tabIndex={tab === index ? 0 : -1} key={label} onClick={() => { setTab(index); setSelected(null); }} onKeyDown={e => { if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? 2 : (index + (e.key === 'ArrowRight' ? 1 : 2)) % 3; setTab(next); setSelected(null); (e.currentTarget.parentElement?.querySelectorAll('[role=tab]')[next] as HTMLElement)?.focus(); } }} sx={{ position: 'relative', border: 0, bgcolor: 'transparent', color: tab === index ? 'text.primary' : 'text.secondary', font: 'inherit', fontSize: 13, fontWeight: 600, py: 1.5, px: 0.25, cursor: 'pointer', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main' } }}>{label}{index === 2 && !!suggestions.data?.length ? ` · ${suggestions.data.length}` : ''}{tab === index && <Box component={motion.span} layoutId="project-tab-line" transition={{ duration: reduce ? 0 : .2 }} sx={{ position: 'absolute', left: 0, right: 0, bottom: -1, height: 2, bgcolor: 'primary.main' }} />}</Box>)}
      </Box>
      {(error || externalError || space.error || detail.error || suggestions.error) && <Alert severity="error" sx={{ mx: 2, mt: 1 }}>{error || externalError || space.error?.message || detail.error?.message || suggestions.error?.message}</Alert>}
      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', px: { xs: 2, md: 3 }, py: 2 }}>
        <AnimatePresence mode="wait" initial={false}><Box component={motion.div} key={selected || `tab-${tab}`} initial={{ opacity: 0, y: reduce ? 0 : 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : .18 }}>
          {selected ? <>
            <Button size="small" color="inherit" startIcon={<ArrowLeft size={16} />} onClick={() => setSelected(null)}>Все {tabs[tab].toLowerCase()}</Button>
            {detail.isLoading && <Skeleton height={120} />}
            {detail.data && <>
              <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap" sx={{ my: 2 }}><Typography sx={{ flex: 1, minWidth: 120, fontSize: 20, fontWeight: 600, overflowWrap: 'anywhere' }}>{detail.data.title}</Typography><Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Версия {detail.data.revision}</Typography></Stack>
              <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mb: 2 }}>
                {!editing ? <Button size="small" onClick={() => beginEdit()} disabled={!!revision}>{detail.data.kind === 'file' ? 'Править текст материала' : 'Редактировать'}</Button> : <><Button startIcon={<Check size={16} />} size="small" disabled={action.isPending} onClick={() => { void save().catch(() => {}); }}>Сохранить</Button><Button size="small" color="inherit" disabled={action.isPending} onClick={() => { setDraft(null); setEditing(false); setError(''); }}>Отмена</Button></>}
                {spec && <Button size="small" startIcon={<DownloadSimple size={16} />} disabled={busy || editing || !!revision} onClick={() => { void download(); }}>Скачать {spec.type === 'table' ? 'XLSX' : spec.type === 'report' ? 'DOCX' : 'PPTX'}</Button>}
                {space.data?.entries.find(e => e.id === selected)?.has_original && <Button size="small" startIcon={<DownloadSimple size={16} />} disabled={busy} onClick={() => { setBusy(true); void apiBlob(`/projects/${pid}/entries/${selected}/original`).then(blob => downloadBlob(blob, detail.data!.title.split('/')[0])).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>Скачать оригинал</Button>}
                <IconButton size="small" aria-label="Удалить материал" disabled={action.isPending} onClick={() => setDeletePending(true)}><Trash size={16} /></IconButton>
              </Stack>
              {deletePending && <Alert severity="warning" sx={{ mb: 2 }} action={<Stack direction="row"><Button size="small" disabled={action.isPending} onClick={() => { void action.mutateAsync({ path: `/projects/${pid}/entries/${selected}`, method: 'DELETE' }).then(() => setSelected(null)).catch(() => {}); }}>Удалить</Button><Button size="small" color="inherit" onClick={() => setDeletePending(false)}>Отмена</Button></Stack>}>Удалить материал и его историю из проекта?</Alert>}
              {!editing && !!history.data?.length && history.data.length > 1 && <TextField select size="small" label="История" value={revision || ''} onChange={e => setRevision(e.target.value ? Number(e.target.value) : null)} sx={{ minWidth: 200, mb: 2 }}><MenuItem value="">Текущая версия</MenuItem>{history.data.map(item => <MenuItem value={item.revision} key={item.revision}>Версия {item.revision}</MenuItem>)}</TextField>}
              {revision && revision !== detail.data.current_revision && <Button size="small" disabled={action.isPending} onClick={() => { void action.mutateAsync({ path: `/projects/${pid}/entries/${selected}/restore`, data: { revision, expected_revision: detail.data!.current_revision } }).then(() => setRevision(null)).catch(() => {}); }}>Восстановить эту версию</Button>}
              {editing && <TextField fullWidth size="small" label="Название" value={spec ? spec.title : title} onChange={e => spec ? setDraft({ ...spec, title: e.target.value }) : setTitle(e.target.value)} sx={{ mb: 2 }} />}
              {editing && detail.data.kind === 'file' && <Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 2 }}>Правки применяются к извлечённому тексту проекта. Для изменения самого файла скачайте оригинал.</Typography>}
              {spec?.type === 'table' && <ResultTable key={selected || 'table'} title={spec.title} headers={(spec.columns || []).map(c => c.label)} editable={editing}
                onEditRow={!editing && !revision ? id => beginEdit(id) : undefined}
                rows={(spec.rows || []).map(row => ({ id: row.id, text: (spec.columns || []).map(c => row.cells[c.id] || ''), cells: (spec.columns || []).map(c => editing && (!editingRow || editingRow === row.id)
                  ? <TextField key={c.id} multiline variant="standard" fullWidth disabled={action.isPending} inputProps={{ 'aria-label': `${c.label}, строка ${row.id}`, maxLength: 1500 }} value={row.cells[c.id] || ''} onChange={e => setDraft({ ...spec, rows: spec.rows!.map(r => r.id === row.id ? { ...r, state: 'pending', cells: { ...r.cells, [c.id]: e.target.value } } : r) })} />
                  : /^https?:\/\//i.test(row.cells[c.id] || '') ? <Box key={c.id} component="a" href={row.cells[c.id]} target="_blank" rel="noreferrer" sx={{ color: 'primary.light' }}>Открыть источник</Box> : <ReactMarkdown key={c.id} skipHtml allowedElements={['p','a','strong','em','code','br']} unwrapDisallowed components={{ p: ({children}) => <Box component="span">{children}</Box>, a: ({href,children}) => <Box component="a" href={href} target="_blank" rel="noreferrer" sx={{ color: 'primary.light' }}>{children}</Box> }}>{row.cells[c.id] || '—'}</ReactMarkdown>) }))} />}
              {editing && editingRow && <Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>Редактируется одна строка. Остальные строки сохранятся без изменений.</Typography>}
              {spec?.workflow === 'procurement' && <Typography sx={{ color: 'text.secondary', fontSize: 12, mt: 1.5 }}>План закупки · пустые поля означают, что данные ещё не получены. Цены и наличие проверяются на указанную дату. Корзины и оплата не выполняются.</Typography>}
              {spec?.type === 'table' && editing && !editingRow && <Button sx={{ mt: 1 }} size="small" startIcon={<Plus size={15} />} onClick={() => setDraft({ ...spec, rows: [...spec.rows!, { id: crypto.randomUUID(), cells: {}, state: 'pending' }] })}>Добавить строку</Button>}
              {spec?.type === 'slides' && <Stack gap={2}>{spec.slides?.map((slide, index) => <Box key={slide.id} sx={{ p: 2.5, border: '1px solid var(--bt-hairline)', borderRadius: 2 }}><Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>Слайд {index + 1}</Typography>{editing ? <><TextField fullWidth label="Заголовок слайда" value={slide.title} onChange={e => setDraft({ ...spec, slides: spec.slides!.map(s => s.id === slide.id ? { ...s, title: e.target.value } : s) })} /><TextField fullWidth multiline minRows={3} sx={{ mt: 1 }} label="Текст слайда" value={slide.text} onChange={e => setDraft({ ...spec, slides: spec.slides!.map(s => s.id === slide.id ? { ...s, text: e.target.value } : s) })} /></> : <><Typography sx={{ fontSize: 22, fontWeight: 600 }}>{slide.title}</Typography><Typography sx={{ mt: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{slide.text}</Typography></>}</Box>)}</Stack>}
              {(!spec || spec.type === 'report') && (editing ? <TextField fullWidth multiline minRows={10} maxRows={24} label={spec ? 'Текст отчёта' : 'Текст материала'} value={spec ? spec.text : body} onChange={e => spec ? setDraft({ ...spec, text: e.target.value }) : setBody(e.target.value)} /> : <Typography sx={{ fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{readable(spec?.text || detail.data.body)}</Typography>)}
            </>}
          </> : <>
            <Typography sx={{ color: 'text.secondary', fontSize: 13, lineHeight: 1.6, mb: 2 }}>{tab === 0 ? 'Загрузите документы: их содержимое будет доступно в беседах проекта.' : tab === 1 ? 'Здесь хранятся готовые таблицы, отчёты и презентации. Их можно править и скачивать.' : 'Сохраните общие требования и решения. Они учитываются в беседах проекта; предложения из переписки требуют вашего подтверждения.'}</Typography>
            <Stack direction="row" gap={1} alignItems="center" sx={{ mb: 2 }}><TextField size="small" fullWidth placeholder={`Найти ${tabs[tab].toLowerCase()}`} value={filter} onChange={e => setFilter(e.target.value)} /><Button size="small" startIcon={<Plus size={16} />} disabled={busy || action.isPending} onClick={e => tab === 0 ? fileRef.current?.click() : setMenu(e.currentTarget)} sx={{ flexShrink: 0 }}>{busy ? 'Загружаю…' : 'Добавить'}</Button></Stack>
            {tab === 2 && suggestions.data?.map(item => <Box key={item.id} sx={{ py: 2, borderBottom: '1px solid var(--bt-hairline)' }}><Typography sx={{ fontSize: 12, color: 'primary.light', mb: 1 }}>Предложение из беседы</Typography><Typography sx={{ fontSize: 14, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{readable(item.body || '')}</Typography><Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 1 }}><Button size="small" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/${pid}/suggestions/${item.id}`, data: { accept: true, expected_revision: item.revision } })}>Сохранить</Button><Button color="inherit" size="small" disabled={action.isPending} onClick={() => setSelected(item.id)}>Изменить</Button><Button color="inherit" size="small" disabled={action.isPending} onClick={() => action.mutate({ path: `/projects/${pid}/suggestions/${item.id}`, data: { accept: false, expected_revision: item.revision } })}>Не сохранять</Button></Stack></Box>)}
            {space.isLoading && <><Skeleton height={58} /><Skeleton height={58} /></>}
            {!space.isLoading && !entries.length && <Stack alignItems="flex-start" gap={1.5} sx={{ py: 5 }}><FolderSimple size={32} /><Typography sx={{ fontSize: 22, fontWeight: 600 }}>{filter ? 'Совпадений нет' : tab === 0 ? 'Всё нужное — в одном месте' : tab === 1 ? 'Здесь появятся готовые результаты' : 'Контекст для следующих задач'}</Typography><Typography sx={{ color: 'text.secondary', fontSize: 14, lineHeight: 1.7 }}>{filter ? 'Попробуйте другое название.' : tab === 0 ? 'Добавьте документы проекта. Они останутся доступны в его беседах.' : tab === 1 ? 'Попросите Оркестратор сохранить таблицу, отчёт или презентацию. Или создайте результат вручную.' : 'Попросите запомнить требование в беседе или добавьте заметку.'}</Typography></Stack>}
            {entries.map(item => <Box component="button" type="button" key={item.id} onClick={() => setSelected(item.id)} sx={{ display: 'flex', width: '100%', gap: 1.5, alignItems: 'center', py: 2, px: 0.5, border: 0, borderBottom: '1px solid var(--bt-hairline)', bgcolor: 'transparent', color: 'text.primary', textAlign: 'left', cursor: 'pointer', '&:hover': { bgcolor: 'var(--bt-overlay-faint)' }, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main' } }}><FileText size={22} style={{ flexShrink: 0 }} /><Box sx={{ minWidth: 0, flex: 1 }}><Typography sx={{ fontSize: 14, fontWeight: 600, overflowWrap: 'anywhere' }}>{item.title}</Typography><Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.4 }}>{item.kind === 'result' ? 'Редактируемый результат' : item.kind === 'file' ? 'Документ' : item.kind === 'decision' ? 'Принятое решение' : 'Материал'} · версия {item.revision}</Typography></Box></Box>)}
            {!!space.data?.chats.length && <Box sx={{ mt: 4 }}><Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>Беседы проекта</Typography>{space.data.chats.map(chat => <Button key={chat.id} color="inherit" size="small" sx={{ justifyContent: 'flex-start', textAlign: 'left', display: 'flex', width: '100%' }} onClick={() => onSelectChat(chat.id)}>{chat.title}</Button>)}</Box>}
          </>}
        </Box></AnimatePresence>
      </Box>
    </>}
    <input hidden ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.zip" onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} />
    <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>{tab === 1 ? [<MenuItem key="table" onClick={() => { void newResult('table').catch(() => {}); }}><Table size={17} style={{ marginRight: 10 }} />Таблица</MenuItem>,<MenuItem key="report" onClick={() => { void newResult('report').catch(() => {}); }}><FileText size={17} style={{ marginRight: 10 }} />Отчёт</MenuItem>,<MenuItem key="slides" onClick={() => { void newResult('slides').catch(() => {}); }}><Presentation size={17} style={{ marginRight: 10 }} />Презентация</MenuItem>] : <MenuItem onClick={() => { setMenu(null); void action.mutateAsync({ path: `/projects/${pid}/entries`, data: { title: 'Новая заметка', body: 'Запишите требования проекта.', kind: 'note' } }).then(item => setSelected((item as Entry).id)).catch(() => {}); }}>Заметка</MenuItem>}</Menu>
  </Box>;
}
