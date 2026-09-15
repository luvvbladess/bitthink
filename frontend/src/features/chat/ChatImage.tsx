import { useState, type MouseEvent, type ReactNode } from 'react';
import { Box } from '@mui/material';
import { DownloadSimple, MagnifyingGlassPlus, PencilSimple, Trash } from '@phosphor-icons/react';
import { ImageLightbox } from './ImageLightbox';
import { downloadChatImage, imageDownloadName } from './chatImages';
import { HOVER_FINE } from '@/theme/effects';

type Props = {
  src: string;
  alt?: string;
  onEdit?: () => void;
  onRemove?: () => void;
};

function ActionChip({
  label,
  onClick,
  icon,
}: {
  label: string;
  onClick: () => void;
  icon: ReactNode;
}) {
  return (
    <Box
      component="button"
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      aria-label={label}
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.6,
        minHeight: 36,
        px: 1.1,
        py: 0.45,
        border: '1px solid var(--bt-hairline)',
        borderRadius: '999px',
        bgcolor: 'var(--bt-panel)',
        color: 'text.primary',
        fontSize: '0.75rem',
        fontWeight: 600,
        cursor: 'pointer',
        boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
        [HOVER_FINE]: { '&:hover': { bgcolor: 'background.paper' } },
        '&:active': { transform: 'scale(0.97)' },
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: 2,
        },
      }}
    >
      {icon}
      {label}
    </Box>
  );
}

export function ChatImage({ src, alt, onEdit, onRemove }: Props) {
  const [open, setOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async (event?: MouseEvent) => {
    event?.stopPropagation();
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
  };

  const openViewer = () => setOpen(true);

  return (
    <>
      <Box
        sx={{
          position: 'relative',
          my: 1.25,
          maxWidth: { xs: '100%', sm: 420 },
          borderRadius: '16px',
          overflow: 'hidden',
          border: '1px solid var(--bt-hairline)',
          bgcolor: 'var(--bt-overlay-faint)',
          cursor: 'zoom-in',
          '& .image-actions': { opacity: { xs: 1, md: 0 } },
          [HOVER_FINE]: {
            '&:hover .image-actions': { opacity: 1 },
          },
        }}
      >
        <Box
          component="img"
          src={src}
          alt={alt || ''}
          draggable={false}
          role="button"
          tabIndex={0}
          aria-label={alt ? `Открыть изображение: ${alt}` : 'Открыть изображение на весь экран'}
          onClick={openViewer}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              openViewer();
            }
          }}
          sx={{ width: '100%', display: 'block', verticalAlign: 'middle' }}
        />
        <Box
          className="image-actions"
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            p: 1.1,
            pointerEvents: 'none',
            background: 'linear-gradient(180deg, rgba(8,12,14,0.28) 0%, transparent 28%, transparent 58%, rgba(8,12,14,0.42) 100%)',
            '& button': { pointerEvents: 'auto' },
          }}
        >
          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <ActionChip
              label="Открыть"
              icon={<MagnifyingGlassPlus size={14} weight="bold" />}
              onClick={openViewer}
            />
          </Box>
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
            {onEdit && (
              <ActionChip
                label="Изменить"
                icon={<PencilSimple size={14} weight="bold" />}
                onClick={onEdit}
              />
            )}
            <ActionChip
              label={downloading ? 'Скачиваю' : 'Скачать'}
              icon={<DownloadSimple size={14} weight="bold" />}
              onClick={() => void handleDownload()}
            />
            {onRemove && (
              <ActionChip
                label="Убрать"
                icon={<Trash size={14} weight="bold" />}
                onClick={onRemove}
              />
            )}
          </Box>
        </Box>
      </Box>
      {open && (
        <ImageLightbox src={src} alt={alt} onClose={() => setOpen(false)} onEdit={onEdit} />
      )}
    </>
  );
}
