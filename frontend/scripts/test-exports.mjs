import { chromium } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const base = process.env.BITTHINK_UI_BASE || 'http://127.0.0.1:5187';
const output = process.env.BITTHINK_EXPORT_OUTPUT || 'test-results/presentation-exports';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base + '/login');
  const html = '<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0}.slide{box-sizing:border-box;width:1600px;height:900px;padding:100px;background:#10242b;color:#ffffff;font:40px Arial}h1{font-size:80px}</style></head><body><section class="slide"><h1>Bit-Think</h1><p>Проверка экспорта презентации</p></section></body></html>';
  for (const format of ['html', 'png', 'pdf', 'pptx']) {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 90000 }),
      page.evaluate(async ({ html, format }) => {
        const { exportCanvas } = await import('/src/features/chat/studioExport.ts');
        await exportCanvas(html, format, 'presentation-check');
      }, { html, format }),
    ]);
    const path = `${output}/${download.suggestedFilename()}`;
    await download.saveAs(path);
    const bytes = await readFile(path);
    assert(bytes.length > 100, `${format}: empty file`);
    if (format === 'png') assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    if (format === 'pdf') assert.equal(bytes.subarray(0, 5).toString(), '%PDF-');
    if (format === 'pptx') {
      assert.equal(bytes.subarray(0, 2).toString(), 'PK');
      assert(bytes.includes(Buffer.from('ppt/presentation.xml')));
      assert(bytes.includes(Buffer.from('ppt/slides/slide1.xml')));
    }
    if (format === 'html') assert(bytes.includes(Buffer.from('Bit-Think')));
    console.log(`PASS ${format}: ${path} (${bytes.length} bytes)`);
  }
  assert.deepEqual(errors, [], 'No uncaught browser exceptions during export');
} finally { await browser.close(); }
