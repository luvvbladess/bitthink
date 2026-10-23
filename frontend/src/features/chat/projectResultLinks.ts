import type { SearchItem } from './clarify';
export type ProjectResultRef = { projectId: string; entryId: string; title: string; type: 'table' | 'report' | 'slides'; revision: number };
export type ResultEditRequest = ProjectResultRef & { requestId: string; selection?: string };
export function resultReferences(search?: SearchItem[]): ProjectResultRef[] {
  const refs = new Map<string, ProjectResultRef>();
  for (const item of search || []) {
    if (item.query !== '__project_results__') continue;
    try {
      const data = JSON.parse(item.summary);
      if (!Array.isArray(data)) continue;
      for (const row of data.slice(0, 10)) {
        if (!row || !/^[a-f0-9]{32}$/.test(row.project_id) || !/^[a-f0-9]{32}$/.test(row.entry_id) || !['table','report','slides'].includes(row.type) || !Number.isInteger(row.revision) || row.revision < 1) continue;
        refs.set(row.entry_id, { projectId: row.project_id, entryId: row.entry_id, title: String(row.title || 'Результат').slice(0, 255), type: row.type, revision: row.revision });
      }
    } catch { /* Old messages and invalid metadata remain ordinary answers. */ }
  }
  return [...refs.values()];
}
