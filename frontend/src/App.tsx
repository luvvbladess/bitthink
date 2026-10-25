import { lazy, Suspense, useEffect, useLayoutEffect } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigationType } from 'react-router-dom';
import { Box } from '@mui/material';
import { AnimatePresence, motion } from 'framer-motion';
import { loadChat, loadSettings, loadBilling, preloadAccountPages } from '@/navigation/preload';
import { ChatConnectionProvider } from '@/hooks/ChatConnection';
import { RouteErrorBoundary } from '@/components/RouteErrorBoundary';
const LoginPage = lazy(() => import('@/pages/LoginPage'));
const LandingPage = lazy(() => import('@/pages/LandingPage'));
const ChatPage = lazy(loadChat);
const JoinPage = lazy(() => import('@/pages/JoinPage'));
const SettingsPage = lazy(loadSettings);
const BillingPage = lazy(loadBilling);
const PrivacyPage = lazy(() => import('@/pages/PrivacyPage'));
const AdminLayout = lazy(() => import('@/pages/admin/AdminLayout'));
const AdminUsersPage = lazy(() => import('@/pages/admin/AdminUsersPage'));
const AdminUserDetailPage = lazy(() => import('@/pages/admin/AdminUserDetailPage'));
const AdminStatsPage = lazy(() => import('@/pages/admin/AdminStatsPage'));
import { useAuthStore } from '@/stores/authStore';
import { FluidNav } from '@/components/FluidNav';
import { PageAtmosphere } from '@/components/PageAtmosphere';
import { apiFetch, ApiError } from '@/api/client';
import { loginDestination } from '@/stores/loginDestination';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  const location = useLocation();
  const next = `${location.pathname}${location.search}`;
  return token ? <>{children}</> : <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
}

const pageTransition = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.2, ease: [0.23, 1, 0.32, 1] },
};

function HomeRoute() {
  const token = useAuthStore((s) => s.accessToken);
  if (token) return <Navigate to="/chat" replace />;
  return (
    <motion.div key="landing" {...pageTransition}>
      <LandingPage />
    </motion.div>
  );
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.accessToken);
  const location = useLocation();
  return !token ? <>{children}</> : <Navigate to={loginDestination(location.search)} replace />;
}

export default function App() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const token = useAuthStore((s) => s.accessToken);
  const setUser = useAuthStore((s) => s.setUser);

  useLayoutEffect(() => {
    // New sections start at the top. Conversation/search changes leave their
    // own scroll position alone; browser Back retains native restoration.
    if (navigationType !== 'POP' || location.pathname === '/chat') window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [location.pathname]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(preloadAccountPages, 1200);
    return () => window.clearTimeout(timer);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    apiFetch('/auth/me', { timeoutMs: 15000 })
      .then(user => { if (!cancelled) setUser(user); })
      .catch(error => {
        if (!cancelled && error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          useAuthStore.getState().logout();
        }
      });
    return () => { cancelled = true; };
  }, [token, setUser]);

  return (
    <ChatConnectionProvider>
    <Box sx={{ minHeight: '100dvh', bgcolor: 'background.default', color: 'text.primary', position: 'relative' }}>
      <PageAtmosphere />
      <Box
        component="a"
        href="#main"
        sx={{
          position: 'absolute',
          left: -9999,
          '&:focus': { left: 16, top: 16, zIndex: 40, px: 2, py: 1, bgcolor: 'primary.main', color: 'primary.contrastText', borderRadius: 1 },
        }}
      >
        К содержанию
      </Box>
      <Box sx={{ position: 'relative', zIndex: 1 }}>
      <FluidNav />
      <Box component="main" id="main">
      <RouteErrorBoundary key={location.pathname} path={location.pathname}>
      <Suspense fallback={<Box role="status" sx={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', color: 'text.secondary' }}>Загружаем страницу…</Box>}>
      <AnimatePresence mode="wait">
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route
            path="/login"
            element={
              <PublicRoute>
                <motion.div key="login" {...pageTransition}>
                  <LoginPage mode="login" />
                </motion.div>
              </PublicRoute>
            }
          />
          <Route
            path="/register"
            element={
              <PublicRoute>
                <motion.div key="register" {...pageTransition}>
                  <LoginPage mode="register" />
                </motion.div>
              </PublicRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <PrivateRoute>
                <motion.div key="chat" {...pageTransition} style={{ height: '100dvh', overflow: 'hidden' }}>
                  <ChatPage />
                </motion.div>
              </PrivateRoute>
            }
          />
          <Route
            path="/join/:token"
            element={
              <PrivateRoute>
                <JoinPage />
              </PrivateRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <PrivateRoute>
                <motion.div key="settings" {...pageTransition}>
                  <SettingsPage />
                </motion.div>
              </PrivateRoute>
            }
          />
          <Route path="/computer" element={<Navigate to="/chat" replace />} />
          <Route
            path="/billing"
            element={
              <PrivateRoute>
                <motion.div key="billing" {...pageTransition}>
                  <BillingPage />
                </motion.div>
              </PrivateRoute>
            }
          />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="/admin/users" replace />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="users/:id" element={<AdminUserDetailPage />} />
            <Route path="stats" element={<AdminStatsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
      </Suspense>
      </RouteErrorBoundary>
      </Box>
      </Box>
    </Box>
    </ChatConnectionProvider>
  );
}
