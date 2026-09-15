/** Shared reading column: messages and composer must use the same box. */
export const CHAT_COL = {
  width: '100%',
  maxWidth: 768,
  mx: 'auto',
  px: { xs: 1.5, sm: 3 },
  boxSizing: 'border-box',
} as const;

/** Top padding so the first line is not hidden under floating chrome. */
export const HEADER_SCROLL_PAD = { xs: '4.5rem', sm: '4.75rem' } as const;

/** Bottom padding so the last reply sits just above the floating composer. */
export const COMPOSER_SCROLL_PAD = { xs: '9.75rem', md: '10.25rem' } as const;

/** Extra room when the clarify card is docked above the composer. */
export const CLARIFY_SCROLL_PAD = { xs: '24rem', md: '23rem' } as const;
