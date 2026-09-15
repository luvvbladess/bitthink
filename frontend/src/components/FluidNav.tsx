import { useState } from 'react';
import { AppBar, Toolbar, Box, IconButton, Drawer, List, ListItemButton, ListItemText } from '@mui/material';
import { List as ListIcon, X } from '@phosphor-icons/react';
import { Link, useLocation } from 'react-router-dom';
import { PrimaryButton } from './IslandButton';
import { AccountMenu } from './AccountMenu';
import { BrandLink } from '@/components/BrandMark';
import { ColorModeToggle } from '@/components/ColorModeToggle';
import { headerIconBtnSx } from '@/theme/effects';
import { useAuthStore } from '@/stores/authStore';

const navLinks = [
  { label: 'Возможности', href: '/#features', private: false, publicOnly: true },
  { label: 'Тарифы', href: '/#pricing', private: false, publicOnly: true },
  { label: 'Вопросы', href: '/#faq', private: false, publicOnly: true },
  { label: 'Чат', href: '/chat', private: true },
  { label: 'Кабинет', href: '/billing', private: true },
  { label: 'Настройки', href: '/settings', private: true },
  { label: 'Админ', href: '/admin', private: true, admin: true },
];

export function FluidNav() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const token = useAuthStore((s) => s.accessToken);
  const isAdmin = useAuthStore((s) => s.isAdmin)();

  const visibleLinks = navLinks.filter(
    (l) =>
      (!l.private || token) &&
      (!l.admin || isAdmin) &&
      (!l.publicOnly || !token)
  );
  const isChatPage = location.pathname === '/chat';

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        top: 0,
        left: 0,
        right: 0,
        width: '100%',
        display: isChatPage ? 'none' : 'flex',
        bgcolor: 'var(--bt-nav)',
        borderBottom: '1px solid',
        borderColor: 'var(--bt-line)',
        boxShadow: 'var(--bt-shadow)',
      }}
    >
      <Toolbar sx={{ minHeight: { xs: 56, md: 56 }, px: { xs: 2, md: 3 }, gap: 1 }}>
        <BrandLink variant="nav" />

        <Box sx={{ display: { xs: 'none', md: 'flex' }, alignItems: 'center', gap: 0.25, ml: 'auto' }}>
          {visibleLinks.map((link) => (
            <NavLink key={link.href} to={link.href} active={location.pathname === link.href}>
              {link.label}
            </NavLink>
          ))}
          <Box sx={{ ml: 1.25, display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <ColorModeToggle />
            {!token ? (
              <Link to="/login" style={{ textDecoration: 'none' }}>
                <PrimaryButton size="small" sx={{ py: 0.6 }}>Войти</PrimaryButton>
              </Link>
            ) : (
              <AccountMenu />
            )}
          </Box>
        </Box>

        <Box sx={{ display: { xs: 'flex', md: 'none' }, ml: 'auto', alignItems: 'center', gap: 0.75 }}>
          <ColorModeToggle />
          <IconButton sx={headerIconBtnSx} onClick={() => setOpen(true)} aria-label="Меню">
            <ListIcon size={22} weight="bold" />
          </IconButton>
        </Box>
      </Toolbar>

      <Drawer
        anchor="top"
        open={open}
        onClose={() => setOpen(false)}
        PaperProps={{ sx: { bgcolor: 'background.default', backgroundImage: 'none', height: '100%', boxShadow: 'none' } }}
      >
        <Box sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Box display="flex" justifyContent="space-between" alignItems="center" mb={2} gap={1}>
            <BrandLink variant="nav" />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <ColorModeToggle />
              <IconButton onClick={() => setOpen(false)} sx={headerIconBtnSx} aria-label="Закрыть меню">
                <X size={22} weight="bold" />
              </IconButton>
            </Box>
          </Box>
          <List>
            {visibleLinks.map((link) => (
              <ListItemButton key={link.href} component={Link} to={link.href} onClick={() => setOpen(false)} sx={{ minHeight: 44 }}>
                <ListItemText primary={link.label} />
              </ListItemButton>
            ))}
            {token && (
              <ListItemButton
                onClick={() => {
                  setOpen(false);
                  useAuthStore.getState().logout();
                }}
                sx={{ minHeight: 44 }}
              >
                <ListItemText primary="Выйти" />
              </ListItemButton>
            )}
          </List>
        </Box>
      </Drawer>
    </AppBar>
  );
}

function NavLink({ to, active, children }: { to: string; active: boolean; children: React.ReactNode }) {
  return (
    <Box
      component={Link}
      to={to}
      sx={{
        px: 1,
        py: 1.5,
        fontSize: '0.875rem',
        fontWeight: 500,
        color: active ? 'text.primary' : 'text.secondary',
        textDecoration: 'none',
        borderBottom: '1px solid',
        borderColor: active ? 'primary.main' : 'transparent',
        textShadow: 'none',
        transition: 'color 0.15s cubic-bezier(0.23, 1, 0.32, 1), border-color 0.15s cubic-bezier(0.23, 1, 0.32, 1)',
        '&:hover': { color: 'text.primary' },
      }}
    >
      {children}
    </Box>
  );
}
