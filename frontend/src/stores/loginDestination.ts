/** Only resume local application routes after authentication. */
export function loginDestination(search: string): string {
  const next = new URLSearchParams(search).get('next') || '';
  if (!next.startsWith('/') || next.startsWith('//') || /[\\\u0000-\u0020]/.test(next)) return '/chat';
  const path = next.split(/[?#]/)[0];
  return ['/login', '/register'].includes(path.replace(/\/$/, '')) ? '/chat' : next;
}
