import { Box, Button, CircularProgress, IconButton, Menu, MenuItem, Select, TextField, Tooltip } from '@mui/material';
import {
  ArrowsOut,
  CaretDown,
  CaretLeft,
  CaretRight,
  DeviceMobile,
  DownloadSimple,
  Monitor,
  CursorClick,
  Check,
  X,
} from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { selectionPrompt, withCanvasSelection, type CanvasSelection } from './studioSelection';
import { ActivityFeed, latestActivityLabel } from '@/components/ActivityFeed';
import { countSlides, ensureSlideRuntime } from './studioDeck';
import {
  canvasKindFromHtml,
  exportCanvas,
  formatsForKind,
  type ExportFormat,
} from './studioExport';

export type StudioCanvasSource = {
  url?: string;
  html?: string;
  name: string;
};

type PendingCanvasFile = {
  filename: string;
  data?: string;
  url?: string;
  canvas?: boolean;
};

type Props = {
  source: StudioCanvasSource | null;
  thinking?: boolean;
  statusText?: string;
  compact?: boolean;
  onClose?: () => void;
  versions?: StudioCanvasSource[];
  onVersion?: (source: StudioCanvasSource) => void;
  onEdit?: (prompt: string) => void;
};

function decodeHtmlFile(data: string): string {
  try {
    const bytes = atob(data);
    const chars = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i += 1) chars[i] = bytes.charCodeAt(i);
    return new TextDecoder('utf-8').decode(chars);
  } catch {
    return '';
  }
}

const canvasIconSx = {
  color: 'text.secondary',
  borderRadius: '10px',
  '&:hover': { color: 'text.primary', bgcolor: 'var(--bt-overlay-faint)' },
  '&.Mui-disabled': { color: 'text.disabled' },
} as const;

const STAGE_W = 1600;
const STAGE_H = 900;

export function DesignCanvas({ source, thinking = false, statusText = '', compact = false, onClose, versions = [], onVersion, onEdit }: Props) {
  const shellRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const sourceKey = source?.url || source?.html || '';
  const [documentState, setDocumentState] = useState({ key: '', html: '', loading: false, error: '' });
  const doc = documentState.key === sourceKey ? documentState.html : '';
  const loadError = documentState.key === sourceKey ? documentState.error : '';
  const loading = Boolean(sourceKey) && (documentState.key !== sourceKey || documentState.loading);
  const [reload, setReload] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [selection, setSelection] = useState<CanvasSelection | null>(null);
  const [change, setChange] = useState('');
  const versionIndex = versions.findIndex(item => (item.url || item.html) === sourceKey);
  const isLatest = versionIndex < 0 || versionIndex === versions.length - 1;
  const [mobileFrame, setMobileFrame] = useState(false);
  const [menuEl, setMenuEl] = useState<HTMLElement | null>(null);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [exportError, setExportError] = useState('');
  const [slideIndex, setSlideIndex] = useState(0);
  const [stageScale, setStageScale] = useState(1);

  useEffect(() => {
    setSelecting(false); setSelection(null); setChange(''); setExportError('');
    if (source?.html) {
      setDocumentState({ key: sourceKey, html: ensureSlideRuntime(source.html), loading: false, error: '' });
      return;
    }
    if (!source?.url) {
      setDocumentState({ key: sourceKey, html: '', loading: false, error: '' });
      return;
    }
    const controller = new AbortController();
    setDocumentState({ key: sourceKey, html: '', loading: true, error: '' });
    fetch(source.url, { credentials: 'same-origin', signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then(text => {
        if (!text.trim() || !/<(?:html|body|section|div|svg)\b/i.test(text)) throw new Error('Empty canvas');
        if (!controller.signal.aborted) setDocumentState({ key: sourceKey, html: ensureSlideRuntime(text), loading: false, error: '' });
      })
      .catch(() => {
        if (!controller.signal.aborted) setDocumentState({ key: sourceKey, html: '', loading: false, error: 'Не удалось открыть макет. Попробуйте загрузить его ещё раз.' });
      });
    return () => controller.abort();
  }, [source?.html, source?.url, reload]);

  useEffect(() => {
    const frame = iframeRef.current;
    if (!frame) return;
    frame.srcdoc = withCanvasSelection(doc);
    setSlideIndex(0);
  }, [doc]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      if (event.data?.type === 'bt-canvas-selection' && selecting && typeof event.data.text === 'string'
          && typeof event.data.tag === 'string' && /^[a-z][a-z0-9-]{0,20}$/.test(event.data.tag)) {
        setSelection({ text: event.data.text.slice(0, 240), tag: event.data.tag,
          slide: Number.isInteger(event.data.slide) && event.data.slide > 0 && event.data.slide <= 200 ? event.data.slide : undefined });
      }
      if (event.data?.type === 'bt-deck-at' && Number.isInteger(event.data.index) && event.data.index >= 0 && event.data.index < countSlides(doc)) {
        setSlideIndex(event.data.index);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [doc, selecting]);

  const empty = !doc && !thinking && !loading && !loadError;
  const kind = canvasKindFromHtml(doc);
  const slideCount = countSlides(doc);
  const useStage = slideCount > 1;

  useEffect(() => {
    if (!useStage) return;
    const box = stageRef.current;
    if (!box) return;
    const fit = () => {
      const next = Math.min(box.clientWidth / STAGE_W, box.clientHeight / STAGE_H);
      setStageScale(Number.isFinite(next) && next > 0.05 ? next : 1);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    return () => observer.disconnect();
  }, [useStage, doc, compact, mobileFrame]);
  const formats = formatsForKind(kind);
  const statusLabel = latestActivityLabel(statusText);
  const headerHint = thinking
    ? statusLabel
    : exporting
      ? exporting === 'pdf'
        ? 'Готовлю PDF…'
        : exporting === 'pptx'
          ? 'Готовлю презентацию…'
          : exporting === 'png'
            ? 'Готовлю картинку…'
            : 'Сохраняю HTML…'
      : source?.name?.replace(/\.html?$/i, '') || 'Макет появится здесь';

  const download = async (format: ExportFormat) => {
    if (!doc || exporting) return;
    setMenuEl(null);
    setExportError('');
    setExporting(format);
    try {
      await exportCanvas(doc, format, source?.name);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Не удалось сохранить файл');
    } finally {
      setExporting(null);
    }
  };

  const fullscreen = async () => {
    const node = shellRef.current;
    if (!node) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen().catch(() => setExportError('Не удалось выйти из полноэкранного режима.'));
      return;
    }
    try { await node.requestFullscreen(); } catch { setExportError('Браузер не разрешил полный экран. Можно увеличить окно или скачать макет.'); }
  };

  const goSlide = (next: number) => {
    if (slideCount < 2) return;
    const at = Math.max(0, Math.min(slideCount - 1, next));
    setSlideIndex(at);
    iframeRef.current?.contentWindow?.postMessage({ type: 'bt-deck', index: at }, '*');
  };

  const navBtnSx = {
    ...canvasIconSx,
    width: compact ? 44 : 32,
    height: compact ? 44 : 32,
  } as const;

  return (
    <Box
      ref={shellRef}
      sx={{
        flex: 1,
        minWidth: 0,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        height: compact ? '100%' : undefined,
        bgcolor: 'var(--bt-bg)',
        color: 'text.primary',
        borderLeft: compact ? 'none' : { md: '1px solid var(--bt-hairline)' },
      }}
    >
      <Box
        sx={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          flexWrap: 'wrap',
          px: compact ? 1 : 1.25,
          py: 0.7,
          minHeight: compact ? 56 : 52,
          pt: compact ? 'max(8px, env(safe-area-inset-top))' : 0.7,
          borderBottom: '1px solid var(--bt-hairline)',
          bgcolor: 'var(--bt-panel)',
        }}
      >
        <Box sx={{ fontSize: '0.875rem', fontWeight: 600, flexShrink: 0 }}>Холст</Box>
        {slideCount > 1 ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.15, minWidth: 0 }}>
            <IconButton size="small" onClick={() => goSlide(slideIndex - 1)} disabled={slideIndex <= 0} aria-label="Предыдущий слайд" sx={navBtnSx}>
              <CaretLeft size={18} />
            </IconButton>
            <Box sx={{ fontVariantNumeric: 'tabular-nums', fontSize: '0.8125rem', color: 'text.secondary', minWidth: 40, textAlign: 'center' }}>
              {slideIndex + 1}/{slideCount}
            </Box>
            <IconButton size="small" onClick={() => goSlide(slideIndex + 1)} disabled={slideIndex >= slideCount - 1} aria-label="Следующий слайд" sx={navBtnSx}>
              <CaretRight size={18} />
            </IconButton>
          </Box>
        ) : (
          <Box
            sx={{
              color: 'text.secondary',
              fontSize: '0.8125rem',
              minWidth: 0,
              flex: '1 1 60px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              fontStyle: thinking ? 'italic' : 'normal',
            }}
          >
            {headerHint}
          </Box>
        )}
        {compact && onClose && <IconButton onClick={onClose} aria-label="Закрыть холст" sx={{ ...navBtnSx, ml: 'auto' }}><X size={18} /></IconButton>}
        <Box sx={{ ml: 'auto', width: compact ? '100%' : undefined, display: 'flex', alignItems: 'center', justifyContent: compact ? 'space-between' : undefined, gap: 0.5, flexWrap: 'wrap' }}>
          {versions.length > 1 && onVersion && (
            <Select size="small" value={versionIndex < 0 ? versions.length - 1 : versionIndex}
              inputProps={{ 'aria-label': 'Версия макета' }}
              renderValue={(value) => `Версия ${Number(value) + 1}`}
              onChange={(event) => onVersion(versions[Number(event.target.value)])}
              disabled={thinking}
              MenuProps={{ disableScrollLock: true, transitionDuration: 0, anchorOrigin: { vertical: 'bottom', horizontal: 'right' }, transformOrigin: { vertical: 'top', horizontal: 'right' },
                PaperProps: { sx: { bgcolor: 'var(--bt-paper)', color: 'text.primary', backgroundImage: 'none', border: '1px solid var(--bt-line)', borderRadius: '12px', mt: 0.75, minWidth: 212, maxHeight: 'min(360px, 60dvh)' } },
                MenuListProps: { 'aria-label': 'Версии макета', sx: { p: 0.5 } } }}
              sx={{ fontSize: '0.8125rem', color: 'text.primary', bgcolor: 'var(--bt-panel)', borderRadius: '10px', minHeight: 40, minWidth: 112,
                '& .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--bt-line)' }, '& .MuiSelect-icon': { color: 'text.secondary' } }}>
              {versions.map((item, index) => <MenuItem key={item.url || index} value={index}
                sx={{ minHeight: 48, borderRadius: '8px', gap: 1.5, fontSize: '0.875rem', '&.Mui-selected': { bgcolor: 'var(--bt-glow)', '&:hover': { bgcolor: 'var(--bt-glow-strong)' } } }}>
                <Box sx={{ flex: 1 }}><Box>Версия {index + 1}</Box><Box sx={{ fontSize: '0.75rem', color: 'text.secondary' }}>{index === versions.length - 1 ? 'Последняя' : 'Предыдущая'}</Box></Box>
                {index === versionIndex && <Check size={16} aria-hidden style={{ color: 'inherit' }} />}
              </MenuItem>)}
            </Select>
          )}
          {!compact && (
            <Tooltip title={mobileFrame ? 'Ширина десктопа' : 'Ширина телефона'}>
              <IconButton size="small" onClick={() => setMobileFrame((value) => !value)} aria-label="Ширина холста" sx={canvasIconSx}>
                {mobileFrame ? <Monitor size={16} /> : <DeviceMobile size={16} />}
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title="Скачать">
            <span>
              <Button
                size="small"
                onClick={(event) => setMenuEl(event.currentTarget)}
                disabled={!doc || Boolean(exporting)}
                aria-label="Скачать макет"
                aria-haspopup="menu"
                sx={{ ...canvasIconSx, minHeight: 40, gap: 0.75, px: 1 }}
              >
                {exporting ? <CircularProgress size={14} thickness={5} /> : <DownloadSimple size={16} />}
                Скачать
                <CaretDown size={10} style={{ marginLeft: 1 }} />
              </Button>
            </span>
          </Tooltip>
          <Menu
            anchorEl={menuEl}
            open={Boolean(menuEl)}
            onClose={() => setMenuEl(null)}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            PaperProps={{
              sx: {
                bgcolor: 'var(--bt-paper)',
                backgroundImage: 'none',
                border: '1px solid var(--bt-hairline)',
                borderRadius: 2,
                mt: 1,
                minWidth: 188,
              },
            }}
          >
            {formats.map((item) => (
              <MenuItem
                key={item.id}
                onClick={() => void download(item.id)}
                sx={{ fontSize: '0.875rem', minHeight: 44 }}
              >
                {item.label}
              </MenuItem>
            ))}
          </Menu>
          {!compact && (
            <Tooltip title="На весь экран">
              <span>
                <IconButton size="small" onClick={fullscreen} disabled={!doc} aria-label="На весь экран" sx={canvasIconSx}>
                  <ArrowsOut size={16} />
                </IconButton>
              </span>
            </Tooltip>
          )}
          {onClose && !compact && (
            <Tooltip title="Закрыть холст">
              <IconButton size="small" onClick={onClose} aria-label="Закрыть холст" sx={navBtnSx}>
                <X size={18} />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>
      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'stretch',
          p: mobileFrame && !compact ? { xs: 1, md: 2 } : 0,
          bgcolor: 'var(--bt-surface)',
          position: 'relative',
        }}
      >
        {loadError && <Box role="alert" sx={{ m: 'auto', p: 3, maxWidth: 360, textAlign: 'center' }}>
          <Box sx={{ mb: 1.5, color: 'text.secondary' }}>{loadError}</Box>
          <Button variant="outlined" onClick={() => setReload(value => value + 1)}>Повторить загрузку</Button>
        </Box>}
        {loading && <Box role="status" sx={{ m: 'auto', display: 'flex', alignItems: 'center', gap: 1.5 }}><CircularProgress size={20} />Открываем макет…</Box>}
        {empty && <Box sx={{ m: 'auto', p: 3, maxWidth: 360, textAlign: 'center' }}>
          <Box sx={{ fontSize: '1.25rem', fontWeight: 600, mb: 1 }}>Здесь будет ваш результат</Box>
          <Box sx={{ color: 'text.secondary', lineHeight: 1.6 }}>Опишите идею в чате. Готовый макет можно рассмотреть, изменить и скачать.</Box>
        </Box>}
        {!empty && !loading && !loadError && (
          <Box
            ref={stageRef}
            sx={{
              width: mobileFrame && !useStage ? { xs: '100%', md: 390 } : '100%',
              maxWidth: '100%',
              height: '100%',
              borderRadius: mobileFrame ? '18px' : 0,
              overflow: 'hidden',
              boxShadow: mobileFrame ? 'var(--bt-shadow)' : 'none',
              bgcolor: 'var(--bt-paper)',
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {doc ? (
              useStage ? (
                <Box
                  sx={{
                    width: STAGE_W * stageScale,
                    height: STAGE_H * stageScale,
                    position: 'relative',
                    overflow: 'hidden',
                    flexShrink: 0,
                    bgcolor: 'var(--bt-paper)',
                  }}
                >
                  <iframe
                    ref={iframeRef}
                    title="Холст Студии"
                    sandbox="allow-scripts"
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: STAGE_W,
                      height: STAGE_H,
                      border: 0,
                      transform: `scale(${stageScale})`,
                      transformOrigin: '0 0',
                      background: 'var(--bt-paper)',
                    }}
                  />
                </Box>
              ) : (
              <iframe
                ref={iframeRef}
                title="Холст Студии"
                sandbox="allow-scripts"
                style={{
                  width: '100%',
                  height: '100%',
                  border: 0,
                  background: 'var(--bt-paper)',
                  contain: 'strict',
                  contentVisibility: 'auto',
                }}
              />
              )
            ) : null}
            {thinking && (
              <Box
                sx={{
                  position: 'absolute',
                  ...(doc
                    ? { left: 16, right: 16, bottom: 16, display: 'flex', justifyContent: 'center' }
                    : { inset: 0, display: 'grid', placeItems: 'center', px: 2 }),
                  pointerEvents: 'none',
                  zIndex: 2,
                }}
              >
                <Box
                  sx={{
                    width: 'min(360px, 100%)',
                    px: 2.5,
                    py: 2.25,
                    borderRadius: '20px',
                    bgcolor: 'var(--bt-panel)',
                    border: '1px solid var(--bt-hairline)',
                    boxShadow: 'var(--bt-shadow)',
                    pointerEvents: 'auto',
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.35 }}>
                    <CircularProgress size={12} thickness={5} />
                    <Box sx={{ fontSize: '0.7rem', letterSpacing: '0.16em', textTransform: 'uppercase', color: 'text.secondary' }}>
                      Студия
                    </Box>
                  </Box>
                  <ActivityFeed statusText={statusText || 'Думаю'} />
                </Box>
              </Box>
            )}
          </Box>
        )}
        {exportError && (
          <Box
            sx={{
              position: 'absolute',
              bottom: 16,
              left: '50%',
              transform: 'translateX(-50%)',
              px: 1.5,
              py: 0.75,
              borderRadius: '999px',
              bgcolor: 'var(--bt-panel)',
              border: '1px solid var(--bt-hairline)',
              color: 'var(--bt-danger)',
              fontSize: '0.8125rem',
              whiteSpace: 'normal',
              maxWidth: 'min(420px, 92%)',
              textAlign: 'center',
            }}
          >
            {exportError}
          </Box>
        )}
      </Box>
      {doc && onEdit && <Box sx={{ flexShrink: 0, borderTop: '1px solid var(--bt-hairline)', bgcolor: 'var(--bt-panel)', p: 1.25 }}>
        {!isLatest ? <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
          <Box sx={{ fontSize: '0.8125rem', color: 'text.secondary' }}>Просмотр предыдущей версии</Box>
          <Button onClick={() => onVersion?.(versions[versions.length - 1])}>К последней</Button>
        </Box> : <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.75 }}>
            <Button size="small" disabled={thinking} variant={selecting ? 'outlined' : 'text'} startIcon={<CursorClick size={16} />}
              aria-pressed={selecting} onClick={() => { const next = !selecting; setSelecting(next); if (!next) setSelection(null); iframeRef.current?.contentWindow?.postMessage({ type: 'bt-select-mode', enabled: next }, '*'); }}>
              {selecting ? 'Завершить выбор' : 'Выбрать элемент'}
            </Button>
            <Box role="status" sx={{ fontSize: '0.8125rem', color: 'text.secondary', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {selection ? (selection.text || selection.tag) : selecting ? 'Нажмите на нужное место в макете' : 'Или опишите изменение целиком'}
            </Box>
          </Box>
          <Box component="form" onSubmit={(event) => { event.preventDefault(); if (!change.trim() || thinking) return;
            onEdit(selection ? selectionPrompt(selection, change) : `В текущем макете: ${change.trim()}. Сохрани остальные элементы и содержание.`); setChange(''); }}
            sx={{ display: 'flex', alignItems: 'flex-end', gap: 1 }}>
            <TextField fullWidth multiline maxRows={3} size="small" value={change} disabled={thinking}
              onChange={(event) => setChange(event.target.value)} placeholder={selection ? 'Что изменить в выбранном элементе?' : 'Например: сделай фон светлее'}
              inputProps={{ 'aria-label': 'Что изменить в макете?' }} />
            <Button type="submit" variant="contained" disabled={thinking || !change.trim()} sx={{ minHeight: 40 }}>Применить</Button>
          </Box>
        </>}
      </Box>}

    </Box>
  );
}

export function isHtmlAttachment(name?: string, url?: string, mime?: string) {
  if ((mime || '').includes('text/html')) return true;
  return /\.html?$/i.test(name || '') || /\.html?(?:\?|$)/i.test(url || '');
}

export function findStudioCanvas(
  messages: Array<{
    attachment?: {
      name?: string;
      url?: string;
      mime_type?: string;
      canvas?: boolean;
      files?: Array<{ name?: string; url?: string; mime_type?: string; canvas?: boolean }>;
    };
    file?: PendingCanvasFile;
  }>,
): StudioCanvasSource | null {
  for (const message of [...messages].reverse()) {
    const attachment = message.attachment;
    if (attachment) {
      const items = [attachment, ...(attachment.files || [])];
      for (const item of items) {
        if (!isHtmlAttachment(item.name, item.url, item.mime_type) && !item.canvas) continue;
        if (item.url) return { url: item.url, name: item.name || 'maket.html' };
      }
    }
    const file = message.file;
    if (!file) continue;
    const htmlName = isHtmlAttachment(file.filename) || Boolean(file.canvas);
    if (!htmlName && !isHtmlAttachment(undefined, file.url)) continue;
    if (file.url) return { url: file.url, name: file.filename || 'maket.html' };
    const html = decodeHtmlFile(file.data || '');
    if (html) return { html, name: file.filename };
  }
  return null;
}


export function studioCanvasVersions(messages: Parameters<typeof findStudioCanvas>[0]): StudioCanvasSource[] {
  const result: StudioCanvasSource[] = [];
  const seen = new Set<string>();
  for (const message of messages) {
    const source = findStudioCanvas([message]);
    if (!source) continue;
    const key = source.url || source.html || '';
    if (!seen.has(key)) { seen.add(key); result.push(source); }
  }
  return result;
}
