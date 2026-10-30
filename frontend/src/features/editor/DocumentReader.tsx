import { useEffect, useLayoutEffect, useRef, useState, type MutableRefObject } from 'react';
import { Box, IconButton, Typography } from '@mui/material';
import { Minus, Plus } from '@phosphor-icons/react';
import { API_BASE } from '@/api/client';

type Inline = { text?: string; bold?: boolean; italic?: boolean; underline?: boolean; strike?: boolean; position?: string; href?: string; image?: string; alt?: string; width?: number; height?: number };
type Paragraph = { type: 'paragraph'; heading?: number; content: Inline[]; list?: { label: string; level: number } };
type Table = { type: 'table'; rows: { header: boolean; cells: { span: number; rowSpan?: number; blocks: ReaderBlock[] }[] }[] };
export type ReaderBlock = Paragraph | Table;
export type ReadingContent = { blocks: ReaderBlock[]; warnings: string[] };

function InlineImage({ item }: { item: Inline }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [item.image]);
  return broken ? <Box component="span" sx={{ display: 'block', color: 'text.secondary', fontSize: '.875rem' }}>Изображение не загрузилось. Его можно посмотреть в «Оригинале».</Box>
    : <Box component="img" src={`${API_BASE}${item.image}`} width={item.width} height={item.height} alt={item.alt || 'Изображение документа'} loading="lazy" decoding="async" onError={() => setBroken(true)} sx={{ display: 'block', maxWidth: '100%', height: 'auto', my: 1.5 }} />;
}

function Inlines({ content }: { content: Inline[] }) {
  return <>{content.map((item, index) => {
    if (item.image) return <InlineImage key={index} item={item} />;
    const body = <Box component={item.position === 'superscript' ? 'sup' : item.position === 'subscript' ? 'sub' : 'span'} sx={{ fontWeight: item.bold ? 700 : undefined, fontStyle: item.italic ? 'italic' : undefined, textDecoration: [item.underline ? 'underline' : '', item.strike ? 'line-through' : ''].filter(Boolean).join(' ') || undefined }}>{item.text}</Box>;
    return item.href ? <Box component="a" key={index} href={item.href} target="_blank" rel="noopener noreferrer" sx={{ color: 'var(--bt-ink)', textDecoration: 'underline', textUnderlineOffset: '3px', overflowWrap: 'anywhere' }}>{body}</Box> : <Box component="span" key={index}>{body}</Box>;
  })}</>;
}

function ReaderBlocks({ blocks }: { blocks: ReaderBlock[] }) {
  const elements = [];
  for (let index = 0; index < blocks.length; index++) {
    const block = blocks[index];
    if (block.type === 'table') {
      const columns = Math.max(1, ...block.rows.map(row => row.cells.reduce((sum, cell) => sum + cell.span, 0)));
      elements.push(<Box key={index} sx={{ my: 2 }}>
        <Typography sx={{ fontSize: '.8125rem', color: 'text.secondary', mb: .5 }}>Таблицу можно прокрутить в стороны</Typography>
        <Box tabIndex={0} role="region" aria-label="Таблица документа — прокрутка по горизонтали" sx={{ overflowX: 'auto', overscrollBehaviorX: 'contain', maxWidth: '100%', border: '1px solid var(--bt-hairline)', borderRadius: '8px', '&:focus-visible': { outline: '2px solid var(--bt-mark-mid)', outlineOffset: 2 } }}>
          <Box component="table" sx={{ borderCollapse: 'collapse', width: '100%', minWidth: columns > 2 ? Math.min(1600, columns * 150) : 280, tableLayout: 'fixed', '& td, & th': { px: 1.25, py: 1, verticalAlign: 'top', borderBottom: '1px solid var(--bt-hairline)', borderRight: '1px solid var(--bt-hairline)', overflowWrap: 'anywhere' }, '& th': { bgcolor: 'var(--bt-overlay)', textAlign: 'start' }, '& p': { my: 0 } }}>
            <tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.cells.map((cell, cellIndex) => <Box component={row.header ? 'th' : 'td'} colSpan={cell.span} rowSpan={cell.rowSpan} key={cellIndex}><ReaderBlocks blocks={cell.blocks} /></Box>)}</tr>)}</tbody>
          </Box>
        </Box>
      </Box>);
    } else if (block.list) {
      const items = [block];
      while (index + 1 < blocks.length) {
        const next = blocks[index + 1];
        if (next.type !== 'paragraph' || !next.list) break;
        items.push(next); index++;
      }
      elements.push(<Box component="ul" key={index} sx={{ listStyle: 'none', p: 0, my: 1.5 }}>{items.map((item, itemIndex) => <Box component="li" key={itemIndex} sx={{ display: 'flex', gap: .75, pl: `${Math.min(item.list!.level, 3) * .75}em`, mb: .5 }}><Box component="span" sx={{ flexShrink: 0, minWidth: '1.25em' }}>{item.list!.label}</Box><Box component="span" dir="auto" sx={{ minWidth: 0, overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}><Inlines content={item.content} /></Box></Box>)}</Box>);
    } else {
      elements.push(<Box component={block.heading ? `h${block.heading}` as 'h1' : 'p'} dir="auto" key={index} sx={{ mt: block.heading && index > 0 ? '1.5em' : 0, mb: '.85em', fontSize: block.heading ? (block.heading === 1 ? '1.45em' : '1.2em') : 'inherit', fontWeight: block.heading ? 650 : 400, lineHeight: block.heading ? 1.3 : 'inherit', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}><Inlines content={block.content} /></Box>);
    }
  }
  return <>{elements}</>;
}

export function DocumentReader({ content, position }: { content: ReadingContent; position: MutableRefObject<number> }) {
  const scroll = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (scroll.current) scroll.current.scrollTop = position.current; }, [position]);
  const [fontSize, setFontSize] = useState(() => {
    try { const saved = Number(localStorage.getItem('bit-think-reader-font-size')); return saved >= 16 && saved <= 24 ? saved : 18; } catch { return 18; }
  });
  const changeSize = (value: number) => { setFontSize(value); try { localStorage.setItem('bit-think-reader-font-size', String(value)); } catch { /* Reading still works without storage. */ } };
  return <Box component="section" aria-label="Чтение документа" sx={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
    <Box sx={{ display: 'flex', alignItems: 'center', px: 1.5, flexShrink: 0, borderBottom: '1px solid var(--bt-hairline)', gap: .5 }}>
      <Typography sx={{ flex: 1, minWidth: 0, fontSize: '.8125rem', color: 'text.secondary' }}>Размер текста</Typography>
      <IconButton aria-label="Уменьшить текст" disabled={fontSize <= 16} onClick={() => changeSize(fontSize - 2)} sx={{ width: 44, height: 44 }}><Minus size={18} /></IconButton>
      <Typography aria-live="polite" sx={{ minWidth: 24, textAlign: 'center', fontSize: '.875rem' }}>{fontSize}</Typography>
      <IconButton aria-label="Увеличить текст" disabled={fontSize >= 24} onClick={() => changeSize(fontSize + 2)} sx={{ width: 44, height: 44 }}><Plus size={18} /></IconButton>
    </Box>
    <Box ref={scroll} onScroll={event => { position.current = event.currentTarget.scrollTop; }} sx={{ flex: 1, minHeight: 0, minWidth: 0, overflowY: 'auto', overflowX: 'hidden', overscrollBehaviorY: 'contain', px: { xs: 2, md: 3 }, pb: 'max(24px, env(safe-area-inset-bottom))', pt: 2 }}>
      <Box component="article" sx={{ maxWidth: '68ch', mx: 'auto', fontSize, lineHeight: 1.65, color: 'var(--bt-ink)', userSelect: 'text' }}>
        {content.blocks.length ? <ReaderBlocks blocks={content.blocks} /> : <Typography>В этом документе нет текста для режима чтения. Посмотрите его в «Оригинале».</Typography>}
      </Box>
      {content.warnings.length > 0 && <Box sx={{ maxWidth: '68ch', mx: 'auto', mt: 3, pt: 2, borderTop: '1px solid var(--bt-hairline)' }}>{content.warnings.map(warning => <Typography key={warning} sx={{ color: 'text.secondary', fontSize: '.875rem', mb: .5 }}>{warning}</Typography>)}</Box>}
    </Box>
  </Box>;
}
