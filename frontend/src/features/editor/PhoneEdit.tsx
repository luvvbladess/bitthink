import { useState } from 'react';
import { Alert, Box, Button, CircularProgress, Drawer, IconButton, TextField, Typography } from '@mui/material';
import { Sparkle, X } from '@phosphor-icons/react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';

interface Paragraph {
  index: number;
  text: string;
  heading: boolean;
  in_table: boolean;
}

interface ParagraphList {
  version: number;
  paragraphs: Paragraph[];
  busy: string[];
}

/**
 * Phone editing. Free OnlyOffice only views documents on phones, so a clause is
 * picked from a list, rewritten here (by hand or with AI) and saved as a tracked
 * change: on a computer it shows as "was / now" and can be accepted or rejected.
 */
export function PhoneEdit({ docId, aiToken, onSaved }: { docId: string; aiToken: string; onSaved: (version: number) => void }) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Paragraph | null>(null);
  const [instruction, setInstruction] = useState('');
  const [draft, setDraft] = useState('');
  const [notice, setNotice] = useState('');
  const { data, isLoading, error, refetch } = useQuery<ParagraphList>({
    queryKey: ['editor-paragraphs', docId],
    queryFn: () => apiFetch(`/editor/${docId}/paragraphs`),
    refetchInterval: 20_000,
  });

  const generate = useMutation({
    mutationFn: () =>
      apiFetch(`/editor/${docId}/ai`, {
        method: 'POST',
        // The AI endpoint takes the per-document token, like the desktop plugin.
        headers: { Authorization: `Bearer ${aiToken}` },
        body: JSON.stringify({ selection: picked?.text || '', instruction }),
        timeoutMs: 120_000,
      }),
    onSuccess: (result: { text: string }) => setDraft((current) => result.text || current),
  });

  const save = useMutation({
    mutationFn: () =>
      apiFetch(`/editor/${docId}/paragraphs`, {
        method: 'POST',
        body: JSON.stringify({ index: picked?.index, base_text: picked?.text, text: draft }),
      }),
    onSuccess: (result: { version: number }) => {
      setPicked(null);
      setNotice('Правка сохранена в файл беседы. На компьютере её можно принять или отклонить.');
      queryClient.invalidateQueries({ queryKey: ['editor-paragraphs', docId] });
      queryClient.invalidateQueries({ queryKey: ['conversation-files'] });
      onSaved(result.version);
    },
    onError: () => refetch(),
  });

  const open = (paragraph: Paragraph) => {
    setPicked(paragraph);
    setDraft(paragraph.text);
    setInstruction('');
    generate.reset();
    save.reset();
  };

  const busy = data?.busy || [];

  return (
    <Box sx={{ position: 'absolute', inset: 0, overflowY: 'auto', bgcolor: 'background.default', px: 2, pt: 1.5, pb: 'calc(16px + env(safe-area-inset-bottom))' }}>
      {busy.length > 0 && (
        <Alert severity="info" sx={{ mb: 1.5 }}>
          Сейчас документ правят на компьютере: {busy.join(', ')}. Править с телефона можно будет, когда его закроют.
        </Alert>
      )}
      {notice && (
        <Alert severity="success" onClose={() => setNotice('')} sx={{ mb: 1.5 }}>
          {notice}
        </Alert>
      )}
      <Typography sx={{ fontSize: '0.8125rem', color: 'text.secondary', mb: 1.5 }}>
        Нажмите на пункт, чтобы переписать его сами или с ИИ.
      </Typography>
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}
      {error && <Alert severity="error">{(error as Error).message}</Alert>}
      {data?.paragraphs.map((paragraph) => (
        <Box
          key={paragraph.index}
          component="button"
          type="button"
          onClick={() => open(paragraph)}
          sx={{
            display: 'block',
            width: '100%',
            textAlign: 'left',
            font: 'inherit',
            color: 'text.primary',
            bgcolor: 'var(--bt-overlay-faint)',
            border: '1px solid var(--bt-hairline)',
            borderRadius: '12px',
            px: 1.5,
            py: 1.25,
            mb: 1,
            cursor: 'pointer',
            '&:active': { bgcolor: 'var(--bt-glow)' },
          }}
        >
          <Typography
            sx={{
              fontSize: paragraph.heading ? '0.9375rem' : '0.875rem',
              fontWeight: paragraph.heading ? 700 : 400,
              lineHeight: 1.45,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
            }}
          >
            {paragraph.text}
          </Typography>
          {paragraph.in_table && <Typography sx={{ fontSize: '0.6875rem', color: 'text.secondary', mt: 0.5 }}>ячейка таблицы</Typography>}
        </Box>
      ))}

      <Drawer
        anchor="bottom"
        open={Boolean(picked)}
        onClose={() => setPicked(null)}
        // Drawers sit under dialogs by default; this one opens from inside the editor dialog.
        sx={{ zIndex: (theme) => theme.zIndex.modal + 1 }}
        PaperProps={{ sx: { maxHeight: '92dvh', borderTopLeftRadius: 18, borderTopRightRadius: 18, pb: 'env(safe-area-inset-bottom)' } }}
      >
        {picked && (
          <Box sx={{ px: 2, pt: 1.5, pb: 2, overflowY: 'auto' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography sx={{ fontWeight: 700, flexGrow: 1 }}>Правка пункта</Typography>
              <IconButton onClick={() => setPicked(null)} aria-label="Закрыть" sx={{ width: 44, height: 44 }}>
                <X size={20} />
              </IconButton>
            </Box>
            <Typography sx={{ fontSize: '0.75rem', fontWeight: 600, color: 'text.secondary', mb: 0.5 }}>Было</Typography>
            <Box sx={{ fontSize: '0.8125rem', color: 'text.secondary', bgcolor: 'var(--bt-overlay-faint)', borderRadius: '10px', p: 1.25, mb: 1.5, maxHeight: 140, overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
              {picked.text}
            </Box>
            <TextField
              label="Что сделать (для ИИ)"
              placeholder="Например: срок оплаты 10 рабочих дней"
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              fullWidth
              multiline
              minRows={2}
              sx={{ mb: 1 }}
            />
            <Button
              onClick={() => generate.mutate()}
              disabled={!instruction.trim() || generate.isPending}
              startIcon={generate.isPending ? <CircularProgress size={16} /> : <Sparkle size={18} />}
              variant="outlined"
              fullWidth
              sx={{ minHeight: 44, mb: 1.5 }}
            >
              {generate.isPending ? 'Пишу вариант…' : 'Сгенерировать'}
            </Button>
            {generate.error && <Alert severity="error" sx={{ mb: 1.5 }}>{(generate.error as Error).message}</Alert>}
            <TextField
              label="Станет"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              fullWidth
              multiline
              minRows={4}
              sx={{ mb: 1.5 }}
            />
            {save.error && <Alert severity="warning" sx={{ mb: 1.5 }}>{(save.error as Error).message}</Alert>}
            <Button
              onClick={() => save.mutate()}
              disabled={!draft.trim() || draft === picked.text || save.isPending || busy.length > 0}
              variant="contained"
              fullWidth
              sx={{ minHeight: 48 }}
            >
              {save.isPending ? 'Сохраняю…' : 'Вставить как правку'}
            </Button>
          </Box>
        )}
      </Drawer>
    </Box>
  );
}
