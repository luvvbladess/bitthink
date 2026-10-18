import { useState } from 'react';
import { Alert, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';

type Rule = { id: number; name: string; event: string; action: string; value: string };
export function ComputerRulesSection() {
  const client = useQueryClient();
  const [kind, setKind] = useState('instruction');
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const query = useQuery<Rule[]>({ queryKey: ['computer-hooks'], queryFn: () => apiFetch('/computer/hooks') });
  const save = useMutation({ mutationFn: () => apiFetch('/computer/hooks', { method: 'POST', body: JSON.stringify({ name, value, action: kind, event: kind === 'instruction' ? 'before_task' : kind === 'deny' ? 'before_tool' : 'after_tool' }) }),
    onSuccess: () => { setError(''); setName(''); setValue(''); client.invalidateQueries({ queryKey: ['computer-hooks'] }); }, onError: (e: Error) => setError(e.message) });
  const remove = useMutation({ mutationFn: (id: number) => apiFetch(`/computer/hooks/${id}`, { method: 'DELETE' }), onSuccess: () => client.invalidateQueries({ queryKey: ['computer-hooks'] }), onError: (e: Error) => setError(e.message) });
  return <Stack spacing={2}>
    <Stack component="form" spacing={1.5} onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <TextField label="Название правила" value={name} onChange={e => setName(e.target.value)} required />
      <TextField select label="Действие" value={kind} onChange={e => { setKind(e.target.value); setValue(''); }}>
        <MenuItem value="instruction">Инструкция перед фоновой задачей</MenuItem><MenuItem value="deny">Запрет инструмента</MenuItem><MenuItem value="limit">Ограничение объёма ответа инструмента</MenuItem>
      </TextField>
      <TextField label={kind === 'instruction' ? 'Инструкция' : kind === 'deny' ? 'Имена инструментов через запятую' : 'Максимум символов (200–12000)'} multiline={kind === 'instruction'} minRows={kind === 'instruction' ? 3 : 1} value={value} onChange={e => setValue(e.target.value)} required helperText={kind === 'deny' ? 'Например: gmail_send, ssh_run, mcp_call' : undefined} />
      <Button type="submit" variant="outlined" disabled={save.isPending || !name.trim() || !value.trim()} sx={{ alignSelf: 'flex-start' }}>Добавить правило</Button>
    </Stack>
    {(query.data || []).map(rule => <Stack key={rule.id} direction="row" alignItems="flex-start" justifyContent="space-between" gap={2} sx={{ pt: 2, borderTop: '1px solid var(--bt-hairline)' }}>
      <Stack sx={{ minWidth: 0 }}><Typography fontWeight={600}>{rule.name}</Typography><Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{rule.value}</Typography></Stack>
      <Button disabled={remove.isPending} onClick={() => remove.mutate(rule.id)}>Удалить</Button>
    </Stack>)}
    {(error || query.error) && <Alert severity="error">{error || query.error?.message}</Alert>}
  </Stack>;
}
