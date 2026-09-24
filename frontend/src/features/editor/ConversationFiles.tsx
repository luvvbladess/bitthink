import { Box, Drawer, IconButton, Tooltip, Typography, CircularProgress } from '@mui/material';
import { X, DownloadSimple, PencilSimpleLine, FileDoc, FilePdf, FileXls, FileText, Image } from '@phosphor-icons/react';
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
}

export const filesQueryKey = (conversationId?: string) => ['conversation-files', conversationId];

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

export function ConversationFilesDrawer({ conversationId, open, onClose }: { conversationId?: string; open: boolean; onClose: () => void }) {
  const editorEnabled = useEditorEnabled();
  const openEditor = useEditorStore((state) => state.open);
  const { data, isLoading, error } = useQuery<ConversationFile[]>({
    queryKey: filesQueryKey(conversationId),
    queryFn: () => apiFetch(`/conversations/${conversationId}/files`),
    enabled: open && Boolean(conversationId),
    // The editor saves a changed document every minute; keep the list current while it is open.
    refetchInterval: open ? 15_000 : false,
  });

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: { xs: '100%', sm: 420 } } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', px: 2, py: 1.5, borderBottom: '1px solid var(--bt-hairline)' }}>
        <Typography sx={{ fontWeight: 700, flexGrow: 1 }}>Файлы беседы</Typography>
        <IconButton onClick={onClose} aria-label="Закрыть список файлов">
          <X size={20} />
        </IconButton>
      </Box>
      <Box sx={{ overflowY: 'auto', px: 1.5, py: 1 }}>
        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={22} />
          </Box>
        )}
        {error && <Typography color="error" sx={{ p: 1 }}>{(error as Error).message}</Typography>}
        {data && data.length === 0 && (
          <Typography sx={{ color: 'text.secondary', p: 1 }}>В этой беседе пока нет файлов.</Typography>
        )}
        {data?.map((file) => {
          const Icon = iconFor(file);
          const canEdit = editorEnabled && file.editable && isEditableDocument(file.name);
          return (
            <Box
              key={file.name}
              sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start', p: 1.25, borderRadius: 2, '&:hover': { bgcolor: 'var(--bt-overlay-faint)' } }}
            >
              <Box sx={{ color: 'primary.light', pt: 0.25 }}>
                <Icon size={22} weight="duotone" />
              </Box>
              <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                <Typography sx={{ fontSize: '0.875rem', fontWeight: 600, overflowWrap: 'anywhere' }}>{file.name}</Typography>
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
                {canEdit && (
                  <Tooltip title="Открыть в редакторе">
                    <IconButton
                      size="small"
                      sx={{ width: 44, height: 44 }}
                      onClick={() => {
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
