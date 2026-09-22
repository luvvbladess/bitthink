import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { Box, Typography, Stack } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { ChatText, Desktop, Image, Lightning } from '@phosphor-icons/react';
import { apiFetch } from '@/api/client';
import { formatResetIn, type Plan, type Subscription, type UsageWindow } from '@/api/billing';
import { UsageMeter } from '@/components/UsageMeter';
import { AccountPageShell, AccountSection } from '@/features/account/AccountChrome';
import { TIER_LABELS, formatRub, formatTokens, formatUsd } from '@/constants/tiers';
import { BRAND_NAME } from '@/brand';
import { applyPageMeta } from '@/seo';

function windowCaption(win?: UsageWindow, idle?: string): string | undefined {
  if (!win?.limit) return idle;
  if (win.active && win.resets_at) return `обновится через ${formatResetIn(win.resets_at)}`;
  if (!win.active) return idle;
  return undefined;
}

function WindowMeters({
  family,
}: {
  family?: { session?: UsageWindow; week?: UsageWindow; month?: UsageWindow };
}) {
  return (
    <Stack spacing={1.75}>
      <UsageMeter
        label="Сейчас"
        used={family?.session?.used || 0}
        limit={family?.session?.limit || 0}
        remaining={family?.session?.remaining}
        caption={windowCaption(family?.session, 'начнётся с первого сообщения')}
      />
      <UsageMeter
        label="На неделю"
        used={family?.week?.used || 0}
        limit={family?.week?.limit || 0}
        remaining={family?.week?.remaining}
        caption={windowCaption(family?.week)}
      />
      <UsageMeter
        label="На месяц"
        used={family?.month?.used || 0}
        limit={family?.month?.limit || 0}
        remaining={family?.month?.remaining}
        caption={windowCaption(family?.month)}
      />
    </Stack>
  );
}

function PoolBlock({
  icon,
  title,
  hint,
  children,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: hint ? 0.5 : 1.5 }}>
        <Box sx={{ color: 'primary.light', display: 'grid', placeItems: 'center' }}>{icon}</Box>
        <Typography sx={{ fontWeight: 600, fontSize: '0.9375rem', letterSpacing: '-0.02em' }}>{title}</Typography>
      </Stack>
      {hint ? (
        <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', mb: 1.5, lineHeight: 1.45 }}>{hint}</Typography>
      ) : null}
      {children}
    </Box>
  );
}

export default function BillingPage() {
  useEffect(() => {
    applyPageMeta({
      title: `Кабинет – ${BRAND_NAME}`,
      canonicalPath: '/billing',
      noindex: true,
    });
  }, []);

  const { data: sub } = useQuery<Subscription>({
    queryKey: ['subscription'],
    queryFn: () => apiFetch('/billing/subscription'),
  });
  const { data: plans } = useQuery<{ plans: Plan[] }>({
    queryKey: ['plans'],
    queryFn: () => apiFetch('/billing/plans'),
  });

  const tier = sub?.tier || 'free';
  const tierLabel = sub?.name || TIER_LABELS[tier] || tier;
  const expires = sub?.expires_at
    ? new Date(sub.expires_at * 1000).toLocaleDateString('ru-RU')
    : tier === 'free'
      ? 'без срока'
      : 'бессрочно';
  const isFree = tier === 'free';
  const isPaid = !isFree && !sub?.unlimited;

  return (
    <AccountPageShell
      title="Кабинет"
      lede={
        sub?.unlimited
          ? 'Лимитов нет. Ниже оценка расхода по ценам API за сегодня и за месяц.'
          : 'Сначала списывается короткое окно, потом неделя, потом месяц. Остаток не копится.'
      }
    >
      <AccountSection featured>
        <Stack spacing={0.5}>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={{ xs: 0.35, sm: 1.5 }}
            alignItems={{ sm: 'baseline' }}
            justifyContent="space-between"
          >
            <Typography sx={{ fontWeight: 600, color: 'primary.light', fontSize: { xs: '1.5rem', sm: '1.75rem' }, letterSpacing: '-0.035em', lineHeight: 1.15 }}>
              {tierLabel}
            </Typography>
            <Typography sx={{ color: 'text.secondary', fontSize: '0.875rem' }}>до {expires}</Typography>
          </Stack>
          <Typography sx={{ color: 'text.secondary', fontSize: '0.8125rem', pt: 1, maxWidth: '48ch', lineHeight: 1.45 }}>
            Оплата на сайте появится отдельно. Сейчас тариф выдаёт администратор.
          </Typography>
        </Stack>
      </AccountSection>

      {sub?.unlimited ? (
        <AccountSection title="Расход" hint="Оценка по ценам API, не чек провайдера. День и месяц считаются по Москве.">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2}>
              {[
                { label: 'Сегодня', value: formatUsd(sub.spend?.day?.usd) },
                { label: 'Этот месяц', value: formatUsd(sub.spend?.month?.usd) },
              ].map((item) => (
                <Box key={item.label} sx={{ flex: 1, minWidth: 0 }}>
                  <Typography sx={{ color: 'text.secondary', fontSize: '0.75rem', fontWeight: 600, mb: 0.35 }}>
                    {item.label}
                  </Typography>
                  <Typography sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', fontSize: '1.25rem', letterSpacing: '-0.03em', color: 'primary.light' }}>
                    {item.value}
                  </Typography>
                </Box>
              ))}
            </Stack>
            {(sub.spend?.day?.models || []).length > 0 && (
              <Stack spacing={0.85} sx={{ pt: 0.5 }}>
                {sub.spend?.day?.models?.slice(0, 6).map((row) => (
                  <Stack key={row.model} direction="row" justifyContent="space-between" spacing={2}>
                    <Typography sx={{ color: 'text.secondary', fontSize: '0.875rem' }} noWrap>
                      {row.model}
                    </Typography>
                    <Typography sx={{ color: 'text.secondary', fontSize: '0.875rem', fontVariantNumeric: 'tabular-nums' }}>
                      {formatUsd(row.usd)}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            )}
          </Stack>
        </AccountSection>
      ) : isFree ? (
        <AccountSection title="Что осталось сегодня" hint="Пилот и Исследование открываются на Pro и выше.">
          <Stack spacing={2}>
            <UsageMeter
              icon={<ChatText size={16} />}
              label="Ответы"
              used={sub?.free_daily?.replies || 0}
              limit={sub?.free_daily?.replies_limit || 30}
              caption={sub?.free_daily?.resets_at ? `обновится через ${formatResetIn(sub.free_daily.resets_at)}` : undefined}
              count
            />
            <UsageMeter
              icon={<Lightning size={16} />}
              label="Поиски"
              used={sub?.free_daily?.searches || 0}
              limit={sub?.free_daily?.searches_limit || 5}
              count
            />
            <UsageMeter
              icon={<Image size={16} />}
              label="Картинки в этом месяце"
              used={sub?.images?.used || 0}
              limit={sub?.images?.limit || 3}
              count
            />
          </Stack>
        </AccountSection>
      ) : (
        <AccountSection title="Что осталось" hint="Сначала короткое окно, затем неделя, затем месяц.">
          <Stack spacing={3}>
            <PoolBlock icon={<ChatText size={18} weight="bold" />} title="Чат">
              <WindowMeters family={sub?.windows?.chat} />
            </PoolBlock>
            <PoolBlock icon={<Desktop size={18} weight="bold" />} title="Пилот" hint="Сайты, почта и сервер.">
              <WindowMeters family={sub?.windows?.computer} />
            </PoolBlock>
            <PoolBlock icon={<Image size={18} weight="bold" />} title="Картинки">
              <UsageMeter
                label="В этом месяце"
                used={sub?.images?.used || 0}
                limit={sub?.images?.limit || 0}
                remaining={sub?.images?.remaining}
                count
              />
            </PoolBlock>
            {isPaid && (sub?.nano_cushion?.limit || 0) > 0 && (sub?.chat?.remaining || 0) <= 0 && (
              <Typography sx={{ color: 'text.secondary', fontSize: '0.875rem', lineHeight: 1.5 }}>
                Пул чата на месяц закончился. Сегодня ещё {Math.max(0, (sub?.nano_cushion?.limit || 0) - (sub?.nano_cushion?.used || 0))} быстрых ответов.
              </Typography>
            )}
          </Stack>
        </AccountSection>
      )}

      {!sub?.unlimited && (
        <AccountSection title="Как считаются токены" hint="1 наш токен равен 1 токену Luna. Если контекст больше 272 тыс. входных токенов, ход считается вдвойне.">
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
            {Object.entries(sub?.multipliers || { 'Luna / Nano': 1, Kimi: 4, DeepSeek: 5, Sol: 20, Astra: 90 }).map(
              ([name, factor]) => (
                <Box
                  key={name}
                  sx={{
                    px: 1.2,
                    py: 0.7,
                    minHeight: 36,
                    borderRadius: '999px',
                    bgcolor: 'var(--bt-overlay-faint)',
                    border: '1px solid var(--bt-hairline)',
                    fontSize: '0.8125rem',
                    color: 'text.secondary',
                  }}
                >
                  {name}{' '}
                  <Box component="span" sx={{ color: 'text.primary', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                    ×{factor}
                  </Box>
                </Box>
              ),
            )}
          </Box>
        </AccountSection>
      )}

      <AccountSection title="Тарифы" hint="Цифры уже те, что будут на тарифе. Кнопок оплаты пока нет.">
        <Stack spacing={0}>
          {(plans?.plans || []).map((plan, index) => {
            const current =
              plan.id === tier || (tier === 'start' && plan.id === 'pro') || (tier === 'max' && plan.id === 'ultra');
            return (
              <Box
                key={plan.id}
                sx={{
                  pt: index ? 2 : 0,
                  pb: index === (plans?.plans || []).length - 1 ? 0 : 2,
                  borderTop: index ? '1px solid var(--bt-hairline)' : 'none',
                  display: 'flex',
                  flexDirection: { xs: 'column', sm: 'row' },
                  gap: { xs: 1, sm: 2 },
                  alignItems: { sm: 'center' },
                  justifyContent: 'space-between',
                }}
              >
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography sx={{ fontWeight: 600, color: current ? 'primary.light' : 'text.primary', letterSpacing: '-0.02em' }}>
                      {plan.name}
                    </Typography>
                    {current && (
                      <Box
                        sx={{
                          px: 0.85,
                          py: 0.2,
                          borderRadius: '999px',
                          bgcolor: 'var(--bt-glow)',
                          color: 'primary.light',
                          fontSize: '0.6875rem',
                          fontWeight: 600,
                        }}
                      >
                        ваш
                      </Box>
                    )}
                  </Stack>
                  <Typography sx={{ color: 'text.secondary', mt: 0.4, fontSize: '0.8125rem', lineHeight: 1.45 }}>
                    {plan.description}
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', mt: 0.35, fontSize: '0.8125rem', lineHeight: 1.45 }}>
                    {formatTokens(plan.chat_session || 0)} сейчас · {formatTokens(plan.chat_week || 0)} / нед · {formatTokens(plan.chat_tokens)} / мес
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', display: 'block', fontSize: '0.75rem', mt: 0.25 }}>
                    Пилот {formatTokens(plan.computer_session || 0)} сейчас · {plan.images} картинок
                  </Typography>
                </Box>
                <Typography
                  sx={{
                    fontWeight: 600,
                    fontVariantNumeric: 'tabular-nums',
                    whiteSpace: 'nowrap',
                    fontSize: '1.0625rem',
                    letterSpacing: '-0.02em',
                    color: current ? 'primary.light' : 'text.primary',
                  }}
                >
                  {formatRub(plan.price_rub)}
                  <Box component="span" sx={{ ml: 0.5, fontSize: '0.75rem', fontWeight: 500, color: 'text.secondary' }}>
                    / мес
                  </Box>
                </Typography>
              </Box>
            );
          })}
        </Stack>
      </AccountSection>
    </AccountPageShell>
  );
}
