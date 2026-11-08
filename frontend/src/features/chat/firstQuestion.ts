const key = 'bit-think-first-question';
export const firstQuestionRoute = '/chat?start=1';
export const firstQuestionLimit = 4000;
let pending = '';

export function saveFirstQuestion(value: string) {
  pending = value.trim().slice(0, firstQuestionLimit);
  try {
    if (pending) sessionStorage.setItem(key, pending);
    else sessionStorage.removeItem(key);
  } catch { /* In-app navigation can still carry the draft in memory. */ }
}

export function takeFirstQuestion() {
  let value = pending;
  try { value ||= sessionStorage.getItem(key) || ''; } catch { /* Storage is optional. */ }
  saveFirstQuestion('');
  return value.slice(0, firstQuestionLimit);
}
