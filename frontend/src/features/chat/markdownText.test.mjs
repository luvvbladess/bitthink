import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const source = fs.readFileSync(new URL('./markdownText.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText;
const {normalizeMarkdown} = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const url = 'https://www.ozon.ru/product/test-5262378617/?is_apparel_size_selected=true&sh=abc';
for (const input of [`это что такое\n${url}`, url, `[товар](${url})`, `Источники\n- ${url}`, 'пример [1]']) {
  assert.equal(normalizeMarkdown(input, 'user'), input);
}
assert.equal(normalizeMarkdown(`Ответ\n\nИсточники\n- ${url}`), 'Ответ');
assert.equal(normalizeMarkdown(`Товар ${url}`), `Товар ${url}`);
const listings = `Вот объявления:\n- [Logitech G435](${url})\n- [JBL](https://www.ozon.ru/product/jbl-123/)`;
assert.equal(normalizeMarkdown(listings), listings);
const html=renderToStaticMarkup(React.createElement(ReactMarkdown,{remarkPlugins:[remarkGfm],children:normalizeMarkdown(listings)}));
assert.ok(html.includes('href="https://www.ozon.ru/product/test-5262378617/?is_apparel_size_selected=true&amp;sh=abc"'));
assert.ok(html.includes('href="https://www.ozon.ru/product/jbl-123/"'));
console.log('PASS user text and assistant listing links preserved; explicit source appendix removed');
