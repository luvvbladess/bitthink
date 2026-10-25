import { Component, type ReactNode } from 'react';
import { Alert, Box, Button, Stack } from '@mui/material';
import { Link } from 'react-router-dom';
import { isRouteDownloadError, refreshRouteOnce } from '@/navigation/routeRecovery';

export class RouteErrorBoundary extends Component<{ children: ReactNode; path: string }, { failed: boolean; download: boolean }> {
  state = { failed: false, download: false };
  static getDerivedStateFromError(error: unknown) { return { failed: true, download: isRouteDownloadError(error) }; }

  componentDidCatch(error: Error) {
    if (isRouteDownloadError(error)) refreshRouteOnce();
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const inChat = this.props.path === '/chat';
    return <Box sx={{ pt: 12, px: 2, maxWidth: 680, mx: 'auto' }}>
      <Alert severity="error">{this.state.download
        ? 'Не удалось загрузить раздел. Проверьте соединение и повторите загрузку.'
        : 'В этом разделе произошла ошибка. Попробуйте открыть его заново.'}</Alert>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 2, alignItems: { xs: 'stretch', sm: 'center' } }}>
        <Button variant="contained" onClick={() => this.state.download ? window.location.reload() : this.setState({ failed: false, download: false })}>{this.state.download ? 'Повторить загрузку' : 'Открыть заново'}</Button>
        <Button component={Link} to={inChat ? '/settings' : '/chat'}>{inChat ? 'Открыть настройки' : 'Вернуться в чат'}</Button>
      </Stack>
    </Box>;
  }
}
