import { useAuthStore } from '@/stores/authStore';

const receipts = new Map<string, { id: string; payload: string; created: number }>();
function storageKey(payload: string) {
  const conversation = JSON.parse(payload).conversation_id;
  return `bitthink-submission:${useAuthStore.getState().user?.id || useAuthStore.getState().user?.email || 'anonymous'}:${conversation}`;
}
/** Keep the same operation ID after an uncertain delivery and a page refresh. */
export function submissionId(payload: string): string {
  const key = storageKey(payload);
  try {
    const previous = receipts.get(key) || JSON.parse(sessionStorage.getItem(key) || 'null');
    if (previous?.payload === payload && previous.created > Date.now() - 29 * 86400000) return previous.id;
  } catch { /* disabled storage */ }
  const id = crypto.randomUUID();
  const receipt = { id, payload, created: Date.now() };
  receipts.set(key, receipt);
  try { sessionStorage.setItem(key, JSON.stringify(receipt)); } catch { /* retry remains available in this tab */ }
  return id;
}
export function confirmSubmission(payload: string) { const key = storageKey(payload); receipts.delete(key); try { sessionStorage.removeItem(key); } catch { /* disabled storage */ } }
useAuthStore.subscribe((state, previous) => {
  const account = previous.user?.id || previous.user?.email;
  if (account && (!state.accessToken || (state.user?.id || state.user?.email) !== account)) {
    for (const key of receipts.keys()) if (key.startsWith(`bitthink-submission:${account}:`)) receipts.delete(key);
    try { for (let i = sessionStorage.length - 1; i >= 0; i--) { const key = sessionStorage.key(i); if (key?.startsWith(`bitthink-submission:${account}:`)) sessionStorage.removeItem(key); } } catch { /* disabled storage */ }
  }
});
