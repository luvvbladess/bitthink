import { useState } from 'react';
import { Alert, Box, Button, Checkbox, Collapse, FormControlLabel, Stack, TextField, Typography } from '@mui/material';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '@/api/client';

type Connector = { id: number; type: string; name: string; hint: string };
type Tool = { name: string; description: string; enabled: boolean };

export function MCPSection({ compact = false }: { compact?: boolean }) {
  const client = useQueryClient();
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(!compact);
  const [tools, setTools] = useState<Record<number, Tool[]>>({});
  const [selected, setSelected] = useState<Record<number, string[]>>({});
  const query = useQuery<Connector[]>({ queryKey: ['connectors'], queryFn: () => apiFetch('/connectors') });
  const action = useMutation({
    mutationFn: async ({ kind, id }: { kind: 'add' | 'discover' | 'save' | 'delete'; id?: number }) => {
      if (kind === 'add') return apiFetch('/connectors', { method: 'POST', body: JSON.stringify({ type: 'mcp', name, payload: { url, token, allowed_tools: [] } }) });
      if (kind === 'delete') return apiFetch(`/connectors/${id}`, { method: 'DELETE' });
      if (kind === 'save') return apiFetch(`/connectors/${id}/mcp/tools`, { method: 'PATCH', body: JSON.stringify({ allowed_tools: selected[id!] || [] }) });
      const result = await apiFetch(`/connectors/${id}/mcp/discover`, { method: 'POST' });
      setTools(previous => ({ ...previous, [id!]: result.tools }));
      setSelected(previous => ({ ...previous, [id!]: result.tools.filter((t: Tool) => t.enabled).map((t: Tool) => t.name) }));
      return result;
    },
    onSuccess: (_, args) => { setError(''); client.invalidateQueries({ queryKey: ['connectors'] }); if (args.kind === 'add') { setName(''); setUrl(''); setToken(''); if (compact) setAdding(false); } },
    onError: (e: Error) => setError(e.message),
  });
  return <Stack spacing={2}>
    {compact ? <Stack direction="row" alignItems="center" justifyContent="space-between" gap={1}><Typography sx={{ fontSize: 14, fontWeight: 600 }}>Внешние инструменты</Typography><Button size="small" onClick={() => setAdding(value => !value)}>{adding ? 'Скрыть' : 'Добавить'}</Button></Stack> : <Typography variant="body2" color="text.secondary">Подключите MCP-сервер и выберите инструменты для Оркестратора.</Typography>}
    <Collapse in={adding} unmountOnExit>
    <Stack component="form" spacing={1.5} onSubmit={e => { e.preventDefault(); action.mutate({ kind: 'add' }); }}>
      <TextField label="Название" value={name} onChange={e => setName(e.target.value)} required inputProps={{ maxLength: 80 }} />
      <TextField label="Адрес MCP-сервера" type="url" value={url} onChange={e => setUrl(e.target.value)} required placeholder="https://example.com/mcp" />
      <TextField label="Токен доступа (если требуется)" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} />
      <Button type="submit" variant="outlined" disabled={action.isPending || !name.trim() || !url.trim()} sx={{ alignSelf: 'flex-start' }}>Подключить</Button>
    </Stack>
    </Collapse>
    {compact && !adding && !query.isLoading && !query.data?.some(c => c.type === 'mcp') && <Typography sx={{ fontSize: 13, color: 'text.secondary' }}>Подключите сервис через MCP, когда понадобятся дополнительные инструменты.</Typography>}
    {(query.data || []).filter(c => c.type === 'mcp').map(c => <Box key={c.id} sx={{ pt: 2, borderTop: '1px solid var(--bt-hairline)' }}>
      <Typography fontWeight={600} sx={{ overflowWrap: 'anywhere' }}>{c.name}</Typography><Typography variant="body2" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>{c.hint}</Typography>
      <Stack direction="row" gap={1} flexWrap="wrap"><Button disabled={action.isPending} onClick={() => action.mutate({ kind: 'discover', id: c.id })}>Проверить и выбрать инструменты</Button><Button color="inherit" disabled={action.isPending} onClick={() => action.mutate({ kind: 'delete', id: c.id })}>Отключить</Button></Stack>
      {tools[c.id] && <Stack>
        {tools[c.id].length === 0 && <Typography variant="body2">Сервер не предоставил инструменты.</Typography>}
        {tools[c.id].map(t => <FormControlLabel key={t.name} control={<Checkbox checked={(selected[c.id] || []).includes(t.name)} onChange={(_, on) => setSelected(previous => ({ ...previous, [c.id]: on ? [...(previous[c.id] || []), t.name] : (previous[c.id] || []).filter(n => n !== t.name) }))} />} label={<Box sx={{ overflowWrap: 'anywhere' }}><Typography variant="body2">{t.name}</Typography><Typography variant="caption" color="text.secondary">{t.description}</Typography></Box>} />)}
        <Button sx={{ alignSelf: 'flex-start' }} disabled={action.isPending} onClick={() => action.mutate({ kind: 'save', id: c.id })}>Сохранить доступ</Button>
      </Stack>}
    </Box>)}
    {(error || query.error) && <Alert severity="error" onClose={() => setError('')}>{error || query.error?.message}</Alert>}
  </Stack>;
}
