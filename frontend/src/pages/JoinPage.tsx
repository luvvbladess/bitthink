import { useEffect, useState } from 'react';
import { Box, Typography } from '@mui/material';
import { useNavigate, useParams } from 'react-router-dom';
import { apiFetch } from '@/api/client';

export default function JoinPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    apiFetch(`/share/${token}/join`, { method: 'POST' })
      .then((data: { id: string }) => {
        if (!cancelled) navigate(`/chat?c=${encodeURIComponent(data.id)}`, { replace: true });
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || 'Ссылка недействительна');
      });
    return () => {
      cancelled = true;
    };
  }, [token, navigate]);

  return (
    <Box sx={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center', px: 3 }}>
      <Typography sx={{ color: error ? 'var(--bt-danger)' : 'text.secondary' }}>
        {error || 'Открываю общий диалог…'}
      </Typography>
    </Box>
  );
}
