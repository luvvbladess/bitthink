import { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Button,
  Box,
  CircularProgress,
  Alert,
  useTheme,
} from '@mui/material';
import { apiFetch } from '@/api/client';

interface Props {
  open: boolean;
  onClose: () => void;
  onGenerated?: (imageUrl: string) => void;
}

export function ImageGenerationDialog({ open, onClose, onGenerated }: Props) {
  const theme = useTheme();
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const data = await apiFetch('/media/images/generate', {
        method: 'POST',
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      if (data.url) {
        setResult(data.url);
        onGenerated?.(data.url);
      } else {
        setError('Не удалось сгенерировать изображение');
      }
    } catch (e: any) {
      setError(e.message || 'Ошибка');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth PaperProps={{ sx: { bgcolor: theme.palette.surface.elevated, border: '1px solid var(--bt-hairline)' } }}>
      <DialogTitle>Генерация изображения</DialogTitle>
      <DialogContent>
        <TextField
          label="Описание изображения"
          multiline
          rows={3}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          fullWidth
          sx={{ mt: 1 }}
        />
        {error && <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>{error}</Alert>}
        {result && (
          <Box sx={{ mt: 2, borderRadius: 3, overflow: 'hidden', border: '1px solid var(--bt-hairline)' }}>
            <img src={result} alt="generated" style={{ width: '100%', display: 'block' }} />
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} sx={{ color: 'text.secondary' }}>
          Закрыть
        </Button>
        <Button onClick={handleGenerate} disabled={loading || !prompt.trim()} variant="contained">
          {loading ? <CircularProgress size={20} /> : 'Сгенерировать'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
