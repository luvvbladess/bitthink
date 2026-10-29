import { Fragment, useMemo, useRef, useState } from 'react';
import {
  Alert, Box, Button, Collapse, Dialog, DialogActions, DialogContent,
  DialogContentText, DialogTitle, Divider, IconButton, ListItemButton,
  ListItemIcon, Menu, MenuItem, TextField, Tooltip, Typography,
} from '@mui/material';
import type { ToolsMode } from './ConversationTools';
import { ListChecks } from '@phosphor-icons/react';
import { ArrowLeft, Check, CaretRight, DotsThree, FolderSimple, MagnifyingGlass, PencilSimple, Plus, Trash, Users, X } from '@phosphor-icons/react';
import { useReducedMotion } from 'framer-motion';
import { BrandLink } from '@/components/BrandMark';
import { AccountMenu } from '@/components/AccountMenu';
import { ProjectActions, type ProjectDeleted } from './ProjectActions';

export interface ConversationItem {
  id: string;
  title: string;
  message_count: number;
  is_active: boolean;
  shared?: boolean;
  role?: 'owner' | 'member';
  updated_at?: string;
  created_at?: string;
}

interface Props {
  hasMore?: boolean; loadingMore?: boolean; onLoadMore?: () => void;
  onTools?: (mode: ToolsMode, query?: string) => void;
  conversations: ConversationItem[];
  activeId?: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => Promise<unknown>;
  onClose?: () => void;
  onLibrary?: () => void;
  generatingIds?: string[];
  projects?: { id: string; name: string; chat_ids?: string[] }[];
  onMoveChat?: (id: string, projectId: string | null) => Promise<void>;
  activeProjectId?: string | null;
  onProject?: (id: string) => void;
  onCreateProject?: () => void;
  onCreateInProject?: (pid: string) => Promise<void>;
  onProjectDeleted?: ProjectDeleted;
}

const finePointer = '@media (min-width: 900px) and (hover: hover) and (pointer: fine)';
const actionSx = {
  width: { xs: 40, md: 32 }, height: { xs: 40, md: 32 }, flexShrink: 0,
  borderRadius: '8px', color: 'text.secondary',
  '@media (pointer: coarse)': { width: 44, height: 44 },
  '&:hover': { bgcolor: 'var(--bt-overlay)', color: 'text.primary' },
  '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
} as const;
const rowSx = {
  display: 'flex', alignItems: 'center', minWidth: 0, minHeight: { xs: 44, md: 40 },
  borderRadius: '8px', position: 'relative', transition: 'background-color 120ms ease-out',
  '&:hover, &:focus-within': { bgcolor: 'var(--bt-overlay-faint)' },
  [finePointer]: {
    '& .sidebar-row-action': { opacity: 0 },
    '&:hover .sidebar-row-action, &:focus-within .sidebar-row-action, & .sidebar-row-action[data-open="true"]': { opacity: 1 },
  },
} as const;
const sectionSx = { px: 1, fontSize: '0.75rem', fontWeight: 500, color: 'text.muted', lineHeight: 1.5 } as const;

function timeValue(iso?: string): number {
  const value = iso ? Date.parse(iso) : Number.NaN;
  return Number.isNaN(value) ? 0 : value;
}

/** Newest activity first. A brand-new chat shares updated_at with the one it replaced, so creation time breaks the tie. */
export function compareConversations(a: ConversationItem, b: ConversationItem): number {
  return timeValue(b.updated_at) - timeValue(a.updated_at)
    || timeValue(b.created_at) - timeValue(a.created_at)
    || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0);
}

function dateGroup(iso?: string): string {
  const then = iso ? new Date(iso) : null;
  if (!then || Number.isNaN(then.getTime())) return 'Недавние';
  const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((dayStart(new Date()) - dayStart(then)) / 86_400_000);
  if (days <= 0) return 'Сегодня';
  if (days === 1) return 'Вчера';
  if (days < 7) return 'На этой неделе';
  if (days < 30) return 'В этом месяце';
  return 'Раньше';
}

export function ChatSidebar({ hasMore, loadingMore, onLoadMore, onTools, conversations, activeId, onSelect, onCreate, onDelete, onRename, onClose, onLibrary, generatingIds = [], projects = [], activeProjectId, onProject, onCreateProject, onMoveChat, onCreateInProject, onProjectDeleted }: Props) {
  const reduce = useReducedMotion();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [dragTarget, setDragTarget] = useState<string | null>(null);
  const [moveError, setMoveError] = useState('');
  const [moveBusy, setMoveBusy] = useState(false);
  const [moveMenu, setMoveMenu] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState('');
  const editPending = useRef(false);
  const [confirmDelete, setConfirmDelete] = useState<ConversationItem | null>(null);
  const [search, setSearch] = useState('');
  const [rowMenu, setRowMenu] = useState<{ el: HTMLElement; conv: ConversationItem } | null>(null);
  const renameInput = useRef<HTMLInputElement>(null);
  const rowActions = useRef(new Map<string, HTMLButtonElement>());
  const membership = useMemo(() => new Map(projects.flatMap(p => (p.chat_ids || []).map(id => [id, p.id] as const))), [projects]);
  const searching = Boolean(search.trim());
  const filtered = conversations.filter(c => searching
    ? c.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) : !membership.has(c.id));
  const ordered = [...filtered].sort(compareConversations);

  const move = async (id: string, pid: string | null) => {
    if (!onMoveChat || moveBusy || conversations.find(c => c.id === id)?.shared) return;
    setMoveBusy(true); setMoveError('');
    try { await onMoveChat(id, pid); if (pid) setExpanded(v => ({ ...v, [pid]: true })); }
    catch { setMoveError('Не удалось перенести беседу. Попробуйте ещё раз через её меню.'); }
    finally { setMoveBusy(false); }
  };
  const dragProps = (conv: ConversationItem) => ({
    draggable: Boolean(onMoveChat && !conv.shared && !moveBusy && editingId !== conv.id),
    onDragStart: (e: React.DragEvent) => { e.dataTransfer.setData('application/x-bitthink-chat', conv.id); e.dataTransfer.effectAllowed = 'move'; },
    onDragEnd: () => setDragTarget(null),
  });
  const dropProps = (pid: string | null) => ({
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes('application/x-bitthink-chat') && !moveBusy) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragTarget(pid || 'unassigned'); } },
    onDragLeave: (e: React.DragEvent) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragTarget(null); },
    onDrop: (e: React.DragEvent) => { e.preventDefault(); setDragTarget(null); const id = e.dataTransfer.getData('application/x-bitthink-chat'); if (conversations.some(c => c.id === id && !c.shared)) void move(id, pid); },
  });
  const startEdit = (conv: ConversationItem) => { if (editPending.current) return; setEditError(''); setEditingId(conv.id); setEditTitle(conv.title); };
  const focusAction = (id: string | null) => { if (id) window.requestAnimationFrame(() => rowActions.current.get(id)?.focus()); };
  const cancelEdit = () => { if (editPending.current) return; setEditError(''); focusAction(editingId); setEditingId(null); };
  const saveEdit = async () => {
    if (!editTitle.trim() || !editingId || editPending.current) return;
    const id = editingId;
    editPending.current = true; setEditBusy(true); setEditError('');
    try {
      await onRename(id, editTitle.trim());
      focusAction(id); setEditingId(null);
    } catch {
      setEditError('Не удалось сохранить название. Проверьте соединение и повторите сохранение.');
    } finally { editPending.current = false; setEditBusy(false); }
  };
  const closeMenu = () => { setRowMenu(null); setMoveMenu(false); };
  const chooseProject = (pid: string | null) => { const id = rowMenu?.conv.id; closeMenu(); if (id) void move(id, pid); };

  // One row and one editing flow for both project conversations and recent chats.
  const renderConversation = (conv: ConversationItem) => {
    const active = conv.id === activeId;
    const working = generatingIds.includes(conv.id);
    const menuOpen = rowMenu?.conv.id === conv.id;
    const projectName = searching ? projects.find(p => p.id === membership.get(conv.id))?.name : undefined;
    return <Box key={conv.id} {...dragProps(conv)} sx={{ ...rowSx, bgcolor: active ? 'var(--bt-overlay)' : 'transparent', '&:hover, &:focus-within': { bgcolor: active ? 'var(--bt-overlay)' : 'var(--bt-overlay-faint)' } }}>
      {editingId === conv.id ? <TextField
        autoFocus inputRef={renameInput} fullWidth size="small" value={editTitle} disabled={editBusy}
        onChange={e => setEditTitle(e.target.value)} inputProps={{ 'aria-label': 'Название беседы', maxLength: 255 }}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); }
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) saveEdit();
          if (e.key === 'Escape') cancelEdit();
        }}
        sx={{ '& .MuiInputBase-root': { px: 0.5, fontSize: '0.875rem', borderRadius: '8px' }, '& input': { px: 0.75, py: 1 } }}
        InputProps={{ endAdornment: <Box sx={{ display: 'flex' }}>
          <IconButton aria-label="Сохранить название" disabled={editBusy || !editTitle.trim()} onClick={() => void saveEdit()} sx={actionSx}><Check size={16} weight="bold" /></IconButton>
          <IconButton aria-label="Отменить редактирование" disabled={editBusy} onClick={cancelEdit} sx={actionSx}><X size={16} weight="bold" /></IconButton>
        </Box> }}
      /> : <>
        <ListItemButton component="button" aria-label={`Открыть беседу ${conv.title}`} aria-current={active ? 'page' : undefined} selected={active} onClick={() => onSelect(conv.id)}
          sx={{ flex: 1, minWidth: 0, minHeight: { xs: 44, md: 40 }, px: 1, py: 0.75, gap: 0.75, borderRadius: '8px', textAlign: 'left', color: active ? 'text.primary' : 'text.secondary', '&.Mui-selected, &.Mui-selected:hover, &:hover': { bgcolor: 'transparent' }, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 } }}>
          {working && <Tooltip title="Готовится ответ"><Box component="span" role="status" aria-label="Готовится ответ" sx={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, bgcolor: 'primary.main' }} /></Tooltip>}
          <Box component="span" sx={{ flex: 1, minWidth: 0 }}>
            <Typography component="span" title={conv.title} sx={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.875rem', fontWeight: active ? 600 : 400, lineHeight: 1.45, color: 'inherit' }}>{conv.title}</Typography>
            {projectName && <Typography component="span" sx={{ display: 'block', fontSize: '0.75rem', color: 'text.muted', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{projectName}</Typography>}
          </Box>
          {conv.shared && <Tooltip title="Общая беседа"><Box component="span" aria-label="Общая беседа" sx={{ display: 'flex', flexShrink: 0, color: 'text.muted' }}><Users size={15} weight="bold" /></Box></Tooltip>}
        </ListItemButton>
        {conv.role !== 'member' && <Tooltip title="Действия с беседой"><IconButton className="sidebar-row-action" data-open={menuOpen || active || undefined}
          ref={node => { if (node) rowActions.current.set(conv.id, node); else rowActions.current.delete(conv.id); }}
          aria-label={`Действия с беседой ${conv.title}`} aria-haspopup="menu" aria-expanded={menuOpen} aria-controls={menuOpen ? 'sidebar-conversation-menu' : undefined}
          onClick={e => { setMoveMenu(false); setRowMenu({ el: e.currentTarget, conv }); }} sx={{ ...actionSx, mr: 0.25 }}><DotsThree size={20} weight="bold" /></IconButton></Tooltip>}
      </>}
    </Box>;
  };

  return <Box component="nav" aria-label="Беседы и проекты" sx={{ height: '100%', display: 'flex', flexDirection: 'column', width: { xs: '100%', md: 280 }, minWidth: 0, overflow: 'hidden', bgcolor: 'var(--bt-sidebar)', borderRight: onClose ? 'none' : '1px solid var(--bt-hairline)' }}>
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 1.75, minHeight: 56, flexShrink: 0 }}>
      <BrandLink variant="sidebar" />
      {onClose && <IconButton onClick={onClose} aria-label="Закрыть меню" sx={actionSx}><X size={20} weight="bold" /></IconButton>}
    </Box>
    <Box sx={{ px: 1.5, pb: 1.25, display: 'flex', flexDirection: 'column', gap: 0.5, flexShrink: 0 }}>
      <Button fullWidth startIcon={<Plus size={18} weight="bold" />} onClick={onCreate}
        sx={{ minHeight: 42, justifyContent: 'flex-start', px: 1.25, borderRadius: '8px', border: '1px solid var(--bt-hairline)', bgcolor: 'var(--bt-overlay-faint)', color: 'text.primary', fontWeight: 500, fontSize: '0.875rem', '&:hover': { bgcolor: 'var(--bt-overlay)' } }}>Новый вопрос</Button>
      {onLibrary && <Button fullWidth startIcon={<FolderSimple size={18} weight="bold" />} onClick={onLibrary}
        sx={{ minHeight: 40, justifyContent: 'flex-start', px: 1.25, borderRadius: '8px', color: 'text.secondary', fontWeight: 400, fontSize: '0.875rem', '&:hover': { bgcolor: 'var(--bt-overlay-faint)', color: 'text.primary' } }}>Библиотека</Button>}
      {onTools && <Box sx={{ display: 'flex', gap: .5 }}><Button color="inherit" startIcon={<ListChecks size={17} />} onClick={() => onTools('tasks')} sx={{ minHeight: 40, flex: 1, justifyContent: 'flex-start', fontSize: 13 }}>Задачи</Button><Button color="inherit" startIcon={<Trash size={17} />} onClick={() => onTools('trash')} sx={{ minHeight: 40, flex: 1, justifyContent: 'flex-start', fontSize: 13 }}>Корзина</Button></Box>}
      <TextField value={search} onChange={e => setSearch(e.target.value)} placeholder="Найти беседу" size="small" fullWidth
        inputProps={{ 'aria-label': 'Найти беседу', autoComplete: 'off' }}
        InputProps={{ startAdornment: <Box sx={{ display: 'flex', mr: 0.75, color: 'text.muted' }}><MagnifyingGlass size={17} weight="bold" /></Box>,
          endAdornment: search ? <IconButton aria-label="Очистить поиск" onClick={() => setSearch('')} sx={{ ...actionSx, width: 32, height: 32 }}><X size={15} weight="bold" /></IconButton> : undefined }}
        sx={{ '& .MuiOutlinedInput-root': { minHeight: 40, px: 1.25, borderRadius: '8px', bgcolor: 'transparent', fontSize: '0.8125rem', '& fieldset': { borderColor: 'transparent' }, '&:hover fieldset': { borderColor: 'var(--bt-hairline)' }, '&.Mui-focused fieldset': { borderColor: 'primary.main' } }, '& input': { py: 1 }, '& input::placeholder': { color: 'text.muted', opacity: 1 } }} />
    </Box>
    {searching && onTools && <Button onClick={() => onTools('search', search)} sx={{ mx: 1, mb: 1, justifyContent: 'flex-start', fontSize: 12 }}>Искать в переписке и файлах</Button>}
    <Box aria-label="Список бесед" sx={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', overscrollBehavior: 'contain', px: 1, pb: 1.5, '&::-webkit-scrollbar': { width: 6 }, '&::-webkit-scrollbar-thumb': { bgcolor: 'var(--bt-overlay-strong)', borderRadius: 6 } }}>
      {onProject && !searching && <Box sx={{ mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pl: 1, mb: 0.25 }}>
          <Typography component="h2" sx={{ ...sectionSx, px: 0 }}>Проекты</Typography>
          {onCreateProject && <Tooltip title="Создать проект"><IconButton aria-label="Создать проект" onClick={onCreateProject} sx={actionSx}><Plus size={16} weight="bold" /></IconButton></Tooltip>}
        </Box>
        {projects.map(project => {
          const chats = conversations.filter(c => !c.shared && membership.get(c.id) === project.id).sort(compareConversations);
          const open = expanded[project.id] ?? activeProjectId === project.id;
          return <Box key={project.id} {...dropProps(project.id)} sx={{ borderRadius: '8px', bgcolor: dragTarget === project.id ? 'var(--bt-overlay-strong)' : 'transparent', outline: dragTarget === project.id ? '1px solid' : 'none', outlineColor: 'primary.main' }}>
            <Box sx={rowSx}>
              <IconButton aria-label={`${open ? 'Свернуть' : 'Показать'} беседы проекта ${project.name}`} aria-expanded={open}
                onClick={() => setExpanded(v => ({ ...v, [project.id]: !open }))} sx={{ ...actionSx, width: { xs: 32, md: 28 } }}>
                <CaretRight size={14} weight="bold" style={{ transform: open ? 'rotate(90deg)' : undefined, transition: reduce ? 'none' : 'transform 150ms ease-out' }} />
              </IconButton>
              <Button onClick={() => { setExpanded(v => ({ ...v, [project.id]: true })); onProject(project.id); }} aria-pressed={activeProjectId === project.id}
                sx={{ flex: 1, minWidth: 0, minHeight: { xs: 44, md: 40 }, justifyContent: 'flex-start', textAlign: 'left', px: 0.25, py: 0.75, gap: 0.5, borderRadius: '8px', color: activeProjectId === project.id ? 'text.primary' : 'text.secondary', fontWeight: 500, fontSize: '0.875rem', '&:hover': { bgcolor: 'transparent', color: 'text.primary' } }}>
                <Box component="span" title={project.name} sx={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.name}</Box>
                {chats.length > 0 && <Box component="span" sx={{ minWidth: 18, fontSize: '0.75rem', color: 'text.muted', fontVariantNumeric: 'tabular-nums', textAlign: 'center' }}>{chats.length}</Box>}
              </Button>
              <ProjectActions compact project={project} onDeleted={onProjectDeleted} />
            </Box>
            <Collapse in={open} timeout={reduce ? 0 : 150}>
              <Box sx={{ ml: 2, pl: 0.5, borderLeft: '1px solid var(--bt-hairline)', mb: 0.5 }}>
                {chats.map(renderConversation)}
                {onCreateInProject && <Button startIcon={<Plus size={14} weight="bold" />} aria-label={`Новая беседа в проекте ${project.name}`} onClick={() => { void onCreateInProject(project.id).catch(() => setMoveError('Не удалось создать беседу в проекте. Попробуйте ещё раз.')); }}
                  sx={{ minHeight: { xs: 44, md: 36 }, px: 1, justifyContent: 'flex-start', color: 'text.muted', fontWeight: 400, fontSize: '0.8125rem', borderRadius: '8px', '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay-faint)' } }}>Новая беседа</Button>}
                {!chats.length && !onCreateInProject && <Typography sx={{ px: 1, py: 1, fontSize: '0.8125rem', color: 'text.muted' }}>Нет бесед</Typography>}
              </Box>
            </Collapse>
          </Box>;
        })}
        {!projects.length && <Typography sx={{ px: 1, py: 0.75, fontSize: '0.8125rem', color: 'text.muted' }}>Проектов пока нет</Typography>}
      </Box>}
      {moveError && <Alert severity="error" closeText="Закрыть" onClose={() => setMoveError('')} sx={{ mb: 1 }} role="alert">{moveError}</Alert>}
      {editError && <Alert severity="error" closeText="Закрыть" onClose={() => setEditError('')} sx={{ mb: 1 }}>{editError}</Alert>}
      <Box {...dropProps(null)} sx={{ minHeight: 44, borderRadius: '8px', bgcolor: dragTarget === 'unassigned' ? 'var(--bt-overlay-strong)' : 'transparent' }}>
        <Typography component="h2" sx={{ ...sectionSx, pt: 0.5, pb: 0.75 }}>{searching ? 'Результаты поиска' : 'Беседы'}</Typography>
        {searching && !ordered.length && <Typography sx={{ px: 1, py: 1, fontSize: '0.8125rem', color: 'text.secondary' }}>Беседа не найдена</Typography>}
        {!conversations.length && !searching && <Typography sx={{ px: 1, py: 0.75, fontSize: '0.8125rem', lineHeight: 1.5, color: 'text.secondary' }}>Здесь появятся ваши беседы.</Typography>}
        {ordered.map((conv, i) => {
          const label = dateGroup(conv.updated_at);
          const showLabel = !searching && Boolean(conv.updated_at) && (i === 0 || label !== dateGroup(ordered[i - 1].updated_at));
          return <Fragment key={conv.id}>
            {showLabel && <Typography sx={{ ...sectionSx, pt: i ? 1.5 : 0.25, pb: 0.5 }}>{label}</Typography>}
            {renderConversation(conv)}
          </Fragment>;
        })}
      </Box>
    </Box>
    <Box sx={{ flexShrink: 0, borderTop: '1px solid var(--bt-hairline)', p: 1, pb: 'max(8px, env(safe-area-inset-bottom))' }}><AccountMenu variant="row" /></Box>
    {hasMore && <Button onClick={onLoadMore} disabled={loadingMore} sx={{ minHeight: 40, mx: 2 }}>{loadingMore ? 'Загружаем…' : 'Показать ещё беседы'}</Button>}
    <Menu id="sidebar-conversation-menu" anchorEl={rowMenu?.el} open={Boolean(rowMenu)} onClose={closeMenu} disableRestoreFocus={Boolean(editingId || confirmDelete)}
      TransitionProps={{ onExited: () => renameInput.current?.focus() }}
      slotProps={{ paper: { sx: { minWidth: 220, maxWidth: 'calc(100vw - 24px)', borderRadius: '12px', '& .MuiMenuItem-root': { minHeight: 44, fontSize: '0.875rem' } } } }}>
      {moveMenu ? [
        <MenuItem key="back" onClick={() => setMoveMenu(false)}><ListItemIcon><ArrowLeft size={18} weight="bold" /></ListItemIcon>Назад</MenuItem>,
        <Divider key="divider" />,
        ...projects.map(p => <MenuItem key={p.id} selected={membership.get(rowMenu?.conv.id || '') === p.id} disabled={moveBusy} onClick={() => chooseProject(p.id)}><ListItemIcon><FolderSimple size={18} weight="bold" /></ListItemIcon><Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</Box></MenuItem>),
        membership.has(rowMenu?.conv.id || '') && <MenuItem key="unassigned" disabled={moveBusy} onClick={() => chooseProject(null)}>Убрать из проекта</MenuItem>,
      ] : [
        <MenuItem key="rename" onClick={() => { const conv = rowMenu?.conv; closeMenu(); if (conv) startEdit(conv); }}><ListItemIcon><PencilSimple size={18} weight="bold" /></ListItemIcon>Переименовать</MenuItem>,
        !rowMenu?.conv.shared && onMoveChat && <MenuItem key="move" disabled={moveBusy || !projects.length} onClick={() => setMoveMenu(true)}><ListItemIcon><FolderSimple size={18} weight="bold" /></ListItemIcon>Переместить в проект…</MenuItem>,
        !rowMenu?.conv.shared && membership.has(rowMenu?.conv.id || '') && <MenuItem key="remove" disabled={moveBusy} onClick={() => chooseProject(null)}>Убрать из проекта</MenuItem>,
        <Divider key="divider" />,
        <MenuItem key="delete" sx={{ color: 'var(--bt-danger)' }} onClick={() => { const conv = rowMenu?.conv; closeMenu(); if (conv) setConfirmDelete(conv); }}><ListItemIcon sx={{ color: 'inherit' }}><Trash size={18} weight="bold" /></ListItemIcon>Удалить</MenuItem>,
      ]}
    </Menu>
    <Dialog open={!!confirmDelete} onClose={() => setConfirmDelete(null)} maxWidth="xs" fullWidth aria-labelledby="delete-conversation-title">
      <DialogTitle id="delete-conversation-title">Переместить беседу в корзину?</DialogTitle>
      <DialogContent><DialogContentText sx={{ overflowWrap: 'anywhere' }}>«{confirmDelete?.title}» можно будет восстановить в течение 30 дней.</DialogContentText></DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button autoFocus color="inherit" onClick={() => setConfirmDelete(null)}>Отмена</Button>
        <Button color="error" onClick={() => { if (confirmDelete) onDelete(confirmDelete.id); setConfirmDelete(null); }}>Удалить</Button>
      </DialogActions>
    </Dialog>
  </Box>;
}
