/** View operations never mutate the result or change its verification state. */
export type TableSort = { column: number; direction: 'asc' | 'desc' } | null;
const collator = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' });
const missing = /^(?:[—–-]|н\/?д|нет данных|неизвестно)?$/i;

function numeric(value: string): number | null {
  // Only an unambiguous single number. Ranges, dimensions and two bank prices stay text.
  const text = value.trim().replace(/[\s\u00a0\u202f]/g, '');
  if (!/^[+-]?\d+(?:[.,]\d+)?(?:₽|руб\.?|%|шт\.?|\/5)?$/i.test(text)) return null;
  const number = Number.parseFloat(text.replace(',', '.'));
  return Number.isFinite(number) ? number : null;
}

export function tableOrder(rows: readonly (readonly string[])[], query: string, sort: TableSort): number[] {
  const terms = query.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean);
  const indices = rows.map((_, index) => index).filter(index => {
    const text = rows[index].join(' ').toLocaleLowerCase('ru');
    return terms.every(term => text.includes(term));
  });
  if (!sort) return indices;
  return indices.sort((a, b) => {
    const left = (rows[a][sort.column] || '').trim();
    const right = (rows[b][sort.column] || '').trim();
    const lm = missing.test(left), rm = missing.test(right);
    if (lm !== rm) return lm ? 1 : -1; // Unknown values always last.
    const ln = numeric(left), rn = numeric(right);
    const compared = ln !== null && rn !== null ? ln - rn : collator.compare(left, right);
    return (sort.direction === 'asc' ? compared : -compared) || a - b;
  });
}

export function nextTableSort(current: TableSort, column: number): TableSort {
  if (current?.column !== column) return { column, direction: 'asc' };
  return current.direction === 'asc' ? { column, direction: 'desc' } : null;
}

function safeSpreadsheetCell(value: string): string {
  // Spreadsheet formula injection also occurs after whitespace / control characters.
  return /^[\s\u0000-\u001f]*[=+@-]/.test(value) ? `'${value}` : value;
}

export function tableDelimited(rows: readonly (readonly string[])[], delimiter: ';' | '\t'): string {
  return rows.map(row => row.map(cell => {
    const safe = safeSpreadsheetCell(cell);
    if (delimiter === '\t') return safe.replace(/[\t\r\n]+/g, ' ');
    return `"${safe.replace(/"/g, '""')}"`;
  }).join(delimiter)).join('\r\n');
}
