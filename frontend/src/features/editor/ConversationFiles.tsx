import { useEffect, useState } from 'react';
import { Box, Drawer, IconButton, Tooltip, Typography, CircularProgress, Tab, Tabs, TextField, Link } from '@mui/material';
import { X, DownloadSimple, PencilSimpleLine, FileDoc, FilePdf, FileXls, FileText, Image, MagnifyingGlass } from '@phosphor-icons/react';
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

export const filesQueryKey = (conversationId?: string) => ['conversation-files', conversationId];
const libraryQueryKey = ['conversation-files', 'library'];

function iconFor(file: ConversationFile) {
  const ext = file.name.split('.').pop()?.toLowerCase();
  if (file.kind === 'image') return Image;
  if (ext === 'pdf') return FilePdf;
  if (ext === 'xlsx' || ext === 'xls') return FileXls;
  if (ext === 'docx' || ext === 'doc') return FileDoc;
  return FileText;
}

function when(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

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
  const [scope, setScope] = useState<FilesScope>(initialScope);
  const [search, setSearch] = useState('');
  const library = scope === 'all' || !conversationId;

  useEffect(() => {
    if (open) {
      setScope(initialScope);
      setSearch('');
    }
  }, [open, initialScope]);

  const { data, isLoading, error } = useQuery<ConversationFile[]>({
    queryKey: library ? libraryQueryKey : filesQueryKey(conversationId),
    queryFn: () => apiFetch(library ? '/conversations/library' : `/conversations/${conversationId}/files`),
    enabled: open,
    // The editor saves a changed document every minute; keep the list current while it is open.
    refetchInterval: open ? 15_000 : false,
  });

  const needle = search.trim().toLowerCase();
  const files = needle
    ? data?.filter((file) => `${file.name} ${file.conversation_title || ''}`.toLowerCase().includes(needle))
    : data;

  const goToChat = async (file: ConversationFile) => {
    if (file.conversation_id && file.conversation_id !== conversationId) await onOpenChat?.(file.conversation_id);
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 440 } } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: '1px solid var(--bt-hairline)' }}>
        <Typography sx={{ fontWeight: 700, flexGrow: 1 }}>{library ? 'Библиотека' : 'Файлы беседы'}</Typography>
        <IconButton onClick={onClose} aria-label="Закрыть список файлов">
          <X size={20} />
        </IconButton>
      </Box>
      {conversationId && (
        <Tabs value={library ? 'all' : 'chat'} onChange={(_, value: FilesScope) => setScope(value)} variant="fullWidth" sx={{ borderBottom: '1px solid var(--bt-hairline)', minHeight: 44 }}>
          <Tab value="chat" label="Эта беседа" sx={{ textTransform: 'none', minHeight: 44 }} />
          <Tab value="all" label="Все файлы" sx={{ textTransform: 'none', minHeight: 44 }} />
        </Tabs>
      )}
      <Box sx={{ px: 1.5, pt: 1.25 }}>
        <TextField
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={library ? 'Найти файл или беседу' : 'Найти файл'}
          size="small"
          fullWidth
          inputProps={{ 'aria-label': 'Поиск по файлам' }}
          InputProps={{
            startAdornment: (
              <Box sx={{ color: 'text.secondary', display: 'flex', mr: 0.75 }}>
                <MagnifyingGlass size={15} />
              </Box>
            ),
          }}
        />
      </Box>
      <Box sx={{ overflowY: 'auto', px: 1.5, py: 1 }}>
        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={22} />
          </Box>
        )}
        {error && <Typography color="error" sx={{ p: 1 }}>{(error as Error).message}</Typography>}
        {files && files.length === 0 && (
          <Typography sx={{ color: 'text.secondary', p: 1 }}>
            {needle ? 'Ничего не нашлось.' : library ? 'Файлов пока нет.' : 'В этой беседе пока нет файлов.'}
          </Typography>
        )}
        {files?.map((file) => {
          const Icon = iconFor(file);
          const canEdit = editorEnabled && file.editable && isEditableDocument(file.name);
          const otherChat = Boolean(file.conversation_id && file.conversation_id !== conversationId);
          return (
            <Box
              key={`${file.conversation_id || ''}/${file.name}`}
              sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start', p: 1.25, borderRadius: 2, '&:hover': { bgcolor: 'var(--bt-overlay-faint)' } }}
            >
              <Box sx={{ color: 'primary.light', pt: 0.25 }}>
                <Icon size={22} weight="duotone" />
              </Box>
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography sx={{ fontSize: '0.875rem', fontWeight: 600, overflowWrap: 'anywhere' }}>{file.name}</Typography>
                {library && file.conversation_title && (
                  otherChat && onOpenChat ? (
                    <Link
                      component="button"
                      type="button"
                      underline="hover"
                      onClick={async () => { await goToChat(file); onClose(); }}
                      sx={{ fontSize: '0.75rem', textAlign: 'left', overflowWrap: 'anywhere' }}
                    >
                      {file.conversation_title}
                    </Link>
                  ) : (
                    <Typography sx={{ fontSize: '0.75rem', color: 'text.secondary', overflowWrap: 'anywhere' }}>
                      {file.conversation_title}
                    </Typography>
                  )
                )}
                <Typography sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>
                  Загрузил {file.uploaded_by} · {when(file.uploaded_at)}
                </Typography>
                {file.edited_at && (
                  <Typography sx={{ fontSize: '0.75rem', color: 'primary.light' }}>
                    Изменён{file.edited_by ? ` · ${file.edited_by}` : ''} · {when(file.edited_at)} · версия {file.version}
                  </Typography>
                )}
              </Box>
              <Box sx={{ display: 'flex', flexShrink: 0 }}>
                {canEdit && (!otherChat || onOpenChat) && (
                  <Tooltip title="Открыть в редакторе">
                    <IconButton
                      size="small"
                      sx={{ width: 44, height: 44 }}
                      onClick={async () => {
                        // The editor works on the active chat's files: switch to the file's chat first.
                        await goToChat(file);
                        onClose();
                        openEditor(file.name);
                      }}
                      aria-label={`Открыть ${file.name} в редакторе`}
                    >
                      <PencilSimpleLine size={18} />
                    </IconButton>
                  </Tooltip>
                )}
                {file.download_url && (
                  <Tooltip title={file.edited_at ? 'Скачать текущую версию' : 'Скачать'}>
                    <IconButton size="small" sx={{ width: 44, height: 44 }} component="a" href={`${API_BASE}${file.download_url}`} aria-label={`Скачать ${file.name}`}>
                      <DownloadSimple size={18} />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>
            </Box>
          );
        })}
      </Box>
    </Drawer>
  );
}
