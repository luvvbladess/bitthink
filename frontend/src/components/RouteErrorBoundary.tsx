import { Component, type ReactNode } from 'react';
import { Alert, Box, Button, Stack } from '@mui/material';
import { Link } from 'react-router-dom';

export class RouteErrorBoundary extends Component<{ children: ReactNode; path: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }

  render() {
    if (!this.state.failed) return this.props.children;
    const inChat = this.props.path === '/chat';
    return <Box sx={{ pt: 12, px: 2, maxWidth: 680, mx: 'auto' }}>
      <Alert severity="error">Не удалось открыть раздел. Проверьте соединение и повторите загрузку.</Alert>
      <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
        <Button variant="contained" onClick={() => window.location.reload()}>Повторить загрузку</Button>
        <Button component={Link} to={inChat ? '/settings' : '/chat'}>{inChat ? 'Открыть настройки' : 'Вернуться в чат'}</Button>
      </Stack>
    </Box>;
  }
}
