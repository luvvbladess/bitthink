import { useId, useLayoutEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Collapse, IconButton, MenuItem, Skeleton, Stack, Switch, TextField, Typography } from '@mui/material';
import { useReducedMotion } from 'framer-motion';
import { ArrowLeft, CaretRight, Clock, Folder, Plugs, PuzzlePiece, SlidersHorizontal, X } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { apiFetch, apiFormData } from '@/api/client';
import { MCPSection } from '@/features/settings/MCPSection';
import { GoogleSection } from '@/features/settings/GoogleSection';
import { ComputerRulesSection } from '@/features/settings/ComputerRulesSection';
import { ProjectMemorySection } from './ProjectMemorySection';

type Task = { id: string; title: string; prompt: string; status: string; enabled: boolean; progress: string; error: string; next_run_at: number; conversation_id: string | null };
type Skill = { name: string; title: string; description: string; origin: string; enabled: boolean };
type SkillTemplate = { name: string; title: string; description: string };
type Section = 'home' | 'tasks' | 'skills' | 'connectors' | 'rules' | 'projects';
const titles = { home: 'Оркестратор', tasks: 'Задачи', skills: 'Навыки', connectors: 'Подключения', rules: 'Правила', projects: 'Память проекта' };
const statusLabels: Record<string, string> = { queued: 'В очереди', running: 'В работе', scheduled: 'По расписанию', completed: 'Готово', paused: 'На паузе', cancelled: 'Отменено', interrupted: 'Прервано', failed: 'Ошибка', blocked: 'Нужен доступ или лимит' };
const date = (value: number) => new Date(value * 1000).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

/** One contextual entry point, beside the composer. No second application shell. */
export function OrchestratorTools({ draft, hasFiles = false, conversationId, onOpenProjects }: { draft: string; hasFiles?: boolean; conversationId?: string | null; onOpenProjects?: () => void }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>('home');
  const [creating, setCreating] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [interval, setInterval] = useState(0);
  const [start, setStart] = useState('');
  const [error, setError] = useState('');
  const [showBuiltins, setShowBuiltins] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [skillSearch, setSkillSearch] = useState('');
  const [showGoogle, setShowGoogle] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const enrollment = useRef({ payload: '', key: '' });
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const reduceMotion = useReducedMotion();
  const [panelHeight, setPanelHeight] = useState(360);
  const close = () => { setOpen(false); triggerRef.current?.focus({ preventScroll: true }); };
  useLayoutEffect(() => {
    if (!open) return;
    const composer = rootRef.current?.parentElement?.querySelector('form');
    const measure = () => {
      const viewport = window.visualViewport?.height || window.innerHeight;
      setPanelHeight(Math.max(96, Math.min(360, viewport - (composer?.getBoundingClientRect().height || 120) - 240)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (composer) observer.observe(composer);
    window.addEventListener('resize', measure);
    window.visualViewport?.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); window.visualViewport?.removeEventListener('resize', measure); };
  }, [open]);
  const tasks = useQuery<Task[]>({ queryKey: ['computer-tasks'], queryFn: () => apiFetch('/computer/tasks'), refetchInterval: 15000 });
  const skills = useQuery<{ items: Skill[] }>({ queryKey: ['skills'], queryFn: () => apiFetch('/skills'), enabled: open, staleTime: 30000 });
  const templates = useQuery<{ items: SkillTemplate[] }>({ queryKey: ['skill-templates'], queryFn: () => apiFetch('/skills/templates'), enabled: open && section === 'skills' && showTemplates, staleTime: 30000 });
  const connectors = useQuery<{ id: number; type: string }[]>({ queryKey: ['connectors'], queryFn: () => apiFetch('/connectors'), enabled: open, staleTime: 30000 });
  const active = (tasks.data || []).filter(t => t.enabled).length;
  const create = useMutation({
    mutationFn: () => {
      const data = { prompt, interval_seconds: interval, start_at: start ? Math.floor(new Date(start).getTime() / 1000) : 0 };
      const payload = JSON.stringify(data);
      if (enrollment.current.payload !== payload) enrollment.current = { payload, key: crypto.randomUUID() };
      return apiFetch('/computer/tasks', { method: 'POST', body: JSON.stringify({ ...data, idempotency_key: enrollment.current.key }) });
    },
    onSuccess: () => { setCreating(false); setError(''); client.invalidateQueries({ queryKey: ['computer-tasks'] }); },
    onError: (e: Error) => setError(e.message),
  });
  const control = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => apiFetch(`/computer/tasks/${id}/${action}`, { method: 'POST' }),
    onSuccess: () => { setError(''); client.invalidateQueries({ queryKey: ['computer-tasks'] }); }, onError: (e: Error) => setError(e.message),
  });
  const toggleSkill = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => apiFetch(`/skills/${name}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
    onMutate: async ({ name, enabled }) => {
      await client.cancelQueries({ queryKey: ['skills'] });
      const previous = client.getQueryData<{ items: Skill[] }>(['skills']);
      if (previous) client.setQueryData(['skills'], { ...previous, items: previous.items.map(skill => skill.name === name ? { ...skill, enabled } : skill) });
      return { previous };
    },
    onError: (e: Error, _, context) => { if (context?.previous) client.setQueryData(['skills'], context.previous); setError(e.message); },
    onSettled: () => client.invalidateQueries({ queryKey: ['skills'] }),
  });
  const upload = useMutation({
    mutationFn: (file: File) => { const form = new FormData(); form.append('file', file); return apiFormData('/skills/import', form); },
    onSuccess: () => { setError(''); client.invalidateQueries({ queryKey: ['skills'] }); }, onError: (e: Error) => setError(e.message),
  });
  const addTemplate = useMutation({
    mutationFn: (name: string) => apiFetch(`/skills/templates/${encodeURIComponent(name)}`, { method: 'POST' }),
    onSuccess: () => { setError(''); client.invalidateQueries({ queryKey: ['skills'] }); },
    onError: (e: Error) => setError(e.message),
  });
  const addTask = () => { enrollment.current = { payload: '', key: '' }; setPrompt(draft); setInterval(0); setStart(''); setError(''); setCreating(true); };
  const custom = (skills.data?.items || []).filter(s => s.origin === 'custom');
  const builtin = (skills.data?.items || []).filter(s => s.origin !== 'custom');
  const matchesSkill = (skill: Skill) => `${skill.title} ${skill.name} ${skill.description}`.toLocaleLowerCase('ru-RU').includes(skillSearch.trim().toLocaleLowerCase('ru-RU'));
  const rowSx = { display: 'flex', width: '100%', gap: 1.5, alignItems: 'center', p: 1.5, textAlign: 'left', bgcolor: 'transparent', color: 'text.primary', border: 0, borderRadius: '10px', font: 'inherit', cursor: 'pointer', '&:hover': { bgcolor: 'var(--bt-overlay)' }, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 } };
  const skillRow = (skill: Skill) => <Stack key={skill.name} direction="row" alignItems="center" gap={2} sx={{ py: 1.25, borderBottom: '1px solid var(--bt-hairline)' }}>
    <Box sx={{ minWidth: 0, flex: 1 }}><Typography sx={{ fontSize: 14, fontWeight: 600 }}>{skill.title || skill.name}</Typography><Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25, overflowWrap: 'anywhere' }}>{skill.description}</Typography></Box>
    <Switch size="small" checked={skill.enabled} disabled={toggleSkill.isPending} onChange={(_, enabled) => toggleSkill.mutate({ name: skill.name, enabled })} inputProps={{ 'aria-label': `Навык ${skill.title || skill.name}` }} />
  </Stack>;
  return <Box ref={rootRef} sx={{ mt: 0.5, width: '100%' }} onKeyDown={e => { if (open && e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); close(); } }}>
    <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1} sx={{ px: 0.5 }}>
    <Typography sx={{ fontSize: 12, color: 'text.secondary', display: { xs: 'none', sm: 'block' } }}>Делегирует задачи и собирает результат</Typography>
    <Button ref={triggerRef} type="button" size="small" onClick={() => { if (open) close(); else { setOpen(true); setSection('home'); setError(''); } }} aria-label="Задачи и инструменты Оркестратора" aria-controls={open ? panelId : undefined} aria-expanded={open}
      startIcon={<SlidersHorizontal size={15} />} sx={{ minHeight: { xs: 44, sm: 36 }, px: 1.25, borderRadius: '999px', color: open ? 'primary.light' : 'text.secondary', fontSize: 12, whiteSpace: 'nowrap', '&:hover': { bgcolor: 'var(--bt-overlay)', color: 'text.primary' } }}>
      Задачи и инструменты{active > 0 && <Box component="span" sx={{ ml: 0.75, px: 0.75, borderRadius: '999px', bgcolor: 'var(--bt-glow)', color: 'primary.light', fontVariantNumeric: 'tabular-nums' }}>{active}</Box>}
    </Button>
    </Stack>
    <Collapse in={open} timeout={reduceMotion ? 0 : 180} unmountOnExit>
    <Box id={panelId} role="region" aria-label="Инструменты Оркестратора" sx={{ mt: 0.75, width: '100%', borderRadius: '14px', bgcolor: 'var(--bt-panel)', border: '1px solid var(--bt-line)', overflow: 'hidden' }}>
      <Stack direction="row" alignItems="center" gap={1} sx={{ px: 2, py: 1.25, position: 'sticky', top: 0, zIndex: 1, bgcolor: 'var(--bt-panel)', borderBottom: section === 'home' ? 0 : '1px solid var(--bt-hairline)' }}>
        {section !== 'home' && <IconButton size="small" aria-label="Назад к инструментам" onClick={() => { setSection('home'); setError(''); }}><ArrowLeft size={18} /></IconButton>}
        <Typography sx={{ fontSize: 15, fontWeight: 600, flex: 1 }}>{titles[section]}</Typography>
        <IconButton size="small" aria-label="Закрыть инструменты" onClick={close} sx={{ minWidth: 36, minHeight: 36 }}><X size={18} /></IconButton>
      </Stack>
      <Box sx={{ px: 2, pb: 2, maxHeight: panelHeight - 54, overflowY: 'auto', overscrollBehavior: 'contain', scrollbarGutter: 'stable' }}>
        {error && <Alert severity="error" sx={{ my: 1 }}>{error}</Alert>}
        {section === 'home' && <>
          {([
            ['tasks', Clock, 'Задачи', active ? `Активных задач: ${active} · работа по расписанию` : 'Поручения на потом и по расписанию'],
            ['projects', Folder, 'Память проекта', 'Требования, решения и документы между беседами'],
            ['skills', PuzzlePiece, 'Навыки', custom.length ? `Личные: ${custom.length} · встроенные: ${builtin.length}` : 'Инструкции под ваши задачи'],
            ['connectors', Plugs, 'Подключения', connectors.data?.length ? `${connectors.data.length} подключено` : 'Почта, файлы и внешние инструменты'],
          ] as const).map(([id, Icon, title, hint]) => <Box component="button" type="button" key={id} onClick={() => { if (id === 'projects' && onOpenProjects) { close(); onOpenProjects(); } else { setSection(id); setCreating(false); } }} sx={rowSx}>
            <Icon size={21} style={{ flexShrink: 0 }} /><Box sx={{ flex: 1, minWidth: 0 }}><Typography sx={{ fontSize: 14, fontWeight: 600 }}>{title}</Typography><Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25 }}>{hint}</Typography></Box><CaretRight size={15} />
          </Box>)}
          <Button size="small" onClick={() => setSection('rules')} sx={{ mt: 1, color: 'text.secondary', fontSize: 12 }}>Дополнительные правила</Button>
        </>}
        {section === 'tasks' && <>
          <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1} sx={{ mt: 1, mb: 2 }}><Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Работают после закрытия чата; при сбое сохраняют шаги</Typography><Button size="small" onClick={addTask} disabled={create.isPending}>Новая задача</Button></Stack>
          <Collapse in={creating} unmountOnExit>
            <Stack spacing={1.5} sx={{ mb: 2 }}>
              <TextField label="Что сделать?" value={prompt} onChange={e => setPrompt(e.target.value)} multiline minRows={2} size="small" inputProps={{ maxLength: 50000 }} />
              {hasFiles && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Файлы из поля сообщения не прикрепляются к задаче. Добавьте нужные ссылки в текст.</Typography>}
              <Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5}>
                <TextField size="small" select label="Повторять" fullWidth value={interval} onChange={e => setInterval(Number(e.target.value))}><MenuItem value={0}>Один раз</MenuItem><MenuItem value={3600}>Каждый час</MenuItem><MenuItem value={86400}>Каждый день</MenuItem><MenuItem value={604800}>Каждую неделю</MenuItem></TextField>
                <TextField size="small" label="Начать" type="datetime-local" fullWidth value={start} onChange={e => setStart(e.target.value)} InputLabelProps={{ shrink: true }} />
              </Stack>
              <Stack direction="row" gap={1}><Button variant="contained" disabled={create.isPending || !prompt.trim()} onClick={() => create.mutate()}>{create.isPending ? 'Создаю…' : start ? 'Запланировать' : 'Запустить'}</Button><Button disabled={create.isPending} onClick={() => setCreating(false)}>Отмена</Button></Stack>
            </Stack>
          </Collapse>
          {tasks.isLoading && <Skeleton height={68} />}
          {tasks.error && <Alert severity="error">{tasks.error.message}</Alert>}
          {!tasks.isLoading && !tasks.data?.length && !creating && <Typography sx={{ fontSize: 14, color: 'text.secondary', py: 2 }}>Попросите следить за ценой или готовить отчёт — один раз или регулярно.</Typography>}
          {(tasks.data || []).map(task => <Box key={task.id} sx={{ py: 1.5, borderTop: '1px solid var(--bt-hairline)' }}>
            <Stack direction="row" gap={1} alignItems="flex-start"><Typography sx={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600, overflowWrap: 'anywhere' }}>{task.title}</Typography><Typography sx={{ fontSize: 11, color: task.status === 'running' ? 'primary.light' : 'text.secondary', whiteSpace: 'nowrap' }}>{statusLabels[task.status] || task.status}</Typography></Stack>
            {task.status === 'scheduled' && <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.5 }}>{date(task.next_run_at)}</Typography>}
            {task.status === 'running' && task.progress && <Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.5, whiteSpace: 'pre-wrap' }}>{task.progress}</Typography>}
            {task.error && <Typography sx={{ fontSize: 12, color: 'error.main', mt: 0.5 }}>{task.error}</Typography>}
            <Stack direction="row" gap={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
              {task.conversation_id && <Button component={Link} to={`/chat?c=${encodeURIComponent(task.conversation_id)}`} size="small" onClick={close}>Результат</Button>}
              <Button size="small" disabled={control.isPending} onClick={() => control.mutate({ id: task.id, action: task.enabled ? 'pause' : 'resume' })}>{task.enabled ? 'Пауза' : task.status === 'completed' ? 'Повторить' : 'Продолжить'}</Button>
              {task.enabled && <Button size="small" color="inherit" disabled={control.isPending} onClick={() => control.mutate({ id: task.id, action: 'cancel' })}>Отменить</Button>}
            </Stack>
          </Box>)}
        </>}
        {section === 'projects' && <ProjectMemorySection key={conversationId || 'new'} conversationId={conversationId} />}
        {section === 'skills' && <>
          <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1} sx={{ mt: 1, mb: 1 }}><Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Применяются по задаче</Typography><Button size="small" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>{upload.isPending ? 'Загружаю…' : 'Добавить навык'}</Button></Stack>
          <input ref={fileRef} hidden type="file" accept=".md,.zip" onChange={e => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ''; }} />
          {skills.isLoading && <Skeleton height={68} />}
          {skills.error && <Alert severity="error">{skills.error.message}</Alert>}
          {custom.map(skillRow)}
          {!custom.length && <Typography sx={{ fontSize: 14, color: 'text.secondary', py: 2 }}>Добавьте свои инструкции в SKILL.md или ZIP. Встроенные навыки уже доступны.</Typography>}
          <Button size="small" sx={{ color: 'text.secondary', mt: 1 }} onClick={() => setShowBuiltins(value => !value)} aria-expanded={showBuiltins}>{showBuiltins ? 'Скрыть встроенные' : `Встроенные навыки · ${builtin.length}`}</Button>
          <Collapse in={showBuiltins} unmountOnExit>
            <TextField size="small" fullWidth label="Найти встроенный навык" value={skillSearch} onChange={e => setSkillSearch(e.target.value)} sx={{ mt: 1.5, mb: 1 }} />
            {builtin.filter(matchesSkill).map(skillRow)}
            {builtin.length > 0 && !builtin.some(matchesSkill) && <Typography sx={{ fontSize: 13, color: 'text.secondary', py: 1 }}>По этому запросу навыков нет.</Typography>}
          </Collapse>
          <Box><Button size="small" sx={{ color: 'text.secondary', mt: 1 }} onClick={() => setShowTemplates(value => !value)} aria-expanded={showTemplates}>{showTemplates ? 'Скрыть шаблоны' : 'Готовые шаблоны для личных навыков'}</Button></Box>
          <Collapse in={showTemplates} unmountOnExit>
            <Typography sx={{ fontSize: 12, color: 'text.secondary', my: 1 }}>Добавьте подходящие правила. До добавления они не влияют на ответы.</Typography>
            {templates.isLoading && <Skeleton height={68} />}
            {templates.error && <Alert severity="error">{templates.error.message}</Alert>}
            {(templates.data?.items || []).map(template => {
              const installed = custom.some(skill => skill.name === template.name);
              return <Stack key={template.name} direction="row" alignItems="center" gap={1.5} sx={{ py: 1.25, borderBottom: '1px solid var(--bt-hairline)' }}>
                <Box sx={{ minWidth: 0, flex: 1 }}><Typography sx={{ fontSize: 14, fontWeight: 600, overflowWrap: 'anywhere' }}>{template.title}</Typography><Typography sx={{ fontSize: 12, color: 'text.secondary', mt: 0.25 }}>{template.description}</Typography></Box>
                <Button size="small" disabled={installed || addTemplate.isPending} onClick={() => addTemplate.mutate(template.name)} sx={{ flexShrink: 0 }}>{installed ? 'Добавлен' : 'Добавить'}</Button>
              </Stack>;
            })}
          </Collapse>
        </>}
        {section === 'connectors' && <Stack spacing={2} sx={{ pt: 1 }}>
          <Box><Button size="small" onClick={() => setShowGoogle(value => !value)} aria-expanded={showGoogle}>Google · почта, Диск и календарь</Button><Collapse in={showGoogle} unmountOnExit><Box sx={{ pt: 1 }}><GoogleSection /></Box></Collapse></Box>
          <MCPSection compact />
        </Stack>}
        {section === 'rules' && <Box sx={{ pt: 2 }}><ComputerRulesSection /></Box>}
      </Box>
    </Box>
    </Collapse>
  </Box>;
}
