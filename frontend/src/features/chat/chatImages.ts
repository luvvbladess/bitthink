import { downloadBlob } from '@/api/client';

export function lastChatImageUrl(
  messages: Array<{
    content?: string;
    attachment?: { type?: string; url?: string; status?: string };
  }>,
): string | undefined {
  const pattern = /!\[[^\]]*\]\((\/uploads\/[^)\s]+)\)/g;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.attachment?.type === 'image'
      && message.attachment.status === 'done'
      && message.attachment.url?.startsWith('/uploads/')
    ) {
      return message.attachment.url;
    }
    const matches = [...(message.content || '').matchAll(pattern)];
    if (matches.length) return matches[matches.length - 1][1];
  }
  return undefined;
}

export function imageDownloadName(url: string, alt?: string): string {
  const fromUrl = url.split('?')[0].split('/').pop() || '';
  let decoded = fromUrl;
  try {
    decoded = decodeURIComponent(fromUrl);
  } catch {
    // Keep the raw segment if it is not URI-encoded.
  }
  if (/\.(png|jpe?g|gif|webp|avif)$/i.test(decoded)) return decoded;
  const base = (alt || 'image').replace(/[\\/:*?"<>|]+/g, ' ').trim().slice(0, 80) || 'image';
  return `${base}.png`;
}

export async function downloadChatImage(url: string, filename?: string) {
  const name = filename || imageDownloadName(url);
  const response = await fetch(url);
  if (!response.ok) throw new Error('Не удалось скачать изображение');
  const blob = await response.blob();
  downloadBlob(blob, name);
}
