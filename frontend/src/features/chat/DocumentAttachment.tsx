import { Box, CircularProgress, IconButton, LinearProgress, Tooltip } from '@mui/material';
import { FileText, FilePdf, FileXls, FileDoc, CheckCircle, WarningCircle, Trash } from '@phosphor-icons/react';

export interface AttachmentInfo {
  name: string;
  size?: number;
  status: 'uploading' | 'done' | 'error';
  /** 0–100 while bytes or parse units are known. null = work started, total not known yet. */
  progress?: number | null;
  progressLabel?: string;
  type?: 'document' | 'image' | 'generated';
  mime_type?: string;
  url?: string;
  canvas?: boolean;
  files?: AttachmentInfo[];
  note?: string;
}

interface Props extends AttachmentInfo {
  onRemoveFromContext?: () => void;
}

function iconForFile(name: string) {
  const ext = name.split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return FilePdf;
  if (ext === 'docx' || ext === 'doc') return FileDoc;
  if (ext === 'pptx' || ext === 'ppt') return FileDoc;
  if (ext === 'xlsx' || ext === 'xls') return FileXls;
  return FileText;
}

function formatSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

export function DocumentAttachment({ name, size, status, type, url, note, progress, progressLabel, onRemoveFromContext }: Props) {
  const Icon = iconForFile(name);
  const isImage = type === 'image';
  const canDownload = status === 'done' && !!url && type !== 'image';
  const showProgress = status === 'uploading' && progress !== undefined;
  const progressValue = typeof progress === 'number' ? Math.max(0, Math.min(100, progress)) : 0;
  const card = (
    <Box
      sx={{
        display: 'inline-flex',
        flexDirection: showProgress ? 'column' : 'row',
        alignItems: showProgress ? 'stretch' : 'center',
        gap: 1.25,
        px: 1.5,
        py: 1,
        borderRadius: 2.5,
        border: '1px solid var(--bt-hairline)',
        bgcolor: 'var(--bt-overlay-faint)',
        maxWidth: 320,
        color: 'inherit',
        textDecoration: 'none',
        cursor: canDownload ? 'pointer' : 'default',
        '&:hover': canDownload ? { borderColor: 'primary.main', bgcolor: 'var(--bt-glow)' } : undefined,
      }}
        {...(canDownload ? { component: 'a' as const, href: url, download: name, rel: 'noopener' } : {})}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, minWidth: 0 }}>
      <Box
        sx={{
          width: isImage ? 48 : 34,
          height: isImage ? 48 : 34,
          borderRadius: 1.5,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          bgcolor: status === 'error' ? 'var(--bt-danger-soft)' : 'var(--bt-glow)',
          color: status === 'error' ? 'var(--bt-danger)' : 'primary.light',
        }}
      >
        {isImage && url ? (
          <Box component="img" src={url} alt="" sx={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <Icon size={18} weight="duotone" />
        )}
      </Box>
      <Box sx={{ minWidth: 0, flexGrow: 1 }}>
        <Box sx={{ fontSize: '0.8125rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {name}
        </Box>
        <Box sx={{ fontSize: '0.6875rem', color: 'text.muted' }}>
          {status === 'uploading' && (progressLabel || 'Загрузка...')}
          {status === 'done' && `${isImage ? 'Изображение' : note || (canDownload ? 'Скачать' : 'Документ')}${formatSize(size) ? ` · ${formatSize(size)}` : ''}`}
          {status === 'error' && 'Ошибка загрузки'}
        </Box>
      </Box>
      <Box sx={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: 0.5 }}>
        {status === 'uploading' && !showProgress && <CircularProgress size={16} thickness={5} sx={{ color: 'primary.light' }} />}
        {status === 'done' && <CheckCircle size={18} weight="fill" style={{ color: 'var(--bt-success)' }} />}
        {status === 'error' && <WarningCircle size={18} weight="fill" style={{ color: 'var(--bt-danger)' }} />}
        {status === 'done' && onRemoveFromContext && type !== 'generated' && (
          <Tooltip title="Удалить из контекста">
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onRemoveFromContext();
              }}
              sx={{
                color: 'text.secondary',
                p: 0.5,
                ml: 0.25,
                '&:hover': { color: 'var(--bt-danger)', bgcolor: 'var(--bt-danger-soft)' },
              }}
              aria-label="Удалить документ из контекста"
            >
              <Trash size={16} />
            </IconButton>
          </Tooltip>
        )}
      </Box>
      </Box>
      {showProgress && (
        <LinearProgress
          variant={progress === null ? 'indeterminate' : 'determinate'}
          value={progress === null ? undefined : progressValue}
          aria-label={progressLabel || 'Загрузка документа'}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress === null ? undefined : progressValue}
          sx={{
            height: 4,
            borderRadius: 99,
            bgcolor: 'var(--bt-overlay)',
            '& .MuiLinearProgress-bar': { borderRadius: 99, bgcolor: 'primary.main' },
          }}
        />
      )}
    </Box>
  );
  return card;
}
