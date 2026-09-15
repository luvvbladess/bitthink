import { apiFetch } from './client';

export interface AdminUser {
  id: number;
  email: string;
  first_name?: string;
  role: string;
  bot_user_id: number;
  created_at: string;
  tier?: string;
  expires_at?: number;
}

export interface AdminUserList {
  total: number;
  offset: number;
  limit: number;
  items: AdminUser[];
}

export interface SubscriptionData {
  tier: string;
  expires_at: number;
  name?: string;
  unlimited?: boolean;
  chat?: { used: number; limit: number; remaining: number | null };
  computer?: { used: number; limit: number; remaining: number | null };
  images?: { used: number; limit: number; remaining: number | null };
  nano_cushion?: { used: number; limit: number };
  windows?: {
    chat?: { session?: { used: number; limit: number }; week?: { used: number; limit: number } };
  };
  chat_tokens_used?: number;
  computer_tokens_used?: number;
  images_used?: number;
  spend?: { day?: { usd?: number }; month?: { usd?: number } };
  daily_nano_mini?: number;
  daily_gpt54?: number;
  daily_director?: number;
  daily_images?: number;
  daily_docs?: number;
}

export const adminApi = {
  getStats: () => apiFetch('/admin/stats'),
  listUsers: (params?: { q?: string; role?: string; offset?: number; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.q) search.set('q', params.q);
    if (params?.role) search.set('role', params.role);
    if (params?.offset !== undefined) search.set('offset', String(params.offset));
    if (params?.limit !== undefined) search.set('limit', String(params.limit));
    return apiFetch(`/admin/users?${search.toString()}`);
  },
  getUser: (id: number) => apiFetch(`/admin/users/${id}`),
  getUserConversations: (id: number) => apiFetch(`/admin/users/${id}/conversations`),
  getUserUsage: (id: number) => apiFetch(`/admin/users/${id}/usage`),
  setSubscription: (id: number, data: Partial<SubscriptionData> & { tier: string; duration_days?: number; from_today?: boolean }) =>
    apiFetch(`/admin/users/${id}/subscription`, { method: 'POST', body: JSON.stringify(data) }),
  resetNonAdminSubscriptions: (data?: { tier?: string; duration_days?: number }) =>
    apiFetch('/admin/subscriptions/reset-non-admins', { method: 'POST', body: JSON.stringify(data || { tier: 'free' }) }),
  setRole: (id: number, role: string) => apiFetch(`/admin/users/${id}/role`, { method: 'POST', body: JSON.stringify({ role }) }),
  deleteConversation: (userId: number, conversationId: string) =>
    apiFetch(`/admin/users/${userId}/conversations/${conversationId}`, { method: 'DELETE' }),
};
