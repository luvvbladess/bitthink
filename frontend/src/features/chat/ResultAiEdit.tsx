import { useState } from 'react';
import { Alert, Box, Button, Stack, TextField, Typography } from '@mui/material';
import { apiFetch } from '@/api/client';

export type EditTarget = { row_id?: string; slide_id?: string; start?: number; end?: number };
type Proposal = { expected_revision: number; changes: Record<string, unknown>[]; preview: { label: string; before: string; after: string }[] };

export function ResultAiEdit({ projectId, entryId, revision, target, onClose, onApplied }: {
  projectId: string; entryId: string; revision: number; target: EditTarget; onClose: () => void; onApplied: (value: { revision: number }) => void;
}) {
  const [instruction, setInstruction] = useState('');
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const preview = async () => {
    setBusy(true); setError('');
    try { setProposal(await apiFetch(`/projects/${projectId}/results/${entryId}/edit-preview`, {
      method: 'POST', body: JSON.stringify({ expected_revision: revision, target, instruction }), timeoutMs: 70000,
    })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const apply = async () => {
    if (!proposal) return;
    setBusy(true); setError('');
    try {
      const result = await apiFetch(`/projects/${projectId}/results/${entryId}/patch`, { method: 'POST', body: JSON.stringify(proposal) }) as { revision: number };
      onApplied(result);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <Box component="section" aria-label="Точечная правка ИИ" sx={{ my: 2, p: 2, border: '1px solid var(--bt-hairline)', borderRadius: '12px' }}>
    <Typography sx={{ fontWeight: 600, mb: .75 }}>Изменить выбранный фрагмент</Typography>
    <Typography sx={{ fontSize: 12, color: 'text.secondary', mb: 1.5 }}>Остальные части результата сохранятся. Правка использует лимит тарифа и не проверяет актуальность фактов в интернете.</Typography>
    <TextField autoFocus fullWidth multiline minRows={2} label="Что изменить?" value={instruction} disabled={busy}
      inputProps={{ maxLength: 2000 }} onChange={e => { setInstruction(e.target.value); setProposal(null); }} />
    {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
    {proposal && <Stack gap={1.5} sx={{ mt: 2 }}>{proposal.preview.map((item, index) => <Box key={index}>
      <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{item.label}</Typography>
      <Typography sx={{ mt: .5, fontSize: 12, color: 'text.secondary' }}>Было</Typography>
      <Box sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 14, maxHeight: 200, overflow: 'auto' }}>{item.before || 'Пусто'}</Box>
      <Typography sx={{ mt: 1, fontSize: 12, color: 'primary.light' }}>Предлагается</Typography>
      <Box sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 14, maxHeight: 240, overflow: 'auto' }}>{item.after || 'Удалить выделенное'}</Box>
    </Box>)}</Stack>}
    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mt: 2 }}>
      {proposal ? <Button size="small" disabled={busy} onClick={() => void apply()}>Применить изменения</Button>
        : <Button size="small" disabled={busy || !instruction.trim()} onClick={() => void preview()}>{busy ? 'Готовлю правку…' : 'Предложить правку'}</Button>}
      <Button size="small" color="inherit" disabled={busy} onClick={onClose}>Отмена</Button>
    </Stack>
  </Box>;
}
