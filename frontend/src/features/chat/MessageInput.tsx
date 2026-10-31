import { useEffect, useRef, useState } from 'react';
import { Box, Button, CircularProgress, Drawer, IconButton, TextField, Tooltip } from '@mui/material';
import { File as FileIcon, PaperPlaneRight, Paperclip, Microphone, Stop, X } from '@phosphor-icons/react';
import { useComposerDraft } from './useComposerDraft';
import { useVoiceInput } from './useVoiceInput';
import { ReasoningEffortSelector, SearchModeSelector, useIsComputer, useSelectedModel, useModePreferencesBusy, useModePreferenceError, useModelsQuery } from '@/components/ModelSelector';
import { composerIconBtnSx, composerShellSx } from '@/theme/effects';
import { DOCGEN_LABEL, PILOT_LABEL } from '@/constants/modes';
import { OrchestratorTools } from './OrchestratorTools';
import { useVisualViewportHeight } from './useVisualViewportHeight';

interface Props {
  starterPrompt?: string | null; onStarterApplied?: () => void;
  onSend: (text: string, files?: File[], mode?: 'chat' | 'image') => Promise<boolean | void> | boolean | void;
  disabled?: boolean;
  isGenerating?: boolean;
  onStop?: () => void;
  editSourceUrl?: string | null;
  onClearEditSource?: () => void;
  imageModeRequest?: number;
  conversationId?: string | null;
  onOpenProjects?: () => void;
  selectionQuote?: { text: string } | null;
  onClearSelectionQuote?: () => void;
}

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
      <IconButton size="small" onClick={onRemove} aria-label={`Убрать ${file.name}`} sx={{ ml: 'auto', minWidth: 44, minHeight: 44, color: 'text.secondary', '&:hover': { color: 'text.primary' } }}>
        <X size={13} />
      </IconButton>
    </Box>
  );
}

export function MessageInput({
  starterPrompt, onStarterApplied,
  onSend,
  disabled,
  isGenerating,
  onStop,
  editSourceUrl,
  onClearEditSource,
  imageModeRequest = 0,
  conversationId,
  onOpenProjects,
  selectionQuote,
  onClearSelectionQuote,
}: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [imageMode, setImageMode] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const viewportHeight = useVisualViewportHeight();
  const [submitting, setSubmitting] = useState(false);
  const preferencesBusy = useModePreferencesBusy();
  const { data: confirmedSettings } = useModelsQuery();
  const preferenceError = useModePreferenceError();
  const { text, setText, pendingFiles, setPendingFiles, submission, restoring, storageWarning } = useComposerDraft(conversationId);
  useEffect(() => { if (starterPrompt && !restoring) { setText(previous => previous.trim() ? `${previous}\n\n${starterPrompt}` : starterPrompt); onStarterApplied?.(); inputRef.current?.focus(); } }, [starterPrompt, restoring]);
  const { voiceState, handleMicClick } = useVoiceInput(conversationId, transcribed => {
    setText(previous => previous.trim() ? `${previous.trim()} ${transcribed}` : transcribed);
  }, !disabled);
  const sendingRef = useRef(false);
  const isComputer = useIsComputer();
  const selectedModel = useSelectedModel();
  const isStudio = selectedModel === 'studio';
  const isDocgen = selectedModel === 'docgen';
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const [attachmentMenu, setAttachmentMenu] = useState(false);

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
    if (!confirmedSettings || (imageMode && (pendingFiles.some(file => !file.type.startsWith('image/')) || pendingFiles.length > 8)) || preferencesBusy || restoring || disabled || sendingRef.current || ['starting', 'recording', 'transcribing'].includes(voiceState) || (!text.trim() && !pendingFiles.length) || (imageMode && !text.trim())) return;
    sendingRef.current = true;
    setSubmitting(true);
    const acceptDraft = submission();
    try {
      const question = text.trim();
      const message = selectionQuote ? `Уточни по выделенному фрагменту предыдущего ответа:\n\n${selectionQuote.text.split('\n').map(line => `> ${line}`).join('\n')}\n\n${question}` : question;
      const result = await onSend(message, pendingFiles, imageMode && !selectionQuote ? 'image' : 'chat');
      if (result !== false) {
        acceptDraft();
        if (selectionQuote) onClearSelectionQuote?.();
        // «Править эту картинку» – одноразовый режим: иначе следующее фото
        // с текстом в любом режиме уйдёт в редактор картинок, а не в чат.
        setImageMode(false);
        inputRef.current?.focus();
      }
    } finally {
      sendingRef.current = false;
      setSubmitting(false);
    }
  };

  const voiceLabel = !voiceSupported
    ? isSecureContext
      ? 'Голосовой ввод не поддерживается этим браузером'
      : 'Голосовой ввод доступен только по HTTPS'
    : voiceState === 'starting'
      ? 'Разрешите доступ к микрофону'
    : voiceState === 'recording'
      ? 'Остановить запись'
      : voiceState === 'transcribing'
        ? 'Распознаём речь...'
        : voiceState === 'error'
          ? 'Не удалось распознать речь'
          : 'Голосовой ввод';

  useEffect(() => {
    if (imageModeRequest > 0 && !isDocgen) setImageMode(true);
  }, [imageModeRequest, isDocgen]);

  // Сменили режим – правка картинки не должна тянуться за человеком в другой режим.
  useEffect(() => {
    setImageMode(false);
    setToolsOpen(false);
    onClearEditSource?.();
  }, [selectedModel, conversationId]);

  const pendingImages = pendingFiles.filter((file) => file.type.startsWith('image/'));
  const editingImage = imageMode && (pendingImages.length > 0 || Boolean(editSourceUrl));
  useEffect(() => {
    if (selectionQuote) { setImageMode(false); inputRef.current?.focus(); }
  }, [selectionQuote]);

  const imageInputError = imageMode && pendingFiles.some(file => !file.type.startsWith('image/'))
    ? 'Для правки картинки подходят только изображения. Уберите остальные файлы или вернитесь к чату.'
    : imageMode && pendingImages.length > 8 ? 'Для правки можно добавить до 8 изображений. Уберите лишние.' : '';
  const canSend = (text.trim() || pendingFiles.length > 0) && !!confirmedSettings && !imageInputError && !preferencesBusy && !restoring && !disabled && !submitting && !['starting', 'recording', 'transcribing'].includes(voiceState) && !(imageMode && !text.trim());

  return (
    <Box sx={{ width: '100%', '&:focus-within .bt-key-hint': { opacity: 1 } }}>
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
        overflowY: 'auto',
        maxHeight: `${Math.max(140, viewportHeight - 80)}px`,
        minHeight: 0,
        flexShrink: 0,
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
      {imageMode && <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}><Box sx={{ fontSize: 12, color: 'text.secondary' }}>Правка изображения</Box><Button size="small" color="inherit" onClick={() => { setImageMode(false); onClearEditSource?.(); }}>Вернуться к чату</Button></Box>}
      {imageInputError && <Box role="alert" sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>{imageInputError}</Box>}
      {storageWarning && <Box role="status" sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>{storageWarning}</Box>}
      {preferenceError && <Box role="alert" sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>{preferenceError}</Box>}
      {preferencesBusy && <Box role="status" sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>Сохраняем настройки режима…</Box>}
      {restoring && <Box role="status" sx={{ fontSize: 12, color: 'text.secondary', mb: 1 }}>Восстанавливаем черновик…</Box>}
      <input
        type="file"
        ref={fileInputRef}
        aria-label="Файлы для сообщения"
        multiple
        accept={imageMode ? 'image/*' : undefined}
        style={{ display: 'none' }}
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = '';
        }}
      />
      <input hidden type="file" accept="image/*" capture="environment" ref={cameraInputRef} aria-label="Снять фото документа" onChange={event => { addFiles(event.target.files); event.target.value = ''; }} />
      <input hidden type="file" accept="image/*" multiple ref={photoInputRef} aria-label="Выбрать фотографии" onChange={event => { addFiles(event.target.files); event.target.value = ''; }} />
      <Drawer anchor="bottom" open={attachmentMenu} onClose={() => setAttachmentMenu(false)} PaperProps={{ sx: { p: 1.5, pb: 'max(12px, env(safe-area-inset-bottom))', borderRadius: '16px 16px 0 0' } }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}><Box sx={{ fontWeight: 600 }}>Добавить к вопросу</Box><IconButton aria-label="Закрыть выбор вложения" onClick={() => setAttachmentMenu(false)} sx={{ width: 44, height: 44 }}><X size={20} /></IconButton></Box>
        {[
          ['Снять фото', cameraInputRef], ['Выбрать фото', photoInputRef], ['Прикрепить файл', fileInputRef],
        ].map(([label, ref]) => <Button key={String(label)} onClick={() => { (ref as typeof fileInputRef).current?.click(); setAttachmentMenu(false); }} sx={{ justifyContent: 'flex-start', minHeight: 48, color: 'text.primary' }}>{String(label)}</Button>)}
      </Drawer>
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
              onClick={() => { setImageMode(false); onClearEditSource?.(); }}
              aria-label="Создать новое изображение"
              sx={{ ml: 'auto', minWidth: 44, minHeight: 44, color: 'text.secondary', '&:hover': { color: 'text.primary' } }}
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
      {selectionQuote && <Box component="section" aria-label="Выбранный фрагмент" sx={{ mb: 1.25, p: 1.25, borderRadius: '10px', bgcolor: 'var(--bt-overlay-faint)', minWidth: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, fontSize: 12, color: 'text.secondary' }}>
          Уточнение по фрагменту
          <IconButton size="small" type="button" aria-label="Убрать цитату" disabled={submitting} onClick={onClearSelectionQuote} sx={{ width: 44, height: 44 }}><X size={15} /></IconButton>
        </Box>
        <Box component="blockquote" sx={{ m: 0, mt: .5, maxHeight: 72, overflowY: 'auto', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13, lineHeight: 1.5 }}>{selectionQuote.text}</Box>
      </Box>}
      <TextField
        inputRef={inputRef as any}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          selectionQuote
            ? 'Что уточнить об этом фрагменте?'
            : editingImage
            ? 'Что изменить на этой картинке?'
            : pendingFiles.length
              ? isDocgen
                ? 'Какой документ собрать по этим файлам?'
                : isStudio
                  ? 'Что создать по этим материалам?'
                  : 'Спросите о прикреплённых файлах...'
              : isDocgen
                ? 'Прикрепите шаблоны и данные, затем опишите документ...'
                : isComputer
                  ? 'Какой результат нужен? Можно прикрепить файлы…'
                  : selectedModel === 'studio'
                    ? 'Опишите, что создать или изменить…'
                    : selectedModel === 'kimi-k2.6'
                      ? 'Что найти прямо сейчас?'
                      : selectedModel === 'gpt-6-astra'
                        ? 'Прикрепите материалы или опишите сложную задачу…'
                        : selectedModel === 'gpt-6-sol' || selectedModel === 'gpt-5.6-sol' || selectedModel === 'gpt-5.6-terra'
                          ? 'Какую тему разобрать с источниками?'
                          : 'Спросите что угодно...'
        }
        fullWidth
        multiline
        minRows={1}
        maxRows={toolsOpen ? (viewportHeight < 480 ? 1 : 3) : viewportHeight < 480 ? 3 : 7}
        variant="standard"
        margin="none"
        hiddenLabel
        disabled={restoring || disabled || submitting}
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
          // Screen keyboards need Enter for paragraphs. Ctrl/Cmd+Enter remains
          // available on tablets and touch laptops with a physical keyboard.
          if (window.matchMedia('(pointer: coarse)').matches && !e.ctrlKey && !e.metaKey) return;
          if (e.key === 'Enter' && !e.shiftKey && !(e.nativeEvent as KeyboardEvent).isComposing && e.keyCode !== 229) {
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
            onClick={() => { if (window.matchMedia('(pointer: coarse)').matches && !isDocgen) setAttachmentMenu(true); else fileInputRef.current?.click(); }}
            disabled={restoring || disabled || submitting}
            sx={composerIconBtnSx}
            aria-label="Прикрепить файл"
          >
            <Paperclip size={20} weight="bold" />
          </IconButton>
        </Tooltip>
        <SearchModeSelector disabled={submitting} />
        <Box sx={{ flex: '1 1 auto', minWidth: 8 }} />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 0.15, sm: 0.25 }, flexShrink: 0, ml: 'auto' }}>
        <ReasoningEffortSelector disabled={submitting} />

        <Tooltip title={voiceLabel} disableTouchListener enterDelay={500}>
          <span>
            <IconButton
              size="small"
              type="button"
              onClick={handleMicClick}
              disabled={restoring || disabled || submitting || !voiceSupported || voiceState === 'starting' || voiceState === 'transcribing'}
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
              {voiceState === 'transcribing' || voiceState === 'starting' ? (
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
        className="bt-key-hint"
        sx={{
          display: toolsOpen && viewportHeight < 480 ? 'none' : isComputer ? 'none' : isStudio || isDocgen || imageMode ? 'block' : { xs: 'none', sm: 'block' },
          // The plain Enter/Shift+Enter reminder shows while typing; the mode explanations stay.
          opacity: isComputer || isStudio || isDocgen || imageMode || editingImage ? 1 : 0,
          transition: 'opacity 0.2s cubic-bezier(0.23, 1, 0.32, 1)',
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
            ? `${DOCGEN_LABEL}: Word, PDF, Excel или zip — соберёт .docx или целый комплект файлов. Перед запуском покажет состав и спросит подтверждение`
          : isStudio
            ? 'Опишите идею своими словами. Файлы и образцы — по желанию.'
          : isComputer
            ? `${PILOT_LABEL}: выполняет задачи с файлами, поиском и инструментами`
            : 'Enter отправит · Shift+Enter новая строка'}
      </Box>
      {isComputer && <OrchestratorTools draft={text} hasFiles={pendingFiles.length > 0} conversationId={conversationId} onOpenProjects={onOpenProjects} onOpenChange={setToolsOpen} />}
    </Box>
  );
}
