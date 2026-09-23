import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Box } from '@mui/material';
import { AnimatePresence, motion } from 'framer-motion';
import LoginPage from '@/pages/LoginPage';
import LandingPage from '@/pages/LandingPage';
import ChatPage from '@/pages/ChatPage';
import JoinPage from '@/pages/JoinPage';
import SettingsPage from '@/pages/SettingsPage';
import BillingPage from '@/pages/BillingPage';
import AdminLayout from '@/pages/admin/AdminLayout';
import AdminUsersPage from '@/pages/admin/AdminUsersPage';
import AdminUserDetailPage from '@/pages/admin/AdminUserDetailPage';
import AdminStatsPage from '@/pages/admin/AdminStatsPage';
import { useAuthStore } from '@/stores/authStore';
import { FluidNav } from '@/components/FluidNav';
import { PageAtmosphere } from '@/components/PageAtmosphere';
import { apiFetch } from '@/api/client';

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
  return !token ? <>{children}</> : <Navigate to="/chat" replace />;
}

export default function App() {
  const token = useAuthStore((s) => s.accessToken);
  const setUser = useAuthStore((s) => s.setUser);

  useEffect(() => {
    if (!token) return;
    apiFetch('/auth/me')
      .then(setUser)
      .catch(() => useAuthStore.getState().logout());
  }, [token, setUser]);

  return (
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
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="/admin/users" replace />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="users/:id" element={<AdminUserDetailPage />} />
            <Route path="stats" element={<AdminStatsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
      </Box>
      </Box>
    </Box>
  );
}
