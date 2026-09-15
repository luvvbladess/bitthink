export type UsageWindow = {
  used: number;
  limit: number;
  remaining: number | null;
  resets_at?: number;
  ratio?: number;
  active?: boolean;
};

export type Pool = {
  used: number;
  limit: number;
  remaining: number | null;
};

export type SpendSlice = {
  usd: number;
  models?: { model: string; usd: number; input?: number; output?: number; images?: number }[];
};

export type Subscription = {
  tier?: string;
  name?: string;
  expires_at?: number;
  unlimited?: boolean;
  chat?: Pool;
  computer?: Pool;
  images?: Pool;
  windows?: {
    chat?: { session?: UsageWindow; week?: UsageWindow; month?: UsageWindow };
    computer?: { session?: UsageWindow; week?: UsageWindow; month?: UsageWindow };
  };
  nano_cushion?: { used: number; limit: number };
  free_daily?: {
    replies: number;
    replies_limit: number;
    searches: number;
    searches_limit: number;
    resets_at?: number;
  };
  multipliers?: Record<string, number>;
  spend?: {
    currency?: string;
    day?: SpendSlice;
    month?: SpendSlice;
  };
};

export type Plan = {
  id: string;
  name: string;
  price_rub: number;
  price_year_rub: number;
  description: string;
  features: string[];
  chat_tokens: number;
  computer_tokens: number;
  chat_week?: number;
  chat_session?: number;
  computer_week?: number;
  computer_session?: number;
  images: number;
};

export function formatResetIn(resetsAt: number, nowSec = Date.now() / 1000): string {
  const sec = Math.max(0, Math.floor(resetsAt - nowSec));
  const days = Math.floor(sec / 86400);
  const hours = Math.floor((sec % 86400) / 3600);
  const minutes = Math.floor((sec % 3600) / 60);
  if (days >= 2) return hours ? `${days} дн. ${hours} ч` : `${days} дн.`;
  if (days === 1) return hours ? `1 дн. ${hours} ч` : '1 день';
  if (hours >= 1) return `${hours} ч ${minutes} мин`;
  if (minutes >= 1) return `${minutes} мин`;
  return 'меньше минуты';
}
