import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { clearPendingSends } from '@/hooks/wsQueue';

interface User {
  id: string;
  email: string;
  first_name?: string;
  avatar_url?: string;
  role?: string;
  subscription_tier: string;
  selected_model: string;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  setTokens: (access: string, refresh: string) => void;
  setUser: (user: User | null) => void;
  updateUser: (patch: Partial<User>) => void;
  logout: () => void;
  isAdmin: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      setTokens: (access, refresh) => set({ accessToken: access, refreshToken: refresh }),
      setUser: (user) => set({ user }),
      updateUser: (patch) => set((state) => ({ user: state.user ? { ...state.user, ...patch } : state.user })),
      logout: () => {
        clearPendingSends();
        set({ accessToken: null, refreshToken: null, user: null });
      },
      isAdmin: () => get().user?.role === 'admin',
    }),
    { name: 'gpt-ultra-auth' }
  )
);
