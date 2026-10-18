import { Children, isValidElement, useMemo, useState, type ReactNode } from 'react';
import { Alert, Box, Button, IconButton, InputAdornment, TextField, Tooltip } from '@mui/material';
import { ArrowDown, ArrowUp, ArrowsDownUp, Copy, DownloadSimple, MagnifyingGlass, PencilSimple, X } from '@phosphor-icons/react';
import { downloadBlob } from '@/api/client';
import { nextTableSort, tableDelimited, tableOrder, type TableSort } from './tableOperations';

export interface ResultTableRow { id: string; cells: ReactNode[]; text: string[] }
export function nodeText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join('');
  if (isValidElement<{ children?: ReactNode; href?: string; alt?: string }>(node)) {
    const text = nodeText(node.props.children);
    return node.props.href ? `${text} (${node.props.href})` : text || node.props.alt || '';
  }
  return '';
}

export function ResultTable({ headers, rows, title = 'Таблица', onEditRow, editable = false }: {
  headers: ReactNode[]; rows: ResultTableRow[]; title?: string;
  onEditRow?: (id: string) => void; editable?: boolean;
}) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<TableSort>(null);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const text = useMemo(() => rows.map(row => row.text), [rows]);
  const order = useMemo(() => tableOrder(text, editable ? '' : query, editable ? null : sort), [text, query, sort, editable]);
  const values = () => [headers.map(nodeText), ...order.map(index => rows[index].text)];
  const copy = async () => {
    setError(''); setFeedback('');
    try { await navigator.clipboard.writeText(tableDelimited(values(), '\t')); setFeedback('Таблица скопирована'); }
    catch { setError('Не удалось скопировать. Скачайте CSV или разрешите доступ к буферу обмена.'); }
  };
  return <Box sx={{ my: 1.5, minWidth: 0, maxWidth: '100%' }}>
    {!editable && <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, mb: 1 }}>
      <TextField size="small" value={query} onChange={e => { setQuery(e.target.value); setFeedback(''); }} placeholder="Найти в таблице" inputProps={{ 'aria-label': 'Найти в таблице' }}
        sx={{ flex: '1 1 180px', minWidth: 0, maxWidth: { sm: 300 } }}
        InputProps={{ startAdornment: <InputAdornment position="start"><MagnifyingGlass size={16} /></InputAdornment>, endAdornment: query ? <InputAdornment position="end"><IconButton size="small" aria-label="Очистить поиск в таблице" onClick={() => setQuery('')}><X size={16} /></IconButton></InputAdornment> : undefined }} />
      <Box component="span" sx={{ fontSize: 12, color: 'text.secondary', fontVariantNumeric: 'tabular-nums' }}>{order.length} / {rows.length}</Box>
      <Box sx={{ display: 'flex', ml: 'auto', gap: .5 }}>
        <Tooltip title="Скопировать видимые строки для Excel"><IconButton aria-label="Скопировать таблицу" onClick={copy} size="small"><Copy size={17} /></IconButton></Tooltip>
        <Tooltip title="Скачать видимые строки CSV"><IconButton aria-label="Скачать таблицу CSV" size="small" onClick={() => { downloadBlob(new Blob(['\ufeff', tableDelimited(values(), ';')], { type: 'text/csv;charset=utf-8' }), `${title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').slice(0, 100) || 'Таблица'}.csv`); }}><DownloadSimple size={17} /></IconButton></Tooltip>
      </Box>
    </Box>}
    {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 1 }}>{error}</Alert>}
    <Box role="status" sx={{ fontSize: 12, color: 'text.secondary' }}>{feedback}</Box>
    <Box role="region" aria-label={title} tabIndex={0} sx={{ overflowX: 'auto', maxWidth: '100%', border: '1px solid var(--bt-hairline)', borderRadius: '12px', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 } }}>
      <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem', fontVariantNumeric: 'tabular-nums', '& th, & td': { px: 1.5, py: 1.25, textAlign: 'left', verticalAlign: 'top', borderBottom: '1px solid var(--bt-hairline)', minWidth: 90, overflowWrap: 'break-word' }, '& tr > :first-of-type': { minWidth: 150 }, '& th': { bgcolor: 'var(--bt-paper)', fontWeight: 600 }, '& td': { maxWidth: 320 }, '& tr:last-child td': { borderBottom: 0 }, '& tbody tr:hover': { bgcolor: 'var(--bt-overlay-faint)' } }}>
        <thead><tr>{headers.map((header, column) => <th key={column} scope="col" aria-sort={sort?.column === column && !editable ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
          {editable ? header : <Box component="button" type="button" onClick={() => setSort(nextTableSort(sort, column))} aria-label={`Сортировать: ${nodeText(header)}`} sx={{ display: 'flex', gap: .75, alignItems: 'center', minHeight: 32, p: 0, border: 0, bgcolor: 'transparent', color: 'inherit', font: 'inherit', fontWeight: 'inherit', cursor: 'pointer', '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 3 } }}>{header}<Box component="span" sx={{ display: 'flex', flexShrink: 0, color: sort?.column === column ? 'primary.light' : 'text.secondary' }}>{sort?.column === column ? sort.direction === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} /> : <ArrowsDownUp size={14} />}</Box></Box>}
        </th>)}{onEditRow && !editable && <th scope="col"><Box component="span" sx={{ fontSize: 12, color: 'text.secondary' }}>Правка</Box></th>}</tr></thead>
        <tbody>{order.map(index => <tr key={rows[index].id}>{rows[index].cells.map((cell, column) => <td key={column}>{cell}</td>)}{onEditRow && !editable && <td><Tooltip title="Изменить только эту строку"><IconButton aria-label={`Изменить строку ${index + 1}`} size="small" onClick={() => onEditRow(rows[index].id)}><PencilSimple size={16} /></IconButton></Tooltip></td>}</tr>)}</tbody>
      </Box>
      {!order.length && <Box sx={{ p: 2, fontSize: 14, color: 'text.secondary' }}> {query ? 'Ничего не найдено. Попробуйте другой запрос.' : 'В таблице пока нет строк.'}{query && <Button size="small" onClick={() => setQuery('')}>Сбросить поиск</Button>}</Box>}
    </Box>
    {!editable && <Box sx={{ mt: .75, fontSize: 12, color: 'text.secondary' }}>Нажмите заголовок для сортировки.<Box component="span" sx={{ display: { xs: 'inline', sm: 'none' } }}> Листайте таблицу в сторону.</Box></Box>}
  </Box>;
}

/** Preserve ReactMarkdown's links and emphasis; only the surrounding table gets controls. */
export function MarkdownResultTable({ children }: { children?: ReactNode }) {
  const sections = Children.toArray(children).filter(isValidElement<{ children?: ReactNode }>);
  const rowCells = (row: ReactNode): ReactNode[] => isValidElement<{ children?: ReactNode }>(row)
    ? Children.toArray(row.props.children).filter(isValidElement<{ children?: ReactNode }>).map(cell => cell.props.children) : [];
  const head = sections.find(section => section.type === 'thead');
  const body = sections.find(section => section.type === 'tbody');
  if (!head || !body) return <Box sx={{ overflowX: 'auto' }}><table>{children}</table></Box>;
  const headers = rowCells(Children.toArray(head.props.children)[0]);
  const rows = Children.toArray(body.props.children).filter(isValidElement).map((row, index) => {
    const cells = rowCells(row); return { id: String(row.key ?? index), cells, text: cells.map(nodeText) };
  });
  return <ResultTable headers={headers} rows={rows} />;
}
