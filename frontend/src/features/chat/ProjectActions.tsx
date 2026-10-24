import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, IconButton, ListItemIcon, Menu, MenuItem, TextField, Tooltip } from '@mui/material';
import { DotsThree, PencilSimple, Trash } from '@phosphor-icons/react';
import { apiFetch } from '@/api/client';

export type ProjectDeleted = (id: string, cleanupPending?: boolean) => void;

/** The same management actions in the sidebar and in the project workspace. */
export function ProjectActions({ project, onDeleted, compact = false }: { project: { id: string; name: string }; onDeleted?: ProjectDeleted; compact?: boolean }) {
  const client = useQueryClient();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null);
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const close = () => { if (!busy) { setDialog(null); setError(''); } };
  const open = (mode: 'rename' | 'delete') => { setAnchor(null); setError(''); setName(project.name); setDialog(mode); };
  const submit = async () => {
    if (busy || (dialog === 'rename' && !name.trim())) return;
    setBusy(true); setError('');
    try {
      const result = await apiFetch(`/projects/${project.id}`, { method: dialog === 'delete' ? 'DELETE' : 'PATCH', ...(dialog === 'rename' ? { body: JSON.stringify({ name: name.trim() }) } : {}) }) as { cleanup_pending?: boolean };
      const deleting = dialog === 'delete';
      setDialog(null);
      if (deleting) {
        client.removeQueries({ queryKey: ['project-workspace', project.id] });
        client.removeQueries({ queryKey: ['project-workspace-detail', project.id] });
        client.removeQueries({ queryKey: ['project-suggestions', project.id] });
        onDeleted?.(project.id, result.cleanup_pending);
      }
      await Promise.all(['projects', 'project-chat', 'project-workspace'].map(key => client.invalidateQueries({ queryKey: [key] })));
    } catch (e) { setError((e as Error).message || 'Не удалось сохранить изменение. Попробуйте ещё раз.'); }
    finally { setBusy(false); }
  };
  return <>
    <Tooltip title="Действия с проектом"><span className={compact ? 'sidebar-row-action' : undefined} data-open={anchor ? true : undefined}><IconButton size="small" disabled={busy} aria-label={`Действия с проектом ${project.name}`} aria-haspopup="menu" aria-expanded={!!anchor} sx={compact ? { width: { xs: 40, md: 32 }, height: { xs: 40, md: 32 }, borderRadius: '8px', color: 'text.secondary', '@media (pointer: coarse)': { width: 44, height: 44 }, '&:hover': { bgcolor: 'var(--bt-overlay)', color: 'text.primary' } } : undefined} onClick={e => { e.stopPropagation(); setAnchor(e.currentTarget); }}><DotsThree size={20} weight="bold" /></IconButton></span></Tooltip>
    <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
      <MenuItem onClick={() => open('rename')}><ListItemIcon><PencilSimple size={18} /></ListItemIcon>Переименовать проект</MenuItem>
      <MenuItem onClick={() => open('delete')} sx={{ color: 'error.main' }}><ListItemIcon sx={{ color: 'inherit' }}><Trash size={18} /></ListItemIcon>Удалить проект</MenuItem>
    </Menu>
    <Dialog open={!!dialog} onClose={close} fullWidth maxWidth="xs" aria-labelledby={`project-action-${project.id}`}>
      <form onSubmit={e => { e.preventDefault(); void submit(); }}>
        <DialogTitle id={`project-action-${project.id}`}>{dialog === 'delete' ? 'Удалить проект?' : 'Переименовать проект'}</DialogTitle>
        <DialogContent>
          {dialog === 'rename' ? <TextField autoFocus margin="dense" fullWidth label="Название проекта" value={name} disabled={busy} inputProps={{ maxLength: 160 }} onChange={e => setName(e.target.value)} helperText={`${name.length}/160`} /> : <>
            <DialogContentText sx={{ overflowWrap: 'anywhere', mb: 1.5 }}>Проект «{project.name}» будет удалён.</DialogContentText>
            <DialogContentText sx={{ mb: 1.5 }}>Беседы и вложения в них сохранятся. Беседы появятся в разделе «Беседы вне проектов».</DialogContentText>
            <DialogContentText>Материалы, результаты, их версии и память проекта удалятся безвозвратно. Перед удалением скачайте нужные файлы.</DialogContentText>
          </>}
          {error && <Alert severity="error" sx={{ mt: 2 }} role="alert">{error}</Alert>}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button autoFocus={dialog === 'delete'} disabled={busy} color="inherit" onClick={close}>Отмена</Button>
          <Button type="submit" disabled={busy || (dialog === 'rename' && !name.trim())} color={dialog === 'delete' ? 'error' : 'primary'} variant="contained">{busy ? 'Сохраняю…' : dialog === 'delete' ? 'Удалить проект' : 'Сохранить'}</Button>
        </DialogActions>
      </form>
    </Dialog>
  </>;
}
