/** Account-scoped local drafts. Files never leave this browser until Send. */
type SavedDraft = { scope: string; text: string; files: File[]; updated: number };
let database: Promise<IDBDatabase> | undefined;
function db() {
  return database ??= new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('Хранилище недоступно')); return; }
    const request = indexedDB.open('bitthink-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'scope' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('Хранилище занято'));
  });
}
export async function loadDraft(scope: string): Promise<SavedDraft | undefined> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const request = database.transaction('drafts').objectStore('drafts').get(scope);
    request.onsuccess = () => { const value = request.result as SavedDraft | undefined; resolve(value && value.updated > Date.now() - 7 * 86400000 ? value : undefined); };
    request.onerror = () => reject(request.error);
  });
}
export async function saveDraft(scope: string, draft: { text: string; files: File[] }) {
  const database = await db();
  const safe = draft.files.reduce((size, file) => size + file.size, 0) <= 20 * 1024 * 1024;
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction('drafts', 'readwrite');
    const store = transaction.objectStore('drafts');
    if (!draft.text && !draft.files.length) store.delete(scope);
    else store.put({ scope, text: draft.text, files: safe ? draft.files : [], updated: Date.now() });
    transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error); transaction.onabort = () => reject(transaction.error);
  });
  return safe;
}
export async function clearDraftAccount(account: string) {
  const database = await db();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction('drafts', 'readwrite');
    const request = transaction.objectStore('drafts').openCursor();
    request.onsuccess = () => { const cursor = request.result; if (cursor) { if (String(cursor.key).startsWith(account + ':') || cursor.value.updated <= Date.now() - 7 * 86400000) cursor.delete(); cursor.continue(); } };
    transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
  });
}
