import { Box, CircularProgress, IconButton, Menu, MenuItem, Tooltip } from '@mui/material';
import {
  ArrowsOut,
  CaretDown,
  CaretLeft,
  CaretRight,
  DeviceMobile,
  DownloadSimple,
  Monitor,
  X,
} from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
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

export function DesignCanvas({ source, thinking = false, statusText = '', compact = false, onClose }: Props) {
  const shellRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState('');
  const [mobileFrame, setMobileFrame] = useState(false);
  const [menuEl, setMenuEl] = useState<HTMLElement | null>(null);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [exportError, setExportError] = useState('');
  const [slideIndex, setSlideIndex] = useState(0);
  const [stageScale, setStageScale] = useState(1);

  useEffect(() => {
    if (source?.html) {
      setDoc(ensureSlideRuntime(source.html));
      return;
    }
    if (!source?.url) {
      setDoc('');
      return;
    }
    let cancelled = false;
    fetch(source.url, { credentials: 'same-origin' })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then((text) => {
        if (!cancelled) setDoc(ensureSlideRuntime(text));
      })
      .catch(() => {
        if (!cancelled) setDoc('');
      });
    return () => {
      cancelled = true;
    };
  }, [source?.html, source?.url]);

  useEffect(() => {
    const frame = iframeRef.current;
    if (!frame) return;
    frame.srcdoc = doc;
    setSlideIndex(0);
  }, [doc]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      if (event.data?.type === 'bt-deck-at' && typeof event.data.index === 'number') {
        setSlideIndex(event.data.index);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [doc]);

  const empty = !doc && !thinking;
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

  const fullscreen = () => {
    const node = shellRef.current;
    if (!node) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    void node.requestFullscreen();
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
          px: compact ? 1 : 1.25,
          py: 0.7,
          minHeight: compact ? 56 : 52,
          pt: compact ? 'max(8px, env(safe-area-inset-top))' : 0.7,
          borderBottom: '1px solid var(--bt-hairline)',
          bgcolor: 'var(--bt-panel)',
        }}
      >
        <Box sx={{ fontSize: '0.8125rem', fontWeight: 600, letterSpacing: '-0.02em', flexShrink: 0 }}>Холст</Box>
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
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              fontStyle: thinking ? 'italic' : 'normal',
            }}
          >
            {headerHint}
          </Box>
        )}
        <Box sx={{ ml: 'auto', display: 'flex', alignItems: 'center', gap: 0.15 }}>
          {!compact && (
            <Tooltip title={mobileFrame ? 'Ширина десктопа' : 'Ширина телефона'}>
              <IconButton size="small" onClick={() => setMobileFrame((value) => !value)} aria-label="Ширина холста" sx={canvasIconSx}>
                {mobileFrame ? <Monitor size={16} /> : <DeviceMobile size={16} />}
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title="Скачать">
            <span>
              <IconButton
                size="small"
                onClick={(event) => setMenuEl(event.currentTarget)}
                disabled={!doc || Boolean(exporting)}
                aria-label="Скачать макет"
                aria-haspopup="menu"
                sx={compact ? navBtnSx : canvasIconSx}
              >
                {exporting ? <CircularProgress size={14} thickness={5} /> : <DownloadSimple size={16} />}
                <CaretDown size={10} style={{ marginLeft: 1 }} />
              </IconButton>
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
          {onClose && (
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
        {empty && (
          <Box
            sx={{
              m: 'auto',
              textAlign: 'left',
              px: 3,
              py: 3,
              width: 'min(340px, 92%)',
              borderRadius: '20px',
              bgcolor: 'var(--bt-panel)',
              border: '1px solid var(--bt-hairline)',
              boxShadow: 'var(--bt-shadow)',
            }}
          >
            <Box sx={{ fontSize: '0.7rem', letterSpacing: '0.16em', textTransform: 'uppercase', color: 'text.secondary', mb: 1 }}>
              Студия
            </Box>
            <Box sx={{ fontSize: '1.15rem', fontWeight: 600, color: 'text.primary', letterSpacing: '-0.03em', mb: 0.75 }}>
              Живой макет
            </Box>
            <Box sx={{ fontSize: '0.875rem', lineHeight: 1.5, color: 'text.secondary' }}>
              Опишите слайды в чате или прикрепите образец PPTX/PDF и файл ТЗ. Макет появится здесь. Готовую презу правит следующее сообщение: «темнее шапка», «другой стиль», «поправь слайд 3».
            </Box>
          </Box>
        )}
        {!empty && (
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
    if (!htmlName && !file.url) continue;
    if (file.url) return { url: file.url, name: file.filename || 'maket.html' };
    const html = decodeHtmlFile(file.data || '');
    if (html) return { html, name: file.filename };
  }
  return null;
}
