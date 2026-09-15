export const TIER_LABELS: Record<string, string> = {
  free: 'Базовый',
  trial: 'Пробный',
  start: 'Pro',
  pro: 'Pro',
  proplus: 'Pro+',
  max: 'Ultra',
  ultra: 'Ultra',
  creator: 'Creator',
};

export function formatTokens(value: number | null | undefined): string {
  const n = Math.max(0, Number(value) || 0);
  if (n >= 1_000_000) {
    const millions = n / 1_000_000;
    const digits = millions >= 10 ? 0 : 1;
    return `${millions.toLocaleString('ru-RU', { maximumFractionDigits: digits })} млн`;
  }
  if (n >= 1_000) {
    return `${Math.round(n / 1_000).toLocaleString('ru-RU')} тыс.`;
  }
  return n.toLocaleString('ru-RU');
}

export function formatUsd(value: number | null | undefined): string {
  const n = Math.max(0, Number(value) || 0);
  if (n > 0 && n < 0.01) return '< $0.01';
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatRub(value: number): string {
  return `${value.toLocaleString('ru-RU')} ₽`;
}
