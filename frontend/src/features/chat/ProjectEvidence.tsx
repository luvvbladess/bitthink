import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Box, Button, Typography } from '@mui/material';
import { apiBlob, apiFetch } from '@/api/client';
import type { ProjectCitation } from './EvidenceLink';

type Evidence = { title: string; excerpt: string; revision: number; page: number | null; pdf_available: boolean; original_url: string | null };
export function ProjectEvidence({ citation }: { citation: ProjectCitation }) {
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const evidence = useQuery<Evidence>({ queryKey: ['project-evidence', citation], queryFn: () => apiFetch(`/projects/${citation.projectId}/entries/${citation.entryId}/evidence?revision=${citation.revision}&offset=${citation.offset}`) });
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  if (evidence.error) return <Alert severity="error">{evidence.error.message}</Alert>;
  const data = evidence.data;
  return <Box sx={{ mb: 2, p: 1.5, border: '1px solid var(--bt-hairline)', borderRadius: '12px' }}>
    <Typography sx={{ fontWeight: 600, fontSize: 14 }}>Фрагмент источника · версия {citation.revision}{data?.page ? ` · страница ${data.page}` : ''}</Typography>
    <Box component="blockquote" sx={{ mx: 0, my: 1, fontSize: 14, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 280, overflowY: 'auto' }}>{data?.excerpt || 'Загружаю сохранённый фрагмент…'}</Box>
    {data?.pdf_available && <Button size="small" disabled={busy} onClick={() => {
      if (url) { setUrl(''); return; }
      setBusy(true); setError('');
      void apiBlob(data.original_url!).then(blob => { if (alive.current) setUrl(URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))); }).catch(e => { if (alive.current) setError(e.message); }).finally(() => { if (alive.current) setBusy(false); });
    }}>{busy ? 'Открываю PDF…' : url ? 'Скрыть PDF' : 'Показать оригинал PDF'}</Button>}
    {url && <Box component="iframe" title="Исходный PDF" src={`${url}#page=${data?.page || 1}`} sx={{ display: 'block', mt: 1, width: '100%', height: { xs: 400, md: 560 }, border: 0 }} />}
    {error && <Alert severity="error">{error}</Alert>}
  </Box>;
}
