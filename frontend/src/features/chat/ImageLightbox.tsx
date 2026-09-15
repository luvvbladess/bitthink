import { useCallback, useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react';
import { createPortal } from 'react-dom';
import { Box, IconButton, Tooltip } from '@mui/material';
import {
  DownloadSimple,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  PencilSimple,
  X,
} from '@phosphor-icons/react';
import { downloadChatImage, imageDownloadName } from './chatImages';
import { HOVER_FINE } from '@/theme/effects';

const MIN_ZOOM = 1;
const MAX_ZOOM = 6;
const ZOOM_STEP = 0.4;

type Props = {
  src: string;
  alt?: string;
  onClose: () => void;
  onEdit?: () => void;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function toolBtnSx(extra?: object) {
  return {
    width: 44,
    height: 44,
    color: '#f4f6f7',
    ...extra,
    [HOVER_FINE]: {
      '&:hover': { bgcolor: 'rgba(255,255,255,0.1)' },
    },
    '&:focus-visible': {
      outline: '2px solid #5bb9de',
      outlineOffset: 2,
    },
  };
}

export function ImageLightbox({ src, alt, onClose, onEdit }: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const transformRef = useRef({ zoom: 1, x: 0, y: 0 });
  const pointersRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  const pinchRef = useRef<{ distance: number; zoom: number } | null>(null);
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const lastTapRef = useRef(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const applyTransform = useCallback((nextZoom: number, nextX: number, nextY: number) => {
    const clampedZoom = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
    const x = clampedZoom <= MIN_ZOOM + 0.01 ? 0 : nextX;
    const y = clampedZoom <= MIN_ZOOM + 0.01 ? 0 : nextY;
    transformRef.current = { zoom: clampedZoom, x, y };
    setZoom(clampedZoom);
    setPan({ x, y });
  }, []);

  const zoomAround = useCallback(
    (clientX: number, clientY: number, nextZoom: number) => {
      const viewport = viewportRef.current;
      const current = transformRef.current;
      const clamped = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
      if (!viewport || clamped === current.zoom) {
        applyTransform(clamped, current.x, current.y);
        return;
      }
      const rect = viewport.getBoundingClientRect();
      const cx = clientX - rect.left - rect.width / 2;
      const cy = clientY - rect.top - rect.height / 2;
      const ratio = clamped / current.zoom;
      applyTransform(clamped, cx - (cx - current.x) * ratio, cy - (cy - current.y) * ratio);
    },
    [applyTransform],
  );

  const zoomBy = useCallback(
    (delta: number) => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      const rect = viewport.getBoundingClientRect();
      zoomAround(rect.left + rect.width / 2, rect.top + rect.height / 2, transformRef.current.zoom + delta);
    },
    [zoomAround],
  );

  const resetView = useCallback(() => applyTransform(1, 0, 0), [applyTransform]);

  const handleDownload = useCallback(async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      await downloadChatImage(src, imageDownloadName(src, alt));
    } catch {
      const link = document.createElement('a');
      link.href = src;
      link.download = imageDownloadName(src, alt);
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      setDownloading(false);
    }
  }, [alt, downloading, src]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        zoomBy(ZOOM_STEP);
      } else if (event.key === '-' || event.key === '_') {
        event.preventDefault();
        zoomBy(-ZOOM_STEP);
      } else if (event.key === '0') {
        event.preventDefault();
        resetView();
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        void handleDownload();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleDownload, onClose, resetView, zoomBy]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomAround(event.clientX, event.clientY, transformRef.current.zoom * factor);
    };
    viewport.addEventListener('wheel', onWheel, { passive: false });
    return () => viewport.removeEventListener('wheel', onWheel);
  }, [zoomAround]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointersRef.current.size === 2) {
      const points = [...pointersRef.current.values()];
      const dx = points[0].x - points[1].x;
      const dy = points[0].y - points[1].y;
      pinchRef.current = { distance: Math.hypot(dx, dy), zoom: transformRef.current.zoom };
      dragRef.current = null;
      setDragging(true);
      return;
    }
    if (transformRef.current.zoom > 1.02) {
      dragRef.current = {
        x: event.clientX,
        y: event.clientY,
        panX: transformRef.current.x,
        panY: transformRef.current.y,
      };
      setDragging(true);
    }
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!pointersRef.current.has(event.pointerId)) return;
    pointersRef.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointersRef.current.size === 2 && pinchRef.current) {
      const points = [...pointersRef.current.values()];
      const dx = points[0].x - points[1].x;
      const dy = points[0].y - points[1].y;
      const distance = Math.hypot(dx, dy);
      if (pinchRef.current.distance < 8) return;
      const midX = (points[0].x + points[1].x) / 2;
      const midY = (points[0].y + points[1].y) / 2;
      zoomAround(midX, midY, pinchRef.current.zoom * (distance / pinchRef.current.distance));
      return;
    }
    if (!dragRef.current) return;
    applyTransform(
      transformRef.current.zoom,
      dragRef.current.panX + (event.clientX - dragRef.current.x),
      dragRef.current.panY + (event.clientY - dragRef.current.y),
    );
  };

  const endPointer = (event: PointerEvent<HTMLDivElement>) => {
    pointersRef.current.delete(event.pointerId);
    if (pointersRef.current.size < 2) pinchRef.current = null;
    if (pointersRef.current.size === 0) {
      dragRef.current = null;
      setDragging(false);
    }
  };

  const onDoubleActivate = (event: MouseEvent | PointerEvent) => {
    if (transformRef.current.zoom > 1.05) {
      resetView();
      return;
    }
    zoomAround(event.clientX, event.clientY, 2.4);
  };

  const onClickViewport = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (transformRef.current.zoom > 1.02) {
      resetView();
      return;
    }
    onClose();
  };

  const percent = `${Math.round(zoom * 100)}%`;

  return createPortal(
    <Box
      role="dialog"
      aria-modal="true"
      aria-label={alt ? `Просмотр: ${alt}` : 'Просмотр изображения'}
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: 1700,
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'rgba(6, 8, 10, 0.92)',
        '@media (prefers-reduced-transparency: reduce)': { bgcolor: '#0c1012' },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: { xs: 10, sm: 16 },
          left: 0,
          right: 0,
          zIndex: 2,
          display: 'flex',
          justifyContent: 'center',
          pointerEvents: 'none',
          px: 1.5,
        }}
      >
        <Box
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 0.25,
            pointerEvents: 'auto',
            px: 0.5,
            py: 0.35,
            borderRadius: '999px',
            border: '1px solid rgba(255,255,255,0.14)',
            bgcolor: 'rgba(18, 24, 26, 0.82)',
            backdropFilter: 'blur(18px) saturate(1.2)',
            WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
            boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
          }}
        >
          <Tooltip title="Отдалить">
            <span>
              <IconButton
                aria-label="Отдалить"
                disabled={zoom <= MIN_ZOOM}
                onClick={() => zoomBy(-ZOOM_STEP)}
                sx={toolBtnSx()}
              >
                <MagnifyingGlassMinus size={20} />
              </IconButton>
            </span>
          </Tooltip>
          <Box
            component="button"
            type="button"
            onClick={resetView}
            aria-label="Сбросить масштаб"
            title="Сбросить масштаб"
            sx={{
              minWidth: 56,
              px: 0.75,
              border: 0,
              bgcolor: 'transparent',
              color: 'rgba(244,246,247,0.88)',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: zoom > 1 ? 'pointer' : 'default',
            }}
          >
            {percent}
          </Box>
          <Tooltip title="Приблизить">
            <span>
              <IconButton
                aria-label="Приблизить"
                disabled={zoom >= MAX_ZOOM}
                onClick={() => zoomBy(ZOOM_STEP)}
                sx={toolBtnSx()}
              >
                <MagnifyingGlassPlus size={20} />
              </IconButton>
            </span>
          </Tooltip>
          <Box sx={{ width: 1, height: 22, mx: 0.4, bgcolor: 'rgba(255,255,255,0.16)' }} />
          {onEdit && (
            <Tooltip title="Изменить">
              <IconButton
                aria-label="Изменить это изображение"
                onClick={() => {
                  onClose();
                  onEdit();
                }}
                sx={toolBtnSx()}
              >
                <PencilSimple size={20} weight="bold" />
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title={downloading ? 'Скачиваю' : 'Скачать'}>
            <span>
              <IconButton
                aria-label="Скачать изображение"
                disabled={downloading}
                onClick={() => void handleDownload()}
                sx={toolBtnSx()}
              >
                <DownloadSimple size={20} weight="bold" />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Закрыть">
            <IconButton ref={closeRef} aria-label="Закрыть" onClick={onClose} sx={toolBtnSx()}>
              <X size={20} weight="bold" />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      <Box
        ref={viewportRef}
        onClick={onClickViewport}
        onDoubleClick={onDoubleActivate}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        sx={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
          px: { xs: 1, sm: 2 },
          pt: { xs: 9, sm: 10 },
          pb: { xs: 3, sm: 4 },
          touchAction: 'none',
          cursor: zoom > 1 ? 'grab' : 'zoom-in',
          '&:active': { cursor: zoom > 1 ? 'grabbing' : 'zoom-in' },
        }}
      >
        <Box
          component="img"
          src={src}
          alt={alt || ''}
          draggable={false}
          onClick={(event) => {
            event.stopPropagation();
            if (event.detail === 2) return;
            const now = Date.now();
            if (now - lastTapRef.current < 280) {
              onDoubleActivate(event);
              lastTapRef.current = 0;
              return;
            }
            lastTapRef.current = now;
          }}
          onDoubleClick={(event) => {
            event.stopPropagation();
            event.preventDefault();
            lastTapRef.current = 0;
            onDoubleActivate(event);
          }}
          sx={{
            maxWidth: '100%',
            maxHeight: '100%',
            width: 'auto',
            height: 'auto',
            objectFit: 'contain',
            userSelect: 'none',
            transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
            transformOrigin: 'center center',
            transition: dragging ? 'none' : 'transform 0.12s cubic-bezier(0.23, 1, 0.32, 1)',
            '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
            borderRadius: zoom > 1 ? 0 : '12px',
            boxShadow: zoom > 1 ? 'none' : '0 24px 80px rgba(0,0,0,0.45)',
            pointerEvents: 'auto',
          }}
        />
      </Box>
      <Box
        sx={{
          position: 'absolute',
          bottom: { xs: 12, sm: 18 },
          left: 0,
          right: 0,
          textAlign: 'center',
          color: 'rgba(244,246,247,0.55)',
          fontSize: '0.75rem',
          pointerEvents: 'none',
          display: { xs: 'none', sm: 'block' },
        }}
      >
        Колёсико мыши или два пальца, чтобы приблизить. Esc закрывает.
      </Box>
    </Box>,
    document.body,
  );
}
