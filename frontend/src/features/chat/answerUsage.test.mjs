import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const source = fs.readFileSync(new URL('./AnswerUsage.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText.replace(/^import .*$/gm, '');
const { answerUsage, USAGE_QUERY } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
const row = { model: 'gpt-6-sol', calls: 1, input: 100, output: 20, cached: 30, cache_write: 0, units: 1950, retained: 0, unknown_tokens: 0, unknown_units: 0 };
const search = data => [{ query: USAGE_QUERY, summary: JSON.stringify(data) }];
assert.equal(answerUsage(), null);
assert.equal(answerUsage([{ query: USAGE_QUERY, summary: 'broken' }]), null);
assert.deepEqual(answerUsage(search({ version: 1, models: [row] })), [row]);
for (const data of [{ version: 2, models: [row] }, { version: 1, models: [] }, { version: 1, models: [{ ...row, units: -1 }] }, { version: 1, models: [{ ...row, input: true }] }, { version: 1, models: [{ ...row, cached: 101 }] }, { version: 1, models: [{ ...row, unknown_units: 2 }] }, { version: 1, models: Array(33).fill(row) }, { version: 1, models: Array(2).fill({ ...row, units: Number.MAX_SAFE_INTEGER }) }]) assert.equal(answerUsage(search(data)), null);
assert.ok(answerUsage(search({ version: 1, models: [{ ...row, unknown_tokens: 1, units: 2500 }] })));
const clarify = fs.readFileSync(new URL('./clarify.ts', import.meta.url), 'utf8');
const clarifyJS = ts.transpileModule(clarify, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const { splitSearch } = await import('data:text/javascript;base64,' + Buffer.from(clarifyJS).toString('base64'));
assert.deepEqual(splitSearch([...search({ version: 1, models: [row] }), { query: 'Source', summary: 'https://example.com' }]).sources, [{ query: 'Source', summary: 'https://example.com' }]);
console.log('PASS answer usage metadata validation');
