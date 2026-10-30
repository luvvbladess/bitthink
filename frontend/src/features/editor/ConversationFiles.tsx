import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Box, Dialog, Drawer, IconButton, Menu, MenuItem, TextField, Typography, CircularProgress } from '@mui/material';
import { X, DownloadSimple, PencilSimpleLine, FileDoc, FilePdf, FileXls, FileText, Image, MagnifyingGlass, Eye, DotsThree, ChatsCircle, Presentation } from '@phosphor-icons/react';
import { canPreviewDocument, useDocumentPreview } from './DocumentPreview';
import { useQuery } from '@tanstack/react-query';
import { API_BASE, apiFetch } from '@/api/client';
import { isEditableDocument, useEditorEnabled, useEditorStore } from '@/features/editor/DocumentEditor';

interface ConversationFile {
  name: string;
  kind: string;
  size: number;
  uploaded_at: string;
  uploaded_by: string;
  editable: boolean;
  edited_at: string | null;
  edited_by: string | null;
  version: number;
  download_url: string | null;
  /** Only in the library: which chat the file lives in. */
  conversation_id?: string;
  conversation_title?: string;
}

export type FilesScope = 'chat' | 'all';
type FileKind = 'docs' | 'sheets' | 'slides' | 'images' | 'other';

export const filesQueryKey = (conversationId?: string) => ['conversation-files', conversationId];
const libraryQueryKey = ['conversation-files', 'library'];
const GROUPS = ['Сегодня', 'Вчера', 'Последние 7 дней', 'Ранее'] as const;
const FILTERS: { id: 'all' | FileKind; label: string }[] = [
  { id: 'all', label: 'Все' },
  { id: 'docs', label: 'Документы' },
  { id: 'sheets', label: 'Таблицы' },
  { id: 'slides', label: 'Презентации' },
  { id: 'images', label: 'Картинки' },
  { id: 'other', label: 'Другие' },
];

function fileKey(file: ConversationFile) {
  return `${file.conversation_id || ''}/${file.name}`;
}

function fileKind(file: ConversationFile): FileKind {
  if (file.kind === 'image' || /\.(png|jpe?g|gif|webp|bmp|svg|heic|avif)$/i.test(file.name)) return 'images';
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  if (['xls', 'xlsx', 'csv', 'ods', 'tsv'].includes(ext)) return 'sheets';
  if (['ppt', 'pptx', 'odp'].includes(ext)) return 'slides';
  if (['pdf', 'doc', 'docx', 'odt', 'rtf', 'txt', 'md'].includes(ext)) return 'docs';
  return 'other';
}

function iconFor(file: ConversationFile) {
  const kind = fileKind(file);
  if (kind === 'images') return Image;
  if (kind === 'sheets') return FileXls;
  if (kind === 'slides') return Presentation;
  const ext = file.name.split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return FilePdf;
  if (ext === 'docx' || ext === 'doc') return FileDoc;
  return FileText;
}

function stamp(file: ConversationFile) {
  const time = new Date(file.edited_at || file.uploaded_at).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function groupOf(time: number) {
  if (!time) return 'Ранее';
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const day = new Date(time);
  day.setHours(0, 0, 0, 0);
  const diff = Math.floor((start.getTime() - day.getTime()) / 86_400_000);
  if (diff <= 0) return 'Сегодня';
  if (diff === 1) return 'Вчера';
  if (diff < 7) return 'Последние 7 дней';
  return 'Ранее';
}

function ago(time: number) {
  if (!time) return '';
  const delta = Date.now() - time;
  if (delta < 45_000) return 'только что';
  const minutes = Math.round(delta / 60_000);
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(delta / 3_600_000);
  if (hours < 24) return `${hours} ч назад`;
  const date = new Date(time);
  return date.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  });
}

function filesWord(count: number) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} файл`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${count} файла`;
  return `${count} файлов`;
}

function hrefFor(file: ConversationFile) {
  return file.download_url ? `${API_BASE}${file.download_url}` : '';
}

const tileSx = {
  width: 44,
  height: 44,
  borderRadius: '12px',
  flexShrink: 0,
  display: 'grid',
  placeItems: 'center',
  bgcolor: 'var(--bt-overlay)',
  color: 'var(--bt-mark-mid)',
} as const;

const rowButtonSx = {
  appearance: 'none',
  border: 0,
  background: 'transparent',
  color: 'inherit',
  font: 'inherit',
  textAlign: 'left',
  width: '100%',
  minWidth: 0,
  display: 'flex',
  alignItems: 'center',
  gap: 1.25,
  minHeight: 64,
  px: 1,
  py: 0.75,
  borderRadius: '12px',
  cursor: 'pointer',
  touchAction: 'manipulation',
  '&:hover': { bgcolor: 'var(--bt-overlay-faint)' },
  '&:focus-visible': { outline: '2px solid var(--bt-mark-mid)', outlineOffset: 2 },
} as const;

export function ConversationFilesDrawer({
  conversationId,
  open,
  onClose,
  scope: initialScope = 'chat',
  onOpenChat,
}: {
  conversationId?: string;
  open: boolean;
  onClose: () => void;
  scope?: FilesScope;
  /** Switch to the chat a library file belongs to; resolves once it is the active chat. */
  onOpenChat?: (conversationId: string) => Promise<void> | void;
}) {
  const editorEnabled = useEditorEnabled();
  const openEditor = useEditorStore((state) => state.open);
  const openPreview = useDocumentPreview(state => state.open);
  const [scope, setScope] = useState<FilesScope>(initialScope);
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState<'all' | FileKind>('all');
  const [menu, setMenu] = useState<{ el: HTMLElement; file: ConversationFile } | null>(null);
  const [photo, setPhoto] = useState<ConversationFile | null>(null);
  const [photoFailed, setPhotoFailed] = useState(false);
  const [photoAttempt, setPhotoAttempt] = useState(0);
  const [actionError, setActionError] = useState('');
  const [broken, setBroken] = useState<Record<string, true>>({});
  const library = scope === 'all' || !conversationId;

  useEffect(() => {
    if (!open) {
      setMenu(null);
      setPhoto(null);
      return;
    }
    setScope(initialScope);
    setSearch('');
    setKind('all');
    setMenu(null);
    setPhoto(null);
    setBroken({});
    setActionError('');
  }, [open, initialScope]);

  useEffect(() => { setPhotoFailed(false); setPhotoAttempt(0); }, [photo]);

  const { data, isLoading, error, refetch, isFetching } = useQuery<ConversationFile[]>({
    queryKey: library ? libraryQueryKey : filesQueryKey(conversationId),
    queryFn: () => apiFetch(library ? '/conversations/library' : `/conversations/${conversationId}/files`),
    enabled: open,
    // The editor saves a changed document every minute; keep the list current while it is open.
    refetchInterval: open ? 15_000 : false,
  });

  const counts = useMemo(() => {
    const next: Record<FileKind, number> = { docs: 0, sheets: 0, slides: 0, images: 0, other: 0 };
    for (const file of data || []) next[fileKind(file)] += 1;
    return next;
  }, [data]);

  useEffect(() => {
    if (kind !== 'all' && data && counts[kind] === 0) setKind('all');
  }, [counts, kind, data]);

  const needle = search.trim().toLowerCase();
  const visible = useMemo(() => {
    return (data || [])
      .filter((file) => kind === 'all' || fileKind(file) === kind)
      .filter((file) => !needle || `${file.name} ${file.conversation_title || ''}`.toLowerCase().includes(needle))
      .sort((a, b) => stamp(b) - stamp(a));
  }, [data, kind, needle]);

  const groups = useMemo(() => {
    const buckets = new Map<string, ConversationFile[]>();
    for (const file of visible) {
      const label = groupOf(stamp(file));
      buckets.set(label, [...(buckets.get(label) || []), file]);
    }
    return GROUPS.filter((label) => buckets.has(label)).map((label) => ({ label, files: buckets.get(label) || [] }));
  }, [visible]);

  const filters = FILTERS.filter((item) => item.id === 'all' || counts[item.id] > 0);
  const showFilters = filters.length > 2;

  const goToChat = async (file: ConversationFile) => {
    if (file.conversation_id && file.conversation_id !== conversationId) await onOpenChat?.(file.conversation_id);
  };

  const canEdit = (file: ConversationFile) => {
    const otherChat = Boolean(file.conversation_id && file.conversation_id !== conversationId);
    return editorEnabled && file.editable && isEditableDocument(file.name) && (!otherChat || Boolean(onOpenChat));
  };

  const downloadFile = (file: ConversationFile) => {
    const href = hrefFor(file);
    if (!href) return;
    const link = document.createElement('a');
    link.href = href;
    link.rel = 'noopener';
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const editFile = async (file: ConversationFile) => {
    try {
      await goToChat(file);
      onClose();
      openEditor(file.name, file.conversation_id || conversationId);
    } catch {
      setActionError('Не удалось открыть беседу. Попробуйте ещё раз.');
    }
  };

  const openFile = async (file: ConversationFile) => {
    if (canPreviewDocument(file.name)) {
      openPreview({ name: file.name, conversationId: file.conversation_id || conversationId, url: hrefFor(file) || undefined });
      onClose();
      return;
    }
    if (fileKind(file) === 'images' && hrefFor(file)) {
      setPhoto(file);
      return;
    }
    if (canEdit(file)) {
      await editFile(file);
      return;
    }
    downloadFile(file);
  };

  const canOpen = (file: ConversationFile) => (
    canPreviewDocument(file.name)
    || (fileKind(file) === 'images' && Boolean(hrefFor(file)))
    || canEdit(file)
    || Boolean(hrefFor(file))
  );

  const menuFile = menu?.file;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: 440 },
          maxWidth: '100%',
          height: '100dvh',
          maxHeight: '100dvh',
          bgcolor: 'var(--bt-panel)',
          backgroundImage: 'none',
          color: 'var(--bt-ink)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, minWidth: 0, pt: 'env(safe-area-inset-top)' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, pt: 1, pb: 0.5, flexShrink: 0 }}>
          <Box sx={{ minWidth: 0, flex: 1, pl: 0.5 }}>
            <Typography component="h2" sx={{ fontWeight: 650, fontSize: '1.125rem', lineHeight: 1.3 }}>{library ? 'Библиотека' : 'Файлы'}</Typography>
            <Typography sx={{ fontSize: '0.8125rem', color: 'var(--bt-ink-muted)' }}>
              {isLoading ? 'Загружаем…' : data ? filesWord(data.length) : ''}
            </Typography>
          </Box>
          <IconButton onClick={onClose} aria-label="Закрыть библиотеку" sx={{ width: 44, height: 44, color: 'var(--bt-ink-2)' }}>
            <X size={20} />
          </IconButton>
        </Box>

        {conversationId && (
          <Box sx={{ display: 'flex', gap: 0.5, mx: 2, mb: 1.25, p: 0.5, borderRadius: '12px', bgcolor: 'var(--bt-overlay-faint)', flexShrink: 0 }} role="tablist" aria-label="Где искать файлы">
            {([['chat', 'Эта беседа'], ['all', 'Все файлы']] as const).map(([value, label]) => {
              const selected = library ? value === 'all' : value === 'chat';
              return (
                <Box
                  key={value}
                  component="button"
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setScope(value)}
                  sx={{
                    flex: 1,
                    minWidth: 0,
                    minHeight: 44,
                    border: 0,
                    borderRadius: '9px',
                    cursor: 'pointer',
                    font: 'inherit',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    color: selected ? 'var(--bt-ink)' : 'var(--bt-ink-muted)',
                    bgcolor: selected ? 'var(--bt-paper)' : 'transparent',
                    boxShadow: selected ? '0 1px 2px rgba(0,0,0,0.18)' : 'none',
                    touchAction: 'manipulation',
                  }}
                >
                  {label}
                </Box>
              );
            })}
          </Box>
        )}

        <Box sx={{ px: 2, pb: 1.25, flexShrink: 0 }}>
          <TextField
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Поиск"
            fullWidth
            inputProps={{ 'aria-label': 'Поиск по файлам', enterKeyHint: 'search' }}
            InputProps={{
              startAdornment: (
                <Box sx={{ color: 'var(--bt-ink-muted)', display: 'flex', mr: 0.75 }}>
                  <MagnifyingGlass size={18} />
                </Box>
              ),
            }}
            sx={{
              '& .MuiOutlinedInput-root': {
                borderRadius: '14px',
                backgroundColor: 'var(--bt-overlay-faint)',
                fontSize: 16,
                minHeight: 48,
              },
              '& .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--bt-hairline)' },
              '& .MuiOutlinedInput-notchedOutline legend': { width: 0 },
              '& .MuiOutlinedInput-root:hover .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--bt-overlay-strong)' },
              '& .MuiOutlinedInput-root.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--bt-mark-mid)', borderWidth: 1 },
            }}
          />
        </Box>

        {showFilters && (
          <Box
            role="group"
            aria-label="Категории файлов"
            sx={{
              display: 'flex',
              gap: 0.75,
              px: 2,
              pt: 0.5,
              pb: 1,
              flexWrap: 'wrap',
              flexShrink: 0,
              minWidth: 0,
              width: '100%',
            }}
          >
            {filters.map((item) => {
              const selected = kind === item.id;
              return (
                <Box
                  key={item.id}
                  component="button"
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setKind(item.id)}
                  sx={{
                    flex: '0 0 auto',
                    minHeight: 44,
                    px: 1.25,
                    borderRadius: '999px',
                    border: '1px solid',
                    borderColor: selected ? 'transparent' : 'var(--bt-hairline)',
                    bgcolor: selected ? 'var(--bt-ink)' : 'transparent',
                    color: selected ? 'var(--bt-bg)' : 'var(--bt-ink-2)',
                    font: 'inherit',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    touchAction: 'manipulation',
                  }}
                >
                  {item.label}
                </Box>
              );
            })}
          </Box>
        )}

        <Box sx={{ flex: 1, minHeight: 0, minWidth: 0, overflowY: 'auto', overflowX: 'hidden', overscrollBehavior: 'contain', px: 1, pb: 'max(16px, env(safe-area-inset-bottom))' }}>
          {isLoading && !data && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
              <CircularProgress size={22} />
            </Box>
          )}
          {error && <Alert severity="warning" sx={{ my: 1, overflowWrap: 'anywhere' }} action={<Button disabled={isFetching} onClick={() => void refetch()}>Повторить</Button>}>Не удалось обновить список файлов. Попробуйте ещё раз.</Alert>}
          {actionError && <Alert severity="warning" onClose={() => setActionError('')}>{actionError}</Alert>}
          {data && visible.length === 0 && (
            <Box sx={{ px: 2.5, py: 6, textAlign: 'center' }}>
              <Box sx={{ ...tileSx, width: 52, height: 52, borderRadius: '16px', mx: 'auto', mb: 1.5 }}>
                <FileText size={24} />
              </Box>
              <Typography sx={{ fontWeight: 650, mb: 0.5 }}>
                {needle || kind !== 'all' ? 'Ничего не нашлось' : library ? 'Библиотека пуста' : 'В этой беседе нет файлов'}
              </Typography>
              <Typography sx={{ fontSize: '0.875rem', color: 'var(--bt-ink-muted)' }}>
                {needle || kind !== 'all'
                  ? 'Попробуйте другое название или снимите фильтр.'
                  : 'Документы, таблицы и картинки из бесед появятся здесь.'}
              </Typography>
            </Box>
          )}
          {groups.map((group) => (
            <Box key={group.label} component="section" aria-label={group.label}>
              <Typography component="h3" sx={{ px: 1, pt: 1.25, pb: 0.25, fontSize: '0.75rem', fontWeight: 650, color: 'var(--bt-ink-muted)' }}>
                {group.label}
              </Typography>
              {kind === 'images' ? (
                <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0.5, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(132px, 1fr))', gap: 1 }}>
                  {group.files.map((file) => (
                    <ImageCard
                      key={fileKey(file)}
                      file={file}
                      broken={Boolean(broken[fileKey(file)])}
                      onBroken={() => setBroken((current) => ({ ...current, [fileKey(file)]: true }))}
                      onOpen={() => { void openFile(file); }}
                      onMenu={(el) => setMenu({ el, file })}
                    />
                  ))}
                </Box>
              ) : (
                <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                  {group.files.map((file) => (
                    <FileRow
                      key={fileKey(file)}
                      file={file}
                      library={library}
                      disabled={!canOpen(file)}
                      broken={Boolean(broken[fileKey(file)])}
                      onBroken={() => setBroken((current) => ({ ...current, [fileKey(file)]: true }))}
                      onOpen={() => { void openFile(file); }}
                      onMenu={(el) => setMenu({ el, file })}
                    />
                  ))}
                </Box>
              )}
            </Box>
          ))}
        </Box>
      </Box>

      <Menu
        anchorEl={menu?.el}
        open={Boolean(menu)}
        onClose={() => setMenu(null)}
        disableScrollLock
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { sx: { minWidth: 220, maxWidth: 'min(320px, calc(100vw - 24px))', bgcolor: 'var(--bt-paper)', backgroundImage: 'none', border: '1px solid var(--bt-hairline)', borderRadius: '14px' } } }}
      >
        {menuFile && canPreviewDocument(menuFile.name) && (
          <MenuItem sx={{ minHeight: 48, gap: 1.25 }} onClick={() => { const file = menuFile; setMenu(null); void openFile(file); }}>
            <Eye size={18} /> Предпросмотр
          </MenuItem>
        )}
        {menuFile && fileKind(menuFile) === 'images' && hrefFor(menuFile) && (
          <MenuItem sx={{ minHeight: 48, gap: 1.25 }} onClick={() => { setPhoto(menuFile); setMenu(null); }}>
            <Eye size={18} /> Предпросмотр
          </MenuItem>
        )}
        {menuFile && canEdit(menuFile) && (
          <MenuItem sx={{ minHeight: 48, gap: 1.25 }} onClick={() => { const file = menuFile; setMenu(null); void editFile(file); }}>
            <PencilSimpleLine size={18} /> Редактировать
          </MenuItem>
        )}
        {menuFile && hrefFor(menuFile) && (
          <MenuItem component="a" href={hrefFor(menuFile)} sx={{ minHeight: 48, gap: 1.25, color: 'inherit', textDecoration: 'none' }} onClick={() => setMenu(null)}>
            <DownloadSimple size={18} /> Скачать
          </MenuItem>
        )}
        {menuFile?.conversation_id && menuFile.conversation_id !== conversationId && onOpenChat && (
          <MenuItem sx={{ minHeight: 48, gap: 1.25 }} onClick={() => { const file = menuFile; setMenu(null); void goToChat(file).then(onClose).catch(() => setActionError('Не удалось открыть беседу. Попробуйте ещё раз.')); }}>
            <ChatsCircle size={18} /> Перейти в беседу
          </MenuItem>
        )}
        {menuFile && menuFile.version > 1 && (
          <Typography sx={{ px: 2, py: 1, fontSize: '0.75rem', color: 'var(--bt-ink-muted)' }}>Версия {menuFile.version}</Typography>
        )}
      </Menu>

      <Dialog
        open={Boolean(photo)}
        aria-label={photo ? `Предпросмотр картинки: ${photo.name}` : 'Предпросмотр картинки'}
        onClose={() => setPhoto(null)}
        fullWidth
        maxWidth="md"
        disableScrollLock
        PaperProps={{ sx: { m: { xs: 0, sm: 2 }, width: { xs: '100%', sm: 'calc(100% - 32px)' }, maxWidth: { xs: '100%', sm: 960 }, height: { xs: '100dvh', sm: 'auto' }, maxHeight: { xs: '100dvh', sm: 'calc(100dvh - 32px)' }, display: 'flex', flexDirection: 'column', overflow: 'hidden', bgcolor: 'var(--bt-bg)', backgroundImage: 'none', borderRadius: { xs: 0, sm: '16px' } } }}
      >
        {photo && (
          <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', minHeight: 0, maxHeight: { xs: '100dvh', sm: 'calc(100dvh - 32px)' }, pt: { xs: 'env(safe-area-inset-top)', sm: 0 } }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 1, flexShrink: 0 }}>
              <Typography noWrap title={photo.name} sx={{ flex: 1, minWidth: 0, fontWeight: 650 }}>{photo.name}</Typography>
              {hrefFor(photo) && <IconButton component="a" href={hrefFor(photo)} aria-label={`Скачать ${photo.name}`} sx={{ width: 44, height: 44 }}><DownloadSimple size={20} /></IconButton>}
              <IconButton onClick={() => setPhoto(null)} aria-label="Закрыть картинку" sx={{ width: 44, height: 44 }}><X size={20} /></IconButton>
            </Box>
            <Box sx={{ flex: 1, minHeight: 0, display: 'grid', placeItems: 'center', px: 2, pb: 'max(16px, env(safe-area-inset-bottom))', overflow: 'auto' }}>
              {photoFailed ? (
                <Alert severity="warning" action={<Button onClick={() => { setPhotoFailed(false); setPhotoAttempt(value => value + 1); }}>Повторить</Button>}>Не удалось загрузить картинку. Проверьте подключение и попробуйте ещё раз.</Alert>
              ) : <Box key={photoAttempt} component="img" src={hrefFor(photo)} alt={photo.name} onError={() => setPhotoFailed(true)} sx={{ maxWidth: '100%', maxHeight: 'min(78dvh, 820px)', objectFit: 'contain', borderRadius: '12px' }} />}
            </Box>
          </Box>
        )}
      </Dialog>
    </Drawer>
  );
}

function FileMark({ file, broken, onBroken, large = false }: { file: ConversationFile; broken: boolean; onBroken: () => void; large?: boolean }) {
  const src = fileKind(file) === 'images' && hrefFor(file) && !broken ? hrefFor(file) : '';
  if (src) {
    return (
      <Box
        component="img"
        loading="lazy"
        decoding="async"
        src={src}
        alt=""
        onError={onBroken}
        sx={{ width: large ? '100%' : 44, height: large ? 'auto' : 44, aspectRatio: large ? '1' : undefined, objectFit: 'cover', borderRadius: large ? '14px' : '12px', flexShrink: 0, bgcolor: 'var(--bt-overlay)', display: 'block' }}
      />
    );
  }
  const Icon = iconFor(file);
  return <Box sx={large ? { ...tileSx, width: '100%', height: 'auto', aspectRatio: '1', borderRadius: '14px' } : tileSx}><Icon size={large ? 28 : 22} /></Box>;
}

function PreviewLabel() {
  return <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', alignSelf: 'flex-start', gap: 0.5, px: 1, py: 0.25, mt: 0.5, maxWidth: '100%', border: '1px solid var(--bt-hairline)', borderRadius: '8px', bgcolor: 'var(--bt-overlay-faint)', color: 'var(--bt-ink)', fontSize: '0.8125rem', fontWeight: 600, lineHeight: 1.5 }}>
    <Eye size={16} aria-hidden style={{ flexShrink: 0 }} /> Предпросмотр
  </Box>;
}

function FileRow({ file, library, disabled, broken, onBroken, onOpen, onMenu }: {
  file: ConversationFile;
  library: boolean;
  disabled: boolean;
  broken: boolean;
  onBroken: () => void;
  onOpen: () => void;
  onMenu: (el: HTMLElement) => void;
}) {
  const time = stamp(file);
  const when = file.edited_at ? `изменён ${ago(time)}` : ago(time);
  const detail = [library ? file.conversation_title : '', when].filter(Boolean).join(' · ');
  return (
    <Box component="li" sx={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
      <Box component="button" type="button" onClick={onOpen} disabled={disabled} sx={{ ...rowButtonSx, flex: 1, opacity: 1, '&:disabled': { cursor: 'default' } }}>
        <FileMark file={file} broken={broken} onBroken={onBroken} />
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography noWrap title={file.name} sx={{ fontSize: '0.9375rem', fontWeight: 600, lineHeight: 1.35 }}>{file.name}</Typography>
          {detail && <Typography noWrap sx={{ fontSize: '0.8125rem', color: 'var(--bt-ink-muted)', mt: 0.25 }}>{detail}</Typography>}
          {(canPreviewDocument(file.name) || (fileKind(file) === 'images' && hrefFor(file))) && <PreviewLabel />}
        </Box>
      </Box>
      <IconButton aria-label={`Действия с ${file.name}`} aria-haspopup="menu" onClick={(event) => onMenu(event.currentTarget)} sx={{ width: 44, height: 44, flexShrink: 0, color: 'var(--bt-ink-muted)' }}>
        <DotsThree size={20} weight="bold" />
      </IconButton>
    </Box>
  );
}

function ImageCard({ file, broken, onBroken, onOpen, onMenu }: {
  file: ConversationFile;
  broken: boolean;
  onBroken: () => void;
  onOpen: () => void;
  onMenu: (el: HTMLElement) => void;
}) {
  return (
    <Box component="li" sx={{ position: 'relative', minWidth: 0 }}>
      <Box component="button" type="button" onClick={onOpen} aria-label={file.name} sx={{ ...rowButtonSx, flexDirection: 'column', alignItems: 'stretch', gap: 0.75, minHeight: 0, p: 0.5 }}>
        <FileMark file={file} broken={broken} onBroken={onBroken} large />
        <Typography noWrap title={file.name} sx={{ fontSize: '0.75rem', fontWeight: 600, px: 0.5, pb: 0.25 }}>{file.name}</Typography>
        {hrefFor(file) && <PreviewLabel />}
      </Box>
      <IconButton
        aria-label={`Действия с ${file.name}`}
        aria-haspopup="menu"
        onClick={(event) => onMenu(event.currentTarget)}
        sx={{ position: 'absolute', top: 6, right: 6, zIndex: 1, width: 44, height: 44, color: '#fff', bgcolor: 'rgba(0,0,0,0.45)', '&:hover': { bgcolor: 'rgba(0,0,0,0.62)' } }}
      >
        <DotsThree size={18} weight="bold" />
      </IconButton>
    </Box>
  );
}
