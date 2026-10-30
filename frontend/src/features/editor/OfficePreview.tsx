import { useEffect, useId, useRef, useState } from 'react';
import { Alert, Box, Button, CircularProgress, Typography } from '@mui/material';
import { loadEditorScript } from './DocumentEditor';

export type OfficeViewer = { server: string; config: Record<string, unknown> };

export function OfficePreview({ viewer }: { viewer: OfficeViewer }) {
  const host = `office-preview-${useId().replace(/:/g, '')}`;
  const editor = useRef<{ destroyEditor: () => void } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError('');
    const fail = () => { if (!cancelled) { setLoading(false); setError('Не удалось открыть таблицу. Повторите попытку или скачайте файл.'); } };
    const timer = window.setTimeout(fail, 90_000);
    const ready = () => { if (!cancelled) { window.clearTimeout(timer); setLoading(false); setError(''); } };
    void loadEditorScript(viewer.server).then(() => {
      if (cancelled) return;
      if (!window.DocsAPI) { fail(); return; }
      editor.current = new window.DocsAPI.DocEditor(host, {
        ...viewer.config, width: '100%', height: '100%',
        events: { onDocumentReady: ready, onError: fail },
      });
    }).catch(fail);
    return () => { cancelled = true; window.clearTimeout(timer); editor.current?.destroyEditor(); editor.current = null; };
  }, [viewer, host, attempt]);
  return <Box role="region" aria-label="Просмотр таблицы" sx={{ flex: 1, minWidth: 0, minHeight: 0, position: 'relative', bgcolor: '#fff' }}>
    <Box sx={{ position: 'absolute', inset: 0 }}><div id={host} style={{ height: '100%' }} /></Box>
    {(loading || error) && <Box sx={{ position: 'absolute', inset: 0, zIndex: 1, bgcolor: 'background.default', display: 'flex', alignItems: 'center', justifyContent: 'center', p: 2 }}>
      {error ? <Alert severity="warning" action={<Button onClick={() => setAttempt(value => value + 1)}>Повторить</Button>}>{error}</Alert>
        : <Box role="status" sx={{ display: 'flex', gap: 1, alignItems: 'center' }}><CircularProgress size={22} /><Typography>Открываем таблицу…</Typography></Box>}
    </Box>}
  </Box>;
}
