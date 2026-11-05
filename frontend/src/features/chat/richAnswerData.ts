/** A deliberately small, data-only format. Model output never becomes HTML. */
export interface AnswerCardData {
  title: string;
  description: string;
  meta?: string;
  url?: string;
  linkLabel?: string;
  badge?: string;
  image?: string;
}

export function safeCardUrl(value: unknown, image = false): string | undefined {
  if (typeof value !== 'string' || value.length > 2048) return;
  if (image && /^\/uploads\/(?!\/)[^\s\\]+$/.test(value)) return value;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return;
    return url.href;
  } catch { return; }
}

export function parseAnswerCard(text: string): AnswerCardData | null {
  if (text.length > 16000) return null;
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const v = value as Record<string, unknown>;
    const field = (key: string, max: number) => typeof v[key] === 'string' ? (v[key] as string).trim().slice(0, max) : undefined;
    const title = field('title', 180), description = field('description', 4000);
    if (!title || !description) return null;
    return { title, description, meta: field('meta', 400), url: safeCardUrl(v.url), linkLabel: field('linkLabel', 80), badge: field('badge', 40), image: safeCardUrl(v.image, true) };
  } catch { return null; }
}

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: { hProperties?: Record<string, string> } };

/** GFM-style alerts preserve all Markdown and links; only their marker is removed. */
export function remarkAnswerCallouts() {
  const walk = (node: MdNode) => {
    if (node.type === 'blockquote') {
      const first = node.children?.[0]?.children?.[0];
      const marker = first?.type === 'text' && first.value?.match(/^\[!(NOTE|TIP|WARNING|CAUTION|IMPORTANT|SUCCESS)\](?:[ \t]*([^\n]*))?(?:\n|$)/i);
      if (marker && first) {
        first.value = first.value!.slice(marker[0].length);
        node.data = { ...node.data, hProperties: { 'data-callout': marker[1].toLowerCase(), 'data-callout-title': marker[2]?.trim() || '' } };
      }
    }
    node.children?.forEach(walk);
  };
  return walk;
}

/** Clipboard gets useful text and links, not the widget transport JSON. */
export function copyableAnswer(text: string): string {
  return text.replace(/```bitthink-card\s*\n([\s\S]*?)\n```/g, (block, json: string) => {
    const card = parseAnswerCard(json);
    return card ? [card.title, card.description, card.meta, card.url].filter(Boolean).join('\n') : block;
  }).replace(/^>\s*\[!(?:NOTE|TIP|WARNING|CAUTION|IMPORTANT|SUCCESS)\]\s*/gm, '> ');
}
