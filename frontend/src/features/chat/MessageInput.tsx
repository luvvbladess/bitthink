import { useEffect, useRef, useState } from 'react';
import { Box, CircularProgress, IconButton, TextField, Tooltip } from '@mui/material';
import { File as FileIcon, PaperPlaneRight, Paperclip, Microphone, Stop, X } from '@phosphor-icons/react';
import { apiFormData } from '@/api/client';
import { ReasoningEffortSelector, SearchModeSelector, useIsComputer, useSelectedModel } from '@/components/ModelSelector';
import { composerIconBtnSx, composerShellSx } from '@/theme/effects';
import { DOCGEN_LABEL, PILOT_LABEL } from '@/constants/modes';

interface Props {
  onSend: (text: string, files?: File[], mode?: 'chat' | 'image') => Promise<boolean | void> | boolean | void;
  disabled?: boolean;
  isGenerating?: boolean;
  onStop?: () => void;
  editSourceUrl?: string | null;
  onClearEditSource?: () => void;
  imageModeRequest?: number;
}

type VoiceState = 'idle' | 'recording' | 'transcribing' | 'error';

const isSecureContext = typeof window !== 'undefined' && window.isSecureContext;
const hasRecorderApi =
  typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
const voiceSupported = isSecureContext && hasRecorderApi;

function PendingPreview({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [previewUrl, setPreviewUrl] = useState('');
  const isImage = file.type.startsWith('image/');
  useEffect(() => {
    if (!isImage) return;
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file, isImage]);
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 0.75,
        minWidth: 0,
        maxWidth: 220,
        px: 0.85,
        py: 0.65,
        border: '1px solid',
        borderColor: 'var(--bt-glow-strong)',
        borderRadius: '12px',
        bgcolor: 'var(--bt-glow)',
      }}
    >
      <Box
        sx={{
          width: 34,
          height: 34,
          borderRadius: '8px',
          overflow: 'hidden',
          flexShrink: 0,
          display: 'grid',
          placeItems: 'center',
          bgcolor: 'var(--bt-glow)',
          color: 'primary.light',
        }}
      >
        {previewUrl ? (
          <Box component="img" src={previewUrl} alt="" sx={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <FileIcon size={16} />
        )}
      </Box>
      <Box sx={{ minWidth: 0, fontSize: '0.75rem', color: 'text.primary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {file.name}
      </Box>
      <IconButton size="small" onClick={onRemove} aria-label={`Убрать ${file.name}`} sx={{ ml: 'auto', p: 0.25, color: 'text.secondary', '&:hover': { color: 'text.primary' } }}>
        <X size={13} />
      </IconButton>
    </Box>
  );
}

export function MessageInput({
  onSend,
  disabled,
  isGenerating,
  onStop,
  editSourceUrl,
  onClearEditSource,
  imageModeRequest = 0,
}: Props) {
  const [text, setText] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [imageMode, setImageMode] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const isComputer = useIsComputer();
  const selectedModel = useSelectedModel();
  const isStudio = selectedModel === 'studio';
  const isDocgen = selectedModel === 'docgen';
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const addFiles = (files: File[] | FileList | null) => {
    if (!files) return;
    setPendingFiles((current) => {
      const next = [...current];
      for (const file of Array.from(files)) {
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (!next.some((item) => `${item.name}:${item.size}:${item.lastModified}` === key)) next.push(file);
      }
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || submitting || (!text.trim() && !pendingFiles.length) || (imageMode && !text.trim())) return;
    setSubmitting(true);
    try {
      const result = await onSend(text.trim(), pendingFiles, imageMode ? 'image' : 'chat');
      if (result !== false) {
        setText('');
        setPendingFiles([]);
        inputRef.current?.focus();
      }
    } finally {
      setSubmitting(false);
    }
  };

  const failVoice = () => {
    setVoiceState('error');
    setTimeout(() => setVoiceState('idle'), 3000);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const mimeType = recorder.mimeType || 'audio/webm';
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        setVoiceState('transcribing');
        try {
          const ext = (mimeType.split('/')[1] || 'webm').split(';')[0] || 'webm';
          const formData = new FormData();
          formData.append('file', blob, `recording.${ext}`);
          const res = await apiFormData('/media/audio/transcribe', formData);
          if (!res.ok) throw new Error('transcribe failed');
          const data = await res.json();
          const transcribed = (data.text || '').trim();
          if (transcribed && !transcribed.startsWith('❌')) {
            setText((prev) => (prev.trim() ? `${prev.trim()} ${transcribed}` : transcribed));
            setVoiceState('idle');
          } else {
            failVoice();
          }
        } catch {
          failVoice();
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setVoiceState('recording');
    } catch {
      failVoice();
    }
  };

  const handleMicClick = () => {
    if (voiceState === 'idle') startRecording();
    else if (voiceState === 'recording') mediaRecorderRef.current?.stop();
  };

  const voiceLabel = !voiceSupported
    ? isSecureContext
      ? 'Голосовой ввод не поддерживается этим браузером'
      : 'Голосовой ввод доступен только по HTTPS'
    : voiceState === 'recording'
      ? 'Остановить запись'
      : voiceState === 'transcribing'
        ? 'Распознаём речь...'
        : voiceState === 'error'
          ? 'Не удалось распознать речь'
          : 'Голосовой ввод';

  useEffect(() => {
    if (imageModeRequest > 0 && !isStudio && !isDocgen) setImageMode(true);
  }, [imageModeRequest, isStudio, isDocgen]);

  useEffect(() => {
    if (isStudio || isDocgen) setImageMode(false);
  }, [isStudio, isDocgen]);

  const pendingImages = pendingFiles.filter((file) => file.type.startsWith('image/'));
  const editingImage = imageMode && (pendingImages.length > 0 || Boolean(editSourceUrl));
  const canSend = (text.trim() || pendingFiles.length > 0) && !disabled && !submitting && !(imageMode && !text.trim());

  return (
    <Box sx={{ width: '100%' }}>
    <Box
      component="form"
      onSubmit={handleSubmit}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (!disabled && e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
      }}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'visible',
        px: { xs: 1.5, sm: 1.75 },
        pt: { xs: 1.5, sm: 1.5 },
        pb: { xs: 1, sm: 1 },
        ...composerShellSx,
        ...(dragOver && {
          animation: 'none',
          bgcolor: 'var(--bt-glow)',
          borderColor: 'primary.light',
        }),
        ...(imageMode && !isComputer && {
          borderColor: 'var(--bt-line)',
        }),
        ...((isComputer || isDocgen) && {
          animation: 'none',
          borderColor: 'primary.main',
          boxShadow: 'var(--bt-composer-shadow-focus)',
          '@media (prefers-reduced-motion: no-preference)': {
            animation: 'none',
          },
        }),
      }}
    >
      <input
        type="file"
        ref={fileInputRef}
        multiple
        accept={imageMode ? 'image/*' : isDocgen ? '.doc,.docx,.pdf,.xls,.xlsx,.xlsm,.csv,.txt,.rtf,.odt,.zip' : undefined}
        style={{ display: 'none' }}
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = '';
        }}
      />
      {imageMode && editSourceUrl && pendingImages.length === 0 && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, pb: 1 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.75,
              minWidth: 0,
              px: 0.85,
              py: 0.55,
              border: '1px solid',
              borderColor: 'var(--bt-glow-strong)',
              borderRadius: '12px',
              bgcolor: 'var(--bt-glow)',
            }}
          >
            <Box
              component="img"
              src={editSourceUrl}
              alt=""
              sx={{ width: 34, height: 34, borderRadius: '8px', objectFit: 'cover', flexShrink: 0 }}
            />
            <Box sx={{ fontSize: '0.75rem', color: 'text.primary', whiteSpace: 'nowrap' }}>Правка этой картинки</Box>
            <IconButton
              size="small"
              onClick={() => onClearEditSource?.()}
              aria-label="Создать новое изображение"
              sx={{ ml: 'auto', p: 0.25, color: 'text.secondary', '&:hover': { color: 'text.primary' } }}
            >
              <X size={13} />
            </IconButton>
          </Box>
        </Box>
      )}
      {pendingFiles.length > 0 && (
        <Box sx={{ display: 'flex', gap: 0.75, overflowX: 'auto', pb: 1, scrollbarWidth: 'thin' }}>
          {pendingFiles.map((file, index) => (
            <PendingPreview
              key={`${file.name}-${file.size}-${file.lastModified}`}
              file={file}
              onRemove={() => setPendingFiles((items) => items.filter((_, itemIndex) => itemIndex !== index))}
            />
          ))}
        </Box>
      )}
      <TextField
        inputRef={inputRef as any}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          editingImage
            ? 'Что изменить на этой картинке?'
            : pendingFiles.length
              ? isDocgen
                ? 'Какой документ собрать по этим файлам?'
                : isStudio
                  ? 'Соберите по файлам: образец стиля и ТЗ...'
                  : 'Спросите о прикреплённых файлах...'
              : isDocgen
                ? 'Прикрепите шаблоны и данные, затем опишите документ...'
                : isComputer
                  ? 'Сделайте что угодно...'
                  : selectedModel === 'studio'
                    ? 'Образец PPTX и ТЗ или опишите слайды...'
                    : selectedModel === 'kimi-k2.6'
                      ? 'Что найти прямо сейчас?'
                      : selectedModel === 'gpt-6-astra'
                        ? 'Код, договор или задачу в песочницу...'
                        : selectedModel === 'gpt-6-sol' || selectedModel === 'gpt-5.6-sol' || selectedModel === 'gpt-5.6-terra'
                          ? 'Какую тему разобрать с источниками?'
                          : 'Спросите что угодно...'
        }
        fullWidth
        multiline
        minRows={1}
        maxRows={7}
        variant="standard"
        margin="none"
        hiddenLabel
        disabled={disabled}
        sx={{ m: 0 }}
        inputProps={{ 'aria-label': 'Сообщение' }}
        InputProps={{
          disableUnderline: true,
          sx: {
            mt: 0,
            px: { xs: 0.25, sm: 0.15 },
            py: 0,
            color: 'text.primary',
            fontSize: '1rem',
            '&:before, &:after': { display: 'none' },
            '& textarea': {
              resize: 'none',
              overflow: 'auto',
              lineHeight: 1.5,
              padding: 0,
              minHeight: '1.5em',
            },
            '& textarea::placeholder': {
              color: 'text.secondary',
              opacity: 1,
            },
          },
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
          }
        }}
        onPaste={(e) => {
          const files = Array.from(e.clipboardData.items)
            .filter((item) => item.kind === 'file')
            .map((item) => item.getAsFile())
            .filter((file): file is File => !!file);
          if (files.length) {
            e.preventDefault();
            addFiles(files);
          }
        }}
      />
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: { xs: 0.25, sm: 0.5 },
          mt: 1,
          minWidth: 0,
          width: '100%',
          overflow: 'visible',
        }}
      >
        <Tooltip title="Прикрепить файл" disableTouchListener enterDelay={500}>
          <IconButton
            size="small"
            onClick={() => fileInputRef.current?.click()}
            sx={composerIconBtnSx}
            aria-label="Прикрепить файл"
          >
            <Paperclip size={20} weight="bold" />
          </IconButton>
        </Tooltip>
        <SearchModeSelector />
        <Box sx={{ flex: '1 1 auto', minWidth: 8 }} />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 0.15, sm: 0.25 }, flexShrink: 0, ml: 'auto' }}>
        <ReasoningEffortSelector />

        <Tooltip title={voiceLabel} disableTouchListener enterDelay={500}>
          <span>
            <IconButton
              size="small"
              type="button"
              onClick={handleMicClick}
              disabled={disabled || !voiceSupported || voiceState === 'transcribing'}
              sx={{
                ...composerIconBtnSx,
                ...(voiceState === 'recording' && {
                  color: 'var(--bt-danger)',
                  bgcolor: 'var(--bt-danger-soft)',
                  animation: 'mic-pulse 1.4s ease-in-out infinite',
                  '@keyframes mic-pulse': {
                    '0%, 100%': { opacity: 1 },
                    '50%': { opacity: 0.5 },
                  },
                  '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
                }),
                ...(voiceState === 'error' && { color: 'var(--bt-danger)' }),
              }}
              aria-label={voiceLabel}
            >
              {voiceState === 'transcribing' ? (
                <CircularProgress size={18} sx={{ color: 'text.secondary' }} />
              ) : voiceState === 'recording' ? (
                <Stop size={16} weight="fill" />
              ) : (
                <Microphone size={20} weight="bold" />
              )}
            </IconButton>
          </span>
        </Tooltip>
        {isGenerating ? (
          <IconButton
            size="small"
            type="button"
            onPointerDown={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onStop?.();
            }}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onStop?.();
            }}
            aria-label="Остановить генерацию"
            sx={{
              ...composerIconBtnSx,
              width: { xs: 44, sm: 36 },
              height: { xs: 44, sm: 36 },
              borderRadius: '50%',
              bgcolor: 'var(--bt-overlay-strong)',
              color: 'text.primary',
              '&:hover': { bgcolor: 'var(--bt-overlay-strong)' },
            }}
          >
            <Stop size={15} weight="fill" />
          </IconButton>
        ) : (
          <IconButton
            size="small"
            type="submit"
            disabled={!canSend}
            aria-label="Отправить сообщение"
            sx={{
              ...composerIconBtnSx,
              width: { xs: 44, sm: 36 },
              height: { xs: 44, sm: 36 },
              borderRadius: '50%',
              bgcolor: canSend ? 'primary.main' : 'var(--bt-overlay)',
              color: canSend ? 'primary.contrastText' : 'text.muted',
              boxShadow: 'none',
              '&:hover': canSend
                ? { bgcolor: 'primary.dark' }
                : { bgcolor: 'var(--bt-overlay)' },
              '&:disabled': { bgcolor: 'var(--bt-overlay)', color: 'text.muted', boxShadow: 'none' },
            }}
          >
            {submitting ? <CircularProgress size={16} sx={{ color: 'inherit' }} /> : <PaperPlaneRight size={18} weight="fill" />}
          </IconButton>
        )}
        </Box>
      </Box>
    </Box>
      <Box
        sx={{
          display: isComputer || isStudio || isDocgen || imageMode ? 'block' : { xs: 'none', sm: 'block' },
          mt: 0.7,
          px: 0.75,
          fontSize: '0.75rem',
          lineHeight: 1.35,
          color: 'text.secondary',
          letterSpacing: '0.01em',
        }}
      >
        {editingImage
          ? 'Опишите правку. Картинка останется в этой беседе'
          : isDocgen
            ? `${DOCGEN_LABEL}: Word, PDF, Excel или zip — соберёт .docx. Перед запуском спросит подтверждение`
          : isStudio
            ? 'Готовый макет на холсте правится чатом. Можно прикрепить образец PPTX или PDF и файл ТЗ'
          : isComputer
            ? `${PILOT_LABEL} сам откроет сайты, почту или сервер`
            : 'Enter отправит · Shift+Enter новая строка'}
      </Box>
    </Box>
  );
}
