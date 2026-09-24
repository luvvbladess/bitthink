import { useEffect, useRef, useState } from 'react';
import { Box, Dialog, IconButton, Typography, CircularProgress, ToggleButton, ToggleButtonGroup, useMediaQuery, useTheme } from '@mui/material';
import { PhoneEdit } from '@/features/editor/PhoneEdit';
import { X } from '@phosphor-icons/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { create } from 'zustand';
import { apiFetch } from '@/api/client';

// Which chat file is open in the editor. The attachment card opens it,
// ChatPage owns the dialog because it knows the conversation.
export const useEditorStore = create<{ filename: string | null; open: (name: string) => void; close: () => void }>(
  (set) => ({
    filename: null,
    open: (filename) => set({ filename }),
    close: () => set({ filename: null }),
  }),
);

export function useEditorEnabled() {
  const { data } = useQuery({
    queryKey: ['editor-config'],
    queryFn: () => apiFetch('/editor/config'),
    staleTime: 5 * 60_000,
  });
  return Boolean(data?.enabled);
}

export const isEditableDocument = (name: string) => /\.docx?$/i.test(name);

// The plugin runs inside OnlyOffice on our origin and reads this to call the AI
// endpoint. sessionStorage is per tab, so two tabs keep two documents apart.
export const EDITOR_SESSION_KEY = 'bt-editor-session';

declare global {
  interface Window {
    DocsAPI?: { DocEditor: new (id: string, config: unknown) => { destroyEditor: () => void } };
  }
}

const scriptLoads = new Map<string, Promise<void>>();

function loadEditorScript(server: string): Promise<void> {
  const src = `${server}/web-apps/apps/api/documents/api.js`;
  if (!scriptLoads.has(src)) {
    scriptLoads.set(
      src,
      new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = () => resolve();
        script.onerror = () => {
          scriptLoads.delete(src);
          reject(new Error('Сервер документов недоступен'));
        };
        document.body.appendChild(script);
      }),
    );
  }
  return scriptLoads.get(src)!;
}

const HOST_ID = 'bt-onlyoffice-editor';

export function DocumentEditorDialog({ conversationId }: { conversationId?: string }) {
  const { filename, close: closeStore } = useEditorStore();
  const queryClient = useQueryClient();
  const [error, setError] = useState('');
  const close = () => {
    closeStore();
    // The document server sends the final save a few seconds after the last editor leaves.
    const refresh = () => queryClient.invalidateQueries({ queryKey: ['conversation-files', conversationId] });
    refresh();
    window.setTimeout(refresh, 20_000);
  };
  const [loading, setLoading] = useState(false);
  const editorRef = useRef<{ destroyEditor: () => void } | null>(null);
  // Phones get the OnlyOffice viewer plus our own clause editor (free OnlyOffice
  // cannot edit on mobile, and its plugins do not run there).
  const theme = useTheme();
  const isPhone = useMediaQuery(theme.breakpoints.down('md'));
  const [session, setSession] = useState<{ docId: string; aiToken: string } | null>(null);
  const [phoneTab, setPhoneTab] = useState<'view' | 'edit'>('view');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!filename) {
      setSession(null);
      setPhoneTab('view');
    }
  }, [filename]);

  useEffect(() => {
    if (!filename || !conversationId) return;
    let cancelled = false;
    setError('');
    setLoading(true);
    (async () => {
      try {
        const opened = await apiFetch('/editor/open', {
          method: 'POST',
          body: JSON.stringify({ conversation_id: conversationId, filename, origin: window.location.origin, mobile: isPhone }),
        });
        setSession({ docId: opened.doc_id, aiToken: opened.ai_token });
        sessionStorage.setItem(EDITOR_SESSION_KEY, JSON.stringify({ docId: opened.doc_id, aiToken: opened.ai_token }));
        await loadEditorScript(opened.server);
        if (cancelled || !window.DocsAPI) return;
        editorRef.current = new window.DocsAPI.DocEditor(HOST_ID, {
          ...opened.config,
          width: '100%',
          height: '100%',
          events: { onAppReady: () => setLoading(false), onDocumentReady: () => setLoading(false) },
        });
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message || 'Не удалось открыть документ');
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      editorRef.current?.destroyEditor();
      editorRef.current = null;
    };
  }, [filename, conversationId, isPhone, reload]);

  return (
    <Dialog fullScreen open={Boolean(filename)} onClose={close} aria-label="Редактор документа">
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: { xs: 1, md: 2 },
          pt: { xs: 'max(6px, env(safe-area-inset-top))', md: 1 },
          pb: { xs: 0.75, md: 1 },
          borderBottom: '1px solid var(--bt-hairline)',
        }}
      >
        <Typography sx={{ fontWeight: 800, letterSpacing: '-0.02em', color: 'primary.light', flexShrink: 0, display: { xs: 'none', sm: 'block' } }}>
          Bit Office
        </Typography>
        <Typography sx={{ fontWeight: 600, flexGrow: 1, minWidth: 0, fontSize: { xs: '0.875rem', md: '1rem' }, pl: { xs: 1, sm: 0 } }} noWrap>
          {filename}
        </Typography>
        <Typography sx={{ fontSize: '0.75rem', color: 'text.secondary', display: { xs: 'none', md: 'block' } }}>
          Правки сохраняются в файл беседы сами, примерно раз в минуту. Участники видят их сразу.
        </Typography>
        {isPhone && session && (
          <ToggleButtonGroup
            exclusive
            size="small"
            value={phoneTab}
            onChange={(_, next) => next && setPhoneTab(next)}
            aria-label="Просмотр или правка"
            sx={{ flexShrink: 0, '& .MuiToggleButton-root': { px: 1.25, minHeight: 36, textTransform: 'none', fontWeight: 600 } }}
          >
            <ToggleButton value="view">Документ</ToggleButton>
            <ToggleButton value="edit">Править</ToggleButton>
          </ToggleButtonGroup>
        )}
        <IconButton onClick={close} aria-label="Закрыть редактор" sx={{ width: 44, height: 44, flexShrink: 0 }}>
          <X size={20} />
        </IconButton>
      </Box>
      <Box sx={{ position: 'relative', flex: '1 1 0', minHeight: 0 }}>
        {(loading || error) && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1.5, p: 2, textAlign: 'center' }}>
            {error ? <Typography color="error">{error}</Typography> : <CircularProgress size={24} />}
          </Box>
        )}
        <div id={HOST_ID} />
        {isPhone && session && phoneTab === 'edit' && (
          <PhoneEdit
            docId={session.docId}
            aiToken={session.aiToken}
            // A saved clause is a new version: reopen the viewer on it.
            onSaved={() => setReload((value) => value + 1)}
          />
        )}
      </Box>
    </Dialog>
  );
}
