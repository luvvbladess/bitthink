import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { ColorModeProvider } from '@/theme/ColorMode';
import App from '@/App';
import '@/theme/tokens.css';
import { useAuthStore } from '@/stores/authStore';
import { installDiagnostics } from '@/api/diagnostics';

installDiagnostics();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000 * 60 * 5 },
  },
});

// Query keys describe resources, so discard cached private data at an account boundary.
useAuthStore.subscribe((state, previous) => {
  if ((previous.accessToken && !state.accessToken)
    || (previous.user?.id && state.user?.id && previous.user.id !== state.user.id)) {
    queryClient.clear();
  }
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ColorModeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ColorModeProvider>
    </QueryClientProvider>
  </StrictMode>
);
