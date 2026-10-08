/** Cleans a model reply for display: drops the trailing sources list, bare URLs and stray markers. */
export function normalizeMarkdown(text: string, role: 'user' | 'assistant' = 'assistant'): string {
  // User messages are the original input, not a model-generated source list.
  if (role === 'user') return text;
  const sourceHeading = /^(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?(?:источники|sources)\s*:?\s*(?:\*{1,2}|_{1,2})?\s*$/i;
  const sourceItem = /^(?:[-*+•‣∙·]|\d+[.)])?\s*(?:\*{1,2}|_{1,2})?источник(?:и)?\b/i;
  const sourceList = /^(?:[-*+•‣∙·]|\d+[.)])\s*(?:\[[^\]]+\]\(https?:\/\/|<?https?:\/\/|\[\d+\])/i;
  const isSourceLine = (line: string) => {
    const stripped = line.trim();
    return !stripped || sourceHeading.test(stripped) || sourceItem.test(stripped) || sourceList.test(stripped) || /^\[\d+\]\s+/.test(stripped);
  };
  const lines = text.split('\n');
  let cut = lines.length;
  for (let index = 0; index < lines.length; index += 1) {
    const stripped = lines[index].trim();
    if (!stripped) continue;
    if ((sourceHeading.test(stripped) || sourceItem.test(stripped)) && lines.slice(index).every(isSourceLine)) {
      cut = index;
      break;
    }
  }
  const kept = lines.slice(0, cut);
  while (kept.length && !kept[kept.length - 1].trim()) kept.pop();
  return kept
    .join('\n')
    .replace(/^[ \t]*[•‣∙·][ \t]+/gm, '- ')
    .replace(/^[ \t]*(?:[-*+•‣∙·]|\d+[.)])[ \t]*$/gm, '')
    .replace(/\s*\[\d+\]/g, '')
    .replace(/\s*\((?:www\.)?(?:[a-z0-9-]+\.)+(?:xn--[a-z0-9-]+|[a-z]{2,24})(?:\/[^\s)]*)?\)/gi, '')
    .replace(/\(xn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+\)/gi, '')
    .replace(/\bxn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+\b/gi, '')
    .replace(/([A-Za-zА-Яа-яЁё])\.[\u0530-\u058F\u10A0-\u10FF\u0600-\u06FF\u0590-\u05FF\u0900-\u097F\u4E00-\u9FFF\u3040-\u30FF]+/g, '$1')
    .replace(/\n{3,}/g, '\n\n');
}
