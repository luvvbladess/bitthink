import { useEffect, useState } from 'react';
import {
  Avatar,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  InputAdornment,
  MenuItem,
  Pagination,
  Select,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MagnifyingGlass, CaretRight, UsersThree, ArrowsClockwise } from '@phosphor-icons/react';
import { useNavigate } from 'react-router-dom';
import { adminApi, AdminUser } from '@/api/adminApi';
import { AdminIsland, TIER_LABELS, formatExpiry } from './AdminIsland';

function useDebounced<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

const roleColors: Record<string, { bg: string; color: string }> = {
  admin: { bg: 'var(--bt-glow-strong)', color: 'primary.light' },
  user: { bg: 'var(--bt-overlay-faint)', color: 'var(--bt-ink-muted)' },
};

const TIERS = [
  { id: 'free', label: 'Базовый' },
  { id: 'trial', label: 'Пробный' },
  { id: 'pro', label: 'Pro' },
  { id: 'proplus', label: 'Pro+' },
  { id: 'ultra', label: 'Ultra' },
  { id: 'creator', label: 'Creator' },
];

export default function AdminUsersPage() {
  const [qInput, setQInput] = useState('');
  const q = useDebounced(qInput);
  const [page, setPage] = useState(1);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetTier, setResetTier] = useState('free');
  const [resetDays, setResetDays] = useState(30);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const limit = 20;

  useEffect(() => setPage(1), [q]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin', 'users', q, page],
    queryFn: () => adminApi.listUsers({ q, offset: (page - 1) * limit, limit }),
  });

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) => adminApi.setRole(id, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }),
  });

  const bulkReset = useMutation({
    mutationFn: () => adminApi.resetNonAdminSubscriptions({ tier: resetTier, duration_days: resetDays }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin'] });
      setResetOpen(false);
    },
  });

  const users: AdminUser[] = data?.items || [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        alignItems={{ sm: 'center' }}
        sx={{ mb: 3 }}
      >
        <TextField
          placeholder="Поиск по email"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <MagnifyingGlass size={18} />
              </InputAdornment>
            ),
          }}
          size="small"
          sx={{ minWidth: { sm: 280 }, flex: 1 }}
        />
        <Button
          variant="outlined"
          startIcon={<ArrowsClockwise size={16} />}
          onClick={() => setResetOpen(true)}
          sx={{ minHeight: 44, whiteSpace: 'nowrap' }}
        >
          Сбросить тарифы
        </Button>
      </Stack>

      <AdminIsland>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Пользователь</TableCell>
                <TableCell>Роль</TableCell>
                <TableCell>Тариф</TableCell>
                <TableCell>До</TableCell>
                <TableCell>Регистрация</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading &&
                Array.from({ length: 6 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={6}>
                      <Skeleton variant="text" height={40} sx={{ bgcolor: 'var(--bt-overlay-faint)' }} />
                    </TableCell>
                  </TableRow>
                ))}

              {!isLoading && isError && (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Typography sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
                      Не удалось загрузить пользователей.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}

              {!isLoading && !isError && users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Box sx={{ py: 6, textAlign: 'center', color: 'text.secondary' }}>
                      <UsersThree size={28} style={{ opacity: 0.5, marginBottom: 8 }} />
                      <Typography variant="body2">
                        {q ? `Никто не найден по запросу «${q}»` : 'Пользователей пока нет'}
                      </Typography>
                    </Box>
                  </TableCell>
                </TableRow>
              )}

              {!isLoading &&
                !isError &&
                users.map((u) => (
                  <TableRow key={u.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/users/${u.id}`)}>
                    <TableCell>
                      <Stack direction="row" spacing={1.5} alignItems="center">
                        <Avatar
                          sx={{ width: 32, height: 32, fontSize: '0.85rem', bgcolor: 'var(--bt-glow-strong)', color: 'primary.light' }}
                        >
                          {(u.first_name || u.email)[0]?.toUpperCase()}
                        </Avatar>
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={500} noWrap>
                            {u.first_name || u.email.split('@')[0]}
                          </Typography>
                          <Typography variant="caption" sx={{ color: 'text.muted' }} noWrap component="div">
                            {u.email}
                          </Typography>
                        </Box>
                      </Stack>
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Select
                        value={u.role}
                        size="small"
                        onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}
                        sx={{
                          minWidth: 110,
                          '& .MuiSelect-select': {
                            py: 0.5,
                            borderRadius: 1,
                            bgcolor: roleColors[u.role]?.bg,
                            color: roleColors[u.role]?.color,
                            fontWeight: 600,
                            fontSize: '0.8rem',
                          },
                          '& fieldset': { border: 'none' },
                        }}
                      >
                        <MenuItem value="user">user</MenuItem>
                        <MenuItem value="admin">admin</MenuItem>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ color: u.tier && u.tier !== 'free' ? 'primary.light' : 'text.secondary' }}>
                        {TIER_LABELS[u.tier || 'free'] || u.tier || 'Базовый'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                        {formatExpiry(u.expires_at)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                        {new Date(u.created_at).toLocaleDateString('ru-RU')}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <CaretRight size={16} color="currentColor" />
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </TableContainer>
        {totalPages > 1 && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} color="primary" />
          </Box>
        )}
      </AdminIsland>

      <Dialog open={resetOpen} onClose={() => setResetOpen(false)} PaperProps={{ sx: { bgcolor: 'var(--bt-paper)', backgroundImage: 'none' } }}>
        <DialogTitle>Сбросить тарифы не-админам</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ minWidth: 320, pt: 1 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              Старый тариф и дата окончания будут стёрты. Новый срок считается с сегодня. Администраторы не изменятся.
            </Typography>
            <Select value={resetTier} onChange={(e) => setResetTier(e.target.value)} fullWidth>
              {TIERS.map((t) => (
                <MenuItem key={t.id} value={t.id}>
                  {t.label}
                </MenuItem>
              ))}
            </Select>
            {resetTier !== 'free' && (
              <TextField
                label="Дней с сегодня"
                type="number"
                value={resetDays}
                onChange={(e) => setResetDays(Number(e.target.value))}
                fullWidth
              />
            )}
            {bulkReset.isError && (
              <Typography variant="body2" color="error">
                Не удалось сбросить тарифы. Попробуйте ещё раз.
              </Typography>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetOpen(false)}>Отмена</Button>
          <Button variant="contained" disabled={bulkReset.isPending} onClick={() => bulkReset.mutate()}>
            {bulkReset.isPending ? 'Сбрасываю…' : 'Сбросить'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
