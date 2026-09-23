import { splitSearch, type SearchItem } from './clarify';

export type { SearchItem };

export interface ParsedSource {
  url: string;
  domain: string;
  title: string;
  snippet: string;
  favicon: string;
}

export function sourceUrl(summary: string): string {
  const firstLine = (summary || '').split(/\r?\n/, 1)[0].trim();
  return /^https?:\/\//i.test(firstLine) ? firstLine : '';
}

export function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export function sourcesLabel(count: number): string {
  const n10 = count % 10;
  const n100 = count % 100;
  if (n10 === 1 && n100 !== 11) return `${count} источник`;
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return `${count} источника`;
  return `${count} источников`;
}

export function parseSources(items?: SearchItem[] | null): ParsedSource[] {
  const seen = new Set<string>();
  const result: ParsedSource[] = [];
  for (const item of items || []) {
    const url = sourceUrl(item.summary || '');
    // Pilot also stores its employees' task briefs here ("load_skill prices…").
    // Without a link they are internal notes, not sources.
    if (!url) continue;
    const key = url;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const domain = sourceDomain(url || item.query || '');
    const snippet = (item.summary || '').split(/\r?\n/).slice(1).join(' ').trim();
    result.push({
      url,
      domain: domain || 'источник',
      title: (item.query || domain || 'Источник').trim(),
      snippet,
      favicon: domain ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32` : '',
    });
  }
  return result;
}

export function collectDialogueSources(messages: Array<{ search?: SearchItem[] | null }>): ParsedSource[] {
  const items: SearchItem[] = [];
  for (const message of messages) {
    items.push(...splitSearch(message.search).sources);
  }
  return parseSources(items);
}
