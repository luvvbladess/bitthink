import { useEffect, useRef, useState } from 'react';
import { create } from 'zustand';
import { Alert, Box, Button, CircularProgress, IconButton, ToggleButton, ToggleButtonGroup, Typography, useMediaQuery } from '@mui/material';
import { OfficePreview, type OfficeViewer } from './OfficePreview';
import { DocumentReader, type ReadingContent } from './DocumentReader';
import { DesignCanvas } from '@/features/chat/DesignCanvas';
import { CaretLeft, CaretRight, DownloadSimple, ShareNetwork, X, MagnifyingGlassPlus, MagnifyingGlassMinus } from '@phosphor-icons/react';
import { useQuery } from '@tanstack/react-query';
import { apiBlob, apiFetch, downloadBlob } from '@/api/client';

export const canPreviewDocument = (name: string) => /\.(pdf|docx?|odt|rtf|xlsx?|ods|pptx?|odp|html?)$/i.test(name);
type PreviewFile = { name: string; conversationId?: string; url?: string; html?: string };
export const useDocumentPreview = create<{ file: PreviewFile | null; open: (file: PreviewFile) => void; close: () => void }>(set => ({
  file: null, open: file => set({ file }), close: () => set({ file: null }),
}));

export function DocumentPreview({ file, conversationId, onClose }: { file: PreviewFile; conversationId?: string; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [image, setImage] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const id = file.conversationId || conversationId;
  const mobile = useMediaQuery('(max-width:899px)');
  const [mode, setMode] = useState<'read' | 'original' | null>(null);
  const readingPosition = useRef(0);
  const docx = /\.docx$/i.test(file.name);
  const html = /\.html?$/i.test(file.name);
  const reading = docx && (mode || (mobile ? 'read' : 'original')) === 'read';
  const path = `/conversations/${encodeURIComponent(id || '')}/files/preview?filename=${encodeURIComponent(file.name)}&mobile=${mobile}&native=true&reading=${reading}`;
  const info = useQuery<{ pages?: number; viewer?: OfficeViewer; reader?: ReadingContent; download_url: string }>({ queryKey: ['document-preview', id, file.name, mobile, reading], queryFn: ({ signal }) => apiFetch(path, { signal, timeoutMs: 120_000 }), enabled: !!id && !html, retry: false, staleTime: 0, refetchOnWindowFocus: false });
  const [prepared, setPrepared] = useState<File | null>(null);
  useEffect(() => { setPrepared(null); }, [info.dataUpdatedAt]);
  const pageImage = useQuery({ queryKey: ['document-preview-page', id, file.name, page, info.dataUpdatedAt], queryFn: ({ signal }) => apiBlob(`${path}&page=${page}`, { signal, timeoutMs: 120_000 }), enabled: !!info.data?.pages && !!id && !info.isFetching, retry: false, gcTime: 0, refetchOnWindowFocus: false });
  useEffect(() => { if (info.data?.pages) setPage(value => Math.min(value, info.data!.pages!)); }, [info.data]);
  useEffect(() => {
    setImage('');
    if (!pageImage.data) return;
    const url = URL.createObjectURL(pageImage.data);
    setImage(url);
    return () => URL.revokeObjectURL(url);
  }, [pageImage.data]);

  const save = async (share = false) => {
    if ((!info.data?.download_url && !file.url) || busy) return;
    setBusy(true); setNotice('');
    try {
      let attachment = prepared;
      if (!attachment) {
        let blob: Blob;
        if (info.data?.download_url) blob = await apiBlob(info.data.download_url);
        else {
          const response = await fetch(file.url!, { credentials: 'same-origin' });
          if (!response.ok) throw new Error('Не удалось получить файл');
          blob = await response.blob();
        }
        attachment = new File([blob], file.name, { type: blob.type });
        setPrepared(attachment);
      }
      if (share && navigator.canShare?.({ files: [attachment] })) {
        if (navigator.userActivation && !navigator.userActivation.isActive) {
          setNotice('Файл готов. Нажмите «Поделиться файлом» ещё раз, чтобы выбрать приложение.');
          return;
        }
        await navigator.share({ files: [attachment], title: file.name });
      }
      else { downloadBlob(attachment, file.name); if (share) setNotice('Отправка файлов здесь недоступна. Файл сохранён для отправки.'); }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) setNotice('Не удалось сохранить или отправить файл. Попробуйте ещё раз.');
    } finally { setBusy(false); }
  };
  const error = !id ? 'Не удалось определить беседу документа.' : info.error?.message || pageImage.error?.message;
  const iconSx = { width: 44, height: 44, flexShrink: 0 };
  return <Box component="section" aria-label="Предпросмотр документа" sx={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column', bgcolor: 'background.default' }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: .5, px: 1, pt: 'max(4px, env(safe-area-inset-top))', borderBottom: '1px solid var(--bt-hairline)', flexShrink: 0 }}>
      <Typography noWrap title={file.name} sx={{ flex: 1, minWidth: 0, fontSize: '.875rem', fontWeight: 600 }}>{file.name}</Typography>
      {!html && (file.url || info.data?.download_url) && <><IconButton aria-label="Скачать документ" disabled={busy} onClick={() => void save()} sx={iconSx}><DownloadSimple size={20} /></IconButton><IconButton aria-label="Поделиться файлом" disabled={busy} onClick={() => void save(true)} sx={iconSx}><ShareNetwork size={20} /></IconButton></>}
      <IconButton aria-label="Закрыть предпросмотр" onClick={onClose} sx={iconSx}><X size={20} /></IconButton>
    </Box>
    {docx && <Box sx={{ px: 1.5, py: .75, borderBottom: '1px solid var(--bt-hairline)', flexShrink: 0 }}>
      <ToggleButtonGroup exclusive value={reading ? 'read' : 'original'} onChange={(_, next) => { if (next) setMode(next); }} aria-label="Вид документа" sx={{ width: '100%', '& .MuiToggleButton-root': { flex: 1, minWidth: 0, minHeight: 44, px: 1, py: .5, fontSize: '.875rem', textTransform: 'none' } }}>
        <ToggleButton value="read">Чтение</ToggleButton><ToggleButton value="original">Оригинал</ToggleButton>
      </ToggleButtonGroup>
    </Box>}
    {notice && <Alert severity="info" onClose={() => setNotice('')}>{notice}</Alert>}
    {html ? (file.url || file.html ? <DesignCanvas source={{ name: file.name, url: file.url, html: file.html }} compact={mobile} /> : <Alert severity="warning" sx={{ m: 2 }}>Не удалось получить результат. Закройте предпросмотр и откройте файл из беседы ещё раз.</Alert>) : info.data?.reader && !error ? <DocumentReader content={info.data.reader} position={readingPosition} /> : info.data?.viewer && !error ? <><Typography sx={{ px: 1.5, py: 0.5, fontSize: '0.8125rem', color: 'text.secondary', borderBottom: '1px solid var(--bt-hairline)' }}>{info.data.viewer.config.documentType === 'word' ? 'Оригинальное оформление · только просмотр' : mobile ? 'Только просмотр. Проведите по таблице, чтобы увидеть остальные столбцы. Листы — внизу.' : 'Только просмотр · листы и масштаб — внизу таблицы'}</Typography><OfficePreview viewer={info.data.viewer} /></> : <>
    <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', p: { xs: 1, md: 2 }, bgcolor: 'var(--bt-overlay-faint)' }}>
      {error ? <Alert severity="warning" action={<Button onClick={() => { if (info.error) void info.refetch(); else void pageImage.refetch(); }}>Повторить</Button>}>{error}</Alert> : !image || info.isFetching || pageImage.isFetching ? <Box role="status" sx={{ p: 4, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 1 }}><CircularProgress size={22} /><Typography>Готовим страницу…</Typography></Box> : <Box component="img" src={image} alt={`Страница ${page} документа ${file.name}`} sx={{ display: 'block', width: `${zoom}%`, maxWidth: 'none', height: 'auto', mx: 'auto', bgcolor: '#fff' }} />}
    </Box>
    <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', columnGap: 1, borderTop: '1px solid var(--bt-hairline)', pb: 'env(safe-area-inset-bottom)', flexShrink: 0 }}>
      <Box role="group" aria-label="Страницы документа" sx={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
      <IconButton aria-label="Предыдущая страница" disabled={page <= 1 || !info.data} onClick={() => setPage(value => value - 1)} sx={iconSx}><CaretLeft size={20} /></IconButton>
      <Typography aria-live="polite" sx={{ fontSize: '.875rem', minWidth: 62, textAlign: 'center' }}>{page} / {info.data?.pages || '…'}</Typography>
      <IconButton aria-label="Следующая страница" disabled={!info.data?.pages || page >= info.data.pages} onClick={() => setPage(value => value + 1)} sx={iconSx}><CaretRight size={20} /></IconButton>
      </Box>
      <Box role="group" aria-label="Масштаб документа" sx={{ display: 'flex', alignItems: 'center' }}>
      <IconButton aria-label="Уменьшить страницу" disabled={zoom <= 50} onClick={() => setZoom(value => value - 25)} sx={iconSx}><MagnifyingGlassMinus size={20} /></IconButton>
      <Button aria-label="Подогнать страницу по ширине" onClick={() => setZoom(100)} sx={{ minWidth: 48, minHeight: 44, color: 'text.secondary' }}>{zoom}%</Button>
      <IconButton aria-label="Увеличить страницу" disabled={zoom >= 200} onClick={() => setZoom(value => value + 25)} sx={iconSx}><MagnifyingGlassPlus size={20} /></IconButton>
      </Box>
    </Box>
    </>}
  </Box>;
}
