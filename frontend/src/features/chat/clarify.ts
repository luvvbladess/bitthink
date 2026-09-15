export const CLARIFY_QUERY = '__clarify__';

export interface ClarifyQuestion {
  prompt: string;
  options: string[];
}

export interface SearchItem {
  query: string;
  summary: string;
}

export function splitSearch(search?: SearchItem[] | null): {
  sources: SearchItem[];
  questions: ClarifyQuestion[];
} {
  const sources: SearchItem[] = [];
  let questions: ClarifyQuestion[] = [];
  for (const item of search || []) {
    if (item?.query !== CLARIFY_QUERY) {
      if (item?.query || item?.summary) sources.push(item);
      continue;
    }
    try {
      const parsed = JSON.parse(item.summary || '');
      const list = Array.isArray(parsed?.questions) ? parsed.questions : [];
      questions = list
        .map((entry: { prompt?: string; options?: string[] }) => ({
          prompt: String(entry?.prompt || '').trim(),
          options: (entry?.options || []).map((option) => String(option || '').trim()).filter(Boolean).slice(0, 6),
        }))
        .filter((entry: ClarifyQuestion) => entry.prompt.length >= 8 && entry.options.length >= 2)
        .slice(0, 3);
    } catch {
      questions = [];
    }
  }
  return { sources, questions };
}

function isOtherOption(label: string): boolean {
  return /^(other|другое|свой вариант)$/i.test(label.trim());
}

export function formatClarifyReply(
  questions: ClarifyQuestion[],
  answers: Array<string | null>,
): string {
  const lines = questions.map((question, index) => {
    const answer = (answers[index] || '').trim();
    return `${index + 1}. ${question.prompt} – ${answer || 'пропущено'}`;
  });
  if (answers.every((item) => !item)) {
    return 'Уточнения пропущены. Действуй по здравому смыслу.';
  }
  return `Уточнения по задаче:\n${lines.join('\n')}`;
}

export function isClarifyReply(text: string): boolean {
  const stripped = (text || '').trim();
  return stripped.startsWith('Уточнения по задаче:') || stripped.startsWith('Уточнения пропущены');
}

export const CLARIFY_ACK = 'Ответы получены';

export function isClarifyMessage(search?: SearchItem[] | null): boolean {
  return splitSearch(search).questions.length > 0;
}

export { isOtherOption };
