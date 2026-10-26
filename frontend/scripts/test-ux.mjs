import { chromium, expect as baseExpect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';

const base = process.env.BITTHINK_UI_BASE || 'http://127.0.0.1:5187';
const expect = baseExpect.configure({ timeout: 15000 });
const output = process.env.BITTHINK_UI_OUTPUT || 'test-results/ux';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
let passed = 0;
const errors = [];

async function fixture(options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1440, height: 900 }, hasTouch: Boolean(options.touch) });
  const page = await context.newPage();
  if (options.clock) await page.clock.install();
  if (options.observeWelcome) await page.addInitScript(() => {
    window.auditWelcomeMounts = [];
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        if (node.textContent?.includes('С чего начнём?')) window.auditWelcomeMounts.push(performance.now());
      }
    }).observe(document, { childList: true, subtree: true });
  });
  if (options.failSettingsChunk) {
    if (!options.allowAutoRecovery) await page.addInitScript(() => sessionStorage.setItem('bit-think-route-refresh', String(Date.now())));
    await page.route(/\/(?:assets\/SettingsPage-[^/]+\.js|src\/pages\/SettingsPage\.tsx)(?:\?.*)?$/, route => route.abort());
  }
  if (options.runtimeSettingsError) await page.route(/\/(?:assets\/SettingsPage-[^/]+\.js|src\/pages\/SettingsPage\.tsx)(?:\?.*)?$/, route => route.fulfill({ contentType: 'application/javascript', body: 'export default function BrokenSettings() { if (!window.auditRuntimeRecovered) throw new Error("UI_TEST_RUNTIME_FAILURE"); return "Раздел восстановлен"; }' }));
  if (options.failChatChunkOnce) {
    let failed = false;
    await page.route(/\/(?:assets\/ChatPage-[^/]+\.js|src\/pages\/ChatPage\.tsx)(?:\?.*)?$/, route => { if (!failed) { failed = true; return route.abort(); } return route.continue(); });
  }
  if (options.failChatChunkPersistent) await page.route(/\/(?:assets\/ChatPage-[^/]+\.js|src\/pages\/ChatPage\.tsx)(?:\?.*)?$/, route => { state.chatDownloadAttempts = (state.chatDownloadAttempts || 0) + 1; return route.abort(); });
  const state = { auth: options.auth || 'ok', historyError: false, delay: {}, sends: [], uploads: [], created: [], historyLoads: [], failFile: '', ...options };
  const profile = { id: 'audit-user', email: 'audit@example.com', first_name: 'Анна', role: options.admin ? 'admin' : 'user', subscription_tier: 'pro', selected_model: 'auto' };
  const conversations = [
    { id: 'chat-a', title: 'Первая беседа', is_active: true, message_count: 2 },
    { id: 'chat-b', title: 'Вторая беседа', is_active: false, message_count: 2 },
  ];
  const history = {
    'chat-a': [{ id: 'a1', role: 'user', content: 'Вопрос первой беседы' }, { id: 'a2', role: 'assistant', content: 'Ответ первой беседы. Здесь удобно читать и продолжать работу.' }],
    'chat-b': [{ id: 'b1', role: 'user', content: 'Вопрос второй беседы' }, { id: 'b2', role: 'assistant', content: 'Ответ второй беседы.' }],
  };
  if (options.imageHistory) history['chat-a'].push({ id: 'image-original', role: 'assistant', content: '![Эскиз](/uploads/audit-source.png)' });
  if (options.clarify) history['chat-a'].push({ id: 'clarify', role: 'assistant', content: 'Уточните задачу', search: [{ query: '__clarify__', summary: JSON.stringify({ questions: [{ prompt: 'Какой формат результата нужен?', options: ['Таблица', 'Отчёт'] }] }) }] });
  await page.route('**/uploads/**', route => route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvXkAAAAASUVORK5CYII=', 'base64') }));
  page.on('pageerror', error => {
    if (options.failSettingsChunk && /Failed to fetch dynamically imported module: .*SettingsPage/.test(error.message)) return;
    if ((options.failChatChunkOnce || options.failChatChunkPersistent) && /Failed to fetch dynamically imported module: .*ChatPage/.test(error.message)) return;
    if (options.runtimeSettingsError && error.message === 'UI_TEST_RUNTIME_FAILURE') return;
    errors.push(error.message); console.error('BROWSER', error.message);
  });
  page.on('console', message => { if (message.type() === 'error') console.error('CONSOLE', message.text()); });
  await page.addInitScript(({ profile, theme }) => {
    localStorage.setItem('bit-think-color-mode', theme);
    if (profile) localStorage.setItem('gpt-ultra-auth', JSON.stringify({ state: { accessToken: 'audit-access', refreshToken: 'audit-refresh', user: profile }, version: 0 }));
  }, { profile: options.signedOut ? null : profile, theme: options.theme || 'dark' });
  if (options.mockVoice) await page.addInitScript(() => {
    window.auditStoppedTracks = 0;
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async () => ({ getTracks: () => [{ stop: () => window.auditStoppedTracks++ }] }) });
    window.MediaRecorder = class {
      state = 'inactive'; mimeType = 'audio/webm';
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; this.onstop?.(); }
    };
  });
  await page.route('**/api/**', async route => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue();
    const path = new URL(route.request().url()).pathname.slice(4);
    const method = route.request().method();
    if (options.handleRoute && await options.handleRoute({ path, method, route, state, profile, history })) return;
    let data = {};
    if (path === '/diagnostics/client-error') {
      (state.diagnostics ||= []).push(route.request().postDataJSON());
      data = { report_id: state.diagnostics.at(-1).report_id };
    } else if (path === '/diagnostics/performance') {
      if (method === 'POST') (state.performanceReports ||= []).push(route.request().postDataJSON());
      data = method === 'POST' ? { ok: true } : { days: 7, metrics: [] };
    } else if (path === '/auth/me') {
      if (state.auth === 'network') return route.abort('failed');
      if (state.auth === '500') return route.fulfill({ status: 500, json: { detail: 'Temporary outage' } });
      if (state.auth.startsWith('refresh')) return route.fulfill({ status: 401, json: {} });
      data = profile;
    } else if (path === '/auth/refresh') {
      if (state.auth === 'refresh-network') return route.abort('failed');
      return route.fulfill({ status: state.auth === 'refresh-invalid' ? 401 : 503, json: {} });
    } else if (path === '/models') {
      if (state.modelLoadFailure) return route.fulfill({ status: 503, json: { detail: 'Каталог временно недоступен' } });
      const selected = state.selectedModel || options.model || 'auto';
      data = {
        selected, selectedName: selected === 'gpt-6-luna' ? 'Быстрый' : undefined,
        reasoningEffort: state.modelEffort || 'medium', imageQuality: state.imageQuality || 'high',
        supportsReasoningEffort: ['auto', 'gpt-6-luna', 'gpt-6-sol', 'gpt-6-astra'].includes(selected),
        computerAvailable: true, studioAvailable: true, searchAvailable: !state.searchLocked,
        docgenAvailable: Boolean(options.fullModes), astraAvailable: Boolean(options.fullModes), researchModel: options.fullModes ? 'gpt-6-sol' : null,
        models: [{ id: 'auto', name: 'Экспресс', available: true }, { id: 'gpt-6-luna', name: 'Быстрый', available: true }, { id: 'director', name: 'Оркестратор', available: true }, { id: 'studio', name: 'Студия', available: true }],
      };
    } else if (path === '/models/select') {
      (state.modeSelections ||= []).push(route.request().postDataJSON().model);
      if (state.modeDelay) await new Promise(resolve => setTimeout(resolve, state.modeDelay));
      if (state.modeFailure) return route.fulfill({ status: 503, json: { detail: 'Временная ошибка сохранения' } });
      state.selectedModel = route.request().postDataJSON().model;
      data = { ok: true, model: state.selectedModel };
    } else if (path === '/models/reasoning' || path === '/models/image-quality') {
      if (state.preferenceDelay) await new Promise(resolve => setTimeout(resolve, state.preferenceDelay));
      if (state.preferenceFailure) return route.fulfill({ status: 503, json: { detail: 'Временная ошибка настроек' } });
      if (path.endsWith('reasoning')) { state.modelEffort = route.request().postDataJSON().effort; data = { ok: true, effort: state.modelEffort }; }
      else { state.imageQuality = route.request().postDataJSON().quality; data = { ok: true, quality: state.imageQuality }; }
    }
    else if (path === '/conversations' && method === 'POST') {
      state.createRequests = (state.createRequests || 0) + 1;
      if (state.failCreate) return route.fulfill({ status: 503, json: { detail: 'Temporary outage' } });
      if (state.createDelay) await new Promise(resolve => setTimeout(resolve, state.createDelay));
      const id = `chat-new-${state.created.length + 1}`;
      conversations.forEach(item => { item.is_active = false; });
      data = { id, title: 'Новый чат', is_active: true, message_count: 0 };
      history[id] = [];
      conversations.unshift(data);
      state.created.push(id);
      state.activeId = id;
    }
    else if (path === '/conversations') {
      if (state.listDelay) await new Promise(resolve => setTimeout(resolve, state.listDelay));
      const params = new URL(route.request().url()).searchParams;
      const offset = Number(params.get('offset') || 0);
      data = conversations.slice(offset, offset + Number(params.get('limit') || conversations.length));
    }
    else if (path.endsWith('/activate')) {
      const id = path.split('/')[2];
      if (state.delay[id]) await new Promise(resolve => setTimeout(resolve, state.delay[id]));
      conversations.forEach(item => { item.is_active = item.id === id; });
      state.activeId = id;
      (state.activations ||= []).push(id);
      data = { ok: true };
    } else if (path.endsWith('/messages') || path.endsWith('/history')) {
      state.historyLoads.push(path.split('/')[2]);
      if (state.historyDelay?.[path.split('/')[2]]) await new Promise(resolve => setTimeout(resolve, state.historyDelay[path.split('/')[2]]));
      if (state.historyError) return route.fulfill({ status: 503, json: { detail: 'Temporary outage' } });
      data = history[path.split('/')[2]] || [];
      if (path.endsWith('/history')) data = { items: data, has_more: false, before: null, has_newer: false };
    } else if (path === '/chat/jobs') data = { jobs: [] };
    else if (path === '/projects' || path === '/computer/tasks' || path === '/connectors') data = [];
    else if (path.startsWith('/projects/chat/')) data = { project_id: null };
    else if (path === '/billing/subscription') data = { tier: 'pro', name: 'Pro', chat: { used: 0, limit: 1000000 }, computer: { used: 0, limit: 1000000 }, windows: {} };
    else if (path === '/models/prompts') data = { prompts: [], active_index: null };
    else if (path === '/skills') data = { items: [], custom_count: 0, custom_limit: 20 };
    else if (path === '/memory') data = { notes: '', enabled: true, updated_at: 0 };
    else if (path === '/billing/plans') data = { plans: [] };
    else if (path === '/documents' && method === 'POST') {
      const body = route.request().postDataBuffer().toString();
      const name = /filename="([^"]+)"/.exec(body)?.[1] || 'file';
      state.uploads.push(name);
      if (state.uploadDelay) await new Promise(resolve => setTimeout(resolve, state.uploadDelay));
      if (name === state.failFile) return route.fulfill({ status: 503, json: { detail: 'Файл временно недоступен' } });
      data = { message: { id: 'file-' + name, role: 'user', content: '', attachment: { name, status: 'done', type: 'document' } } };
    }
    await route.fulfill({ json: data });
  });
  await page.routeWebSocket(/\/chat\/ws$/, socket => {
    state.socketConnections = (state.socketConnections || 0) + 1;
    let silent = false;
    socket.onClose(() => { state.socketCloses = (state.socketCloses || 0) + 1; });
    socket.onMessage(raw => {
      const event = JSON.parse(String(raw));
      if (event.type === 'auth') {
        state.socketAuths = (state.socketAuths || 0) + 1;
        silent = state.silentFirstSocket && state.socketAuths === 1;
        socket.send(JSON.stringify({ type: 'jobs', payload: { jobs: [] } }));
      }
      if (event.type === 'ping' && !silent) socket.send(JSON.stringify({ type: 'pong', payload: {} }));
      if (event.type === 'message') {
        if (state.dropFirstReceipt) {
          (state.deliveryAttempts ||= []).push(event.payload.request_id);
          if (!state.receiptDropped) {
            state.receiptDropped = true;
            state.sends.push(event.payload);
            history[event.payload.conversation_id].push({ id: 'receipt-user', role: 'user', content: event.payload.content }, { id: 'receipt-answer', role: 'assistant', content: 'Ответ сохранён до переподключения.' });
            socket.close();
          } else socket.send(JSON.stringify({ type: 'accepted', payload: { conversation_id: event.payload.conversation_id, request_id: event.payload.request_id, status: 'completed' } }));
          return;
        }
        if (event.payload.request_id) socket.send(JSON.stringify({ type: 'accepted', payload: { conversation_id: event.payload.conversation_id, request_id: event.payload.request_id } }));
        state.sends.push(event.payload);
        const id = event.payload.conversation_id;
        if (state.streamBurst) {
          history[id].push({ id: 'burst-user', role: 'user', content: event.payload.content });
          state.burstAnswer = 'Поток: ' + Array.from({ length: 100 }, (_, index) => `${index}, `).join('');
          socket.send(JSON.stringify({ type: 'chunk', payload: { conversation_id: id, text: 'Поток: ' } }));
          for (let index = 0; index < 100; index++) socket.send(JSON.stringify({ type: 'chunk', payload: { conversation_id: id, text: `${index}, ` } }));
          return;
        }
        if (state.holdAnswer && id === 'chat-a') {
          history[id].push({ id: 'pending-' + state.sends.length, role: 'user', content: event.payload.content });
          state.finishHeldAnswer = () => {
            history[id].push({ id: 'background-reply', role: 'assistant', content: 'Ответ завершён в другом разделе.' });
            socket.send(JSON.stringify({ type: 'chunk', payload: { conversation_id: id, text: 'Ответ завершён в другом разделе.' } }));
            socket.send(JSON.stringify({ type: 'done', payload: { conversation_id: id } }));
          };
          socket.send(JSON.stringify({ type: 'status', payload: { conversation_id: id, text: 'Готовлю ответ' } }));
          return;
        }
        history[id].push({ id: 'sent-' + state.sends.length, role: 'user', content: event.payload.content }, { id: 'reply-' + state.sends.length, role: 'assistant', content: 'Проверенный новый ответ.' });
        socket.send(JSON.stringify({ type: 'chunk', payload: { conversation_id: id, text: 'Проверенный новый ответ.' } }));
        socket.send(JSON.stringify({ type: 'done', payload: { conversation_id: id } }));
      }
    });
  });
  await page.goto(base + (options.startPath || '/chat'));
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  async function select(title) {
    const menu = page.getByRole('button', { name: 'Открыть список бесед', exact: true });
    if (await menu.isVisible()) await menu.click();
    await page.getByRole('button', { name: `Открыть беседу ${title}`, exact: true }).click();
  }
  return { context, page, state, input, select };
}

async function test(name, run) {
  if (process.env.BITTHINK_UI_FILTER && !name.includes(process.env.BITTHINK_UI_FILTER)) return;
  try { await run(); passed++; console.log('PASS ' + name); }
  catch (error) { console.error('FAIL ' + name); throw error; }
}

async function reachable(locator, page, label) {
  await expect(locator).toBeVisible();
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const viewport = page.viewportSize();
  assert(box && box.x >= 0 && box.y >= 54 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1, `${label} must remain below the header and inside the viewport: ${JSON.stringify(box)}`);
  await expect.poll(() => locator.evaluate(element => {
    const r = element.getBoundingClientRect();
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return top === element || element.contains(top);
  }), { message: `${label} must receive pointer input after transitions` }).toBe(true);
}

async function projectFixture(options = {}) {
  const project = { id: 'demo', name: 'Презентация продукта', chat_ids: ['chat-a'] };
  const spec = { type: 'table', title: 'Сравнение поставщиков', columns: [{ id: 'name', label: 'Поставщик' }, { id: 'price', label: 'Цена' }], rows: [{ id: 'r1', cells: { name: 'Первый поставщик', price: '1500' }, state: 'pending' }] };
  const entry = { id: 'table', title: spec.title, kind: 'result', revision: 1, body: JSON.stringify(spec), current_revision: 1 };
  const f = await fixture({ ...options, handleRoute: async ({ path, method, route, state }) => {
    let data;
    if (path === '/projects') data = [project];
    else if (path === '/projects/chat/chat-a') data = { project_id: 'demo' };
    else if (path === '/projects/demo/workspace') data = { project, entries: [entry], chats: [{ id: 'chat-a', title: 'Первая беседа' }] };
    else if (path === '/projects/demo/suggestions') data = [];
    else if (path === '/projects/demo/entries/table/history') data = [{ revision: entry.revision, title: entry.title }];
    else if (path === '/projects/demo/entries/table') data = entry;
    else if (path === '/projects/demo/results/table' && method === 'PUT') {
      if (state.saveError) { await route.fulfill({ status: 409, json: { detail: 'Версия изменилась. Обновите результат.' } }); return true; }
      const body = route.request().postDataJSON();
      assert.equal(body.expected_revision, entry.revision);
      state.savedSpec = body.spec;
      entry.body = JSON.stringify(body.spec); entry.revision++; entry.current_revision++;
      data = entry;
    } else if (path === '/documents/upload') { state.wrongUpload = true; await route.fulfill({ status: 404, json: { detail: 'Not Found' } }); return true; }
    else if (path === '/documents' && method === 'POST') {
      state.projectUploads = (state.projectUploads || 0) + 1;
      if (state.uploadError) { await route.fulfill({ status: 400, json: { detail: 'Не удалось прочитать документ' } }); return true; }
      data = { ok: true, message: { id: 'file', role: 'user', content: '' } };
    } else if (path === '/projects/chat/chat-a/documents') { state.lookupFilename = new URL(route.request().url()).searchParams.get('filename'); state.documentReads = (state.documentReads || 0) + 1; data = [{ id: 42, filename: 'brief.txt' }]; }
    else if (path === '/projects/demo/documents') { state.boundDocument = route.request().postDataJSON().document_id; data = { id: 'file', title: 'brief.txt', kind: 'file', revision: 1 }; }
    else if (path === '/projects/demo/entries/file') data = { id: 'file', title: 'brief.txt', kind: 'file', revision: 1, body: 'Материалы для презентации' };
    else if (path === '/projects/demo/entries/file/history') data = [];
    else if (path === '/projects/chat/chat-a/context') data = { project_id: 'demo', web: true, include_memory: true, entry_ids: null, last_used: [] };
    else return false;
    await route.fulfill({ json: data }); return true;
  } });
  await expect(f.input).toBeEnabled();
  const menu = f.page.getByRole('button', { name: 'Открыть список бесед', exact: true });
  if (await menu.isVisible()) await menu.click();
  await f.page.getByRole('button', { name: /^Презентация продукта/ }).click();
  f.workspace = f.page.getByRole('region', { name: 'Рабочая область проекта', exact: true });
  await expect(f.workspace).toBeVisible();
  return f;
}

async function sidebarFixture(options = {}) {
  const conversations = [
    { id: 'chat-a', title: 'Первая беседа', message_count: 2, is_active: true, updated_at: new Date().toISOString() },
    { id: 'chat-b', title: 'Вторая беседа', message_count: 2, is_active: false, updated_at: new Date().toISOString() },
    { id: 'shared', title: 'Общий чат команды', message_count: 0, shared: true, role: 'member' },
  ];
  const project = { id: 'demo', name: 'Презентация продукта', chat_ids: ['chat-b'] };
  const f = await fixture({ ...options, handleRoute: async ({ path, method, route, state }) => {
    if (path === '/conversations' && method === 'GET') { await route.fulfill({ json: conversations }); return true; }
    if (path === '/projects') { await route.fulfill({ json: [project] }); return true; }
    if (path.startsWith('/projects/chat/') && path.endsWith('/context')) {
      await route.fulfill({ json: { project_id: 'demo', entry_ids: null, include_memory: true, web: true, last_used: [] } }); return true;
    }
    if (path.startsWith('/projects/chat/')) {
      const id = path.split('/').at(-1);
      if (method === 'PUT') {
        const pid = route.request().postDataJSON().project_id;
        project.chat_ids = project.chat_ids.filter(cid => cid !== id);
        if (pid) project.chat_ids.push(id);
        state.moves = [...(state.moves || []), { id, pid }];
      }
      await route.fulfill({ json: { project_id: project.chat_ids.includes(id) ? 'demo' : null } }); return true;
    }
    if (path === '/conversations/chat-a' && method === 'PATCH') {
      conversations[0].title = route.request().postDataJSON().title;
      state.renames = [...(state.renames || []), conversations[0].title];
      await route.fulfill({ json: conversations[0] }); return true;
    }
  } });
  await expect(f.input).toBeEnabled();
  const opener = f.page.getByRole('button', { name: 'Открыть список бесед', exact: true });
  if (await opener.isVisible()) await opener.click();
  f.sidebar = f.page.getByRole('navigation', { name: 'Беседы и проекты', exact: true });
  await expect(f.sidebar).toBeVisible();
  return f;
}

try {
  await test('modes: failed initial catalog offers recovery while preserving typed text', async () => {
    const f = await fixture({ modelLoadFailure: true });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Черновик до загрузки режимов');
      await expect(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true })).toBeDisabled();
      const retry = f.page.getByRole('button', { name: 'Повторить загрузку режимов', exact: true });
      await expect(retry).toBeVisible(); f.state.modelLoadFailure = false; await retry.click();
      await expect(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true })).toBeEnabled();
      await expect(f.input).toHaveValue('Черновик до загрузки режимов');
      assert.equal(f.state.sends.length, 0);
    } finally { await f.context.close(); }
  });

  for (const width of [320, 1440]) await test(`modes: every available mode switches without sending or losing a draft ${width}`, async () => {
    const f = await fixture({ fullModes: true, viewport: { width, height: 900 } });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Не потерять текст при переключении');
      const choices = [['Поиск', 'kimi-k2.6'], ['Исследование', 'gpt-6-sol'], ['Astra', 'gpt-6-astra'], ['Студия', 'studio'], ['Документы', 'docgen'], ['Оркестратор', 'director'], ['Экспресс', 'auto']];
      for (const [label, model] of choices) {
        await f.page.getByRole('button', { name: /^Режим ответа:/ }).click();
        const dialog = f.page.getByRole('dialog', { name: 'Выбор режима', exact: true });
        const row = dialog.getByRole('button', { name: new RegExp('^' + label + ' ') });
        if (!await row.isVisible()) await dialog.getByRole('button', { name: /^Ещё/ }).click();
        await row.click();
        await expect(f.page.getByRole('button', { name: `Режим ответа: ${label}`, exact: true })).toBeVisible();
        await expect(dialog).toBeHidden(); await expect(f.input).toHaveValue('Не потерять текст при переключении');
        assert.equal(f.state.selectedModel, model);
      }
      assert.equal(f.state.sends.length, 0);
      await f.page.screenshot({ path: `${output}/modes-composer-${width}.png`, fullPage: true });
    } finally { await f.context.close(); }
  });
  await test('modes: an existing direct model is never silently changed to Auto', async () => {
    const f = await fixture({ model: 'gpt-6-luna' });
    try {
      await expect(f.input).toBeEnabled();
      await expect(f.page.getByRole('button', { name: 'Режим ответа: Быстрый', exact: true })).toBeVisible();
      await f.input.fill('Проверка выбранной модели'); await f.input.press('Enter');
      await expect.poll(() => f.state.sends.length).toBe(1);
      assert.equal(f.state.sends[0].model, 'gpt-6-luna');
      assert.deepEqual(f.state.modeSelections || [], []);
    } finally { await f.context.close(); }
  });
  await test('modes: failed selection stays open and retry commits only after acknowledgement', async () => {
    const f = await fixture({ modeFailure: true });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Черновик переживёт ошибку');
      await f.page.getByRole('button', { name: 'Режим ответа: Экспресс', exact: true, includeHidden: true }).click();
      const dialog = f.page.getByRole('dialog', { name: 'Выбор режима', exact: true });
      await dialog.getByRole('button', { name: /^Студия / }).click();
      await expect(dialog.getByRole('alert')).toContainText('Не удалось подтвердить выбор режима');
      await expect(f.page.getByRole('button', { name: 'Режим ответа: Экспресс', exact: true, includeHidden: true })).toHaveCount(1);
      f.state.modeFailure = false; await dialog.getByRole('button', { name: /^Студия / }).click();
      await expect(dialog).toBeHidden();
      await expect(f.page.getByRole('button', { name: 'Режим ответа: Студия', exact: true })).toBeVisible();
      await expect(f.input).toHaveValue('Черновик переживёт ошибку');
    } finally { await f.context.close(); }
  });
  await test('modes: pending preferences prevent sending in an unconfirmed mode', async () => {
    const f = await fixture({ modeDelay: 1200 });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Подождать подтверждения');
      await f.page.getByRole('button', { name: /^Режим ответа:/ }).click();
      await f.page.getByRole('dialog', { name: 'Выбор режима', exact: true }).getByRole('button', { name: /^Студия / }).click();
      await expect(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true, includeHidden: true })).toBeDisabled();
      assert.equal(f.state.sends.length, 0);
      await expect(f.page.getByRole('button', { name: 'Режим ответа: Студия', exact: true })).toBeEnabled();
      await f.input.press('Enter'); await expect.poll(() => f.state.sends.length).toBe(1);
      assert.equal(f.state.sends[0].model, 'studio');
    } finally { await f.context.close(); }
  });
  await test('modes: upload locks settings and preserves the mode seen before another tab changed it', async () => {
    const f = await fixture({ uploadDelay: 1200 });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Разбери файл');
      await f.page.locator('input[type="file"]').setInputFiles({ name: 'mode.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic file') });
      await f.input.press('Enter');
      await expect.poll(() => f.state.uploads.length).toBe(1);
      await expect(f.page.getByRole('button', { name: /^Режим ответа:/ })).toBeDisabled();
      f.state.selectedModel = 'studio';
      await expect.poll(() => f.state.sends.length).toBe(1);
      assert.equal(f.state.sends[0].model, 'auto');
    } finally { await f.context.close(); }
  });
  await test('modes: locked search has an explanation and cannot be selected', async () => {
    const f = await fixture({ searchLocked: true });
    try {
      await expect(f.input).toBeEnabled(); await f.page.getByRole('button', { name: /^Режим ответа:/ }).click();
      const dialog = f.page.getByRole('dialog', { name: 'Выбор режима', exact: true });
      await dialog.getByRole('button', { name: /^Ещё/ }).click();
      await expect(dialog.getByRole('button', { name: /^Поиск / })).toBeDisabled();
      assert.deepEqual(f.state.modeSelections || [], []);
      await f.page.screenshot({ path: `${output}/modes-access.png`, fullPage: true });
    } finally { await f.context.close(); }
  });
  await test('modes: quality error preserves the last confirmed setting and recovers', async () => {
    const f = await fixture({ preferenceFailure: true });
    try {
      await expect(f.input).toBeEnabled(); await f.page.getByRole('button', { name: /^Режим ответа:/ }).click();
      const dialog = f.page.getByRole('dialog', { name: 'Выбор режима', exact: true });
      await dialog.getByRole('radio', { name: 'Быстро', exact: true }).click();
      await expect(dialog.getByRole('alert')).toContainText('Не удалось подтвердить качество картинок');
      await expect(dialog.getByRole('radio', { name: 'Высокое', exact: true })).toHaveAttribute('aria-checked', 'true');
      f.state.preferenceFailure = false; await dialog.getByRole('radio', { name: 'Быстро', exact: true }).click();
      await expect(dialog.getByRole('radio', { name: 'Быстро', exact: true })).toHaveAttribute('aria-checked', 'true');
    } finally { await f.context.close(); }
  });
  await test('modes: reasoning failure is visible and does not change the switch', async () => {
    const f = await fixture({ preferenceFailure: true });
    try {
      await expect(f.input).toBeEnabled(); const toggle = f.page.getByRole('switch', { name: 'Глубокие размышления', exact: true });
      await expect(toggle).toHaveAttribute('aria-checked', 'true'); await toggle.click();
      await expect(f.page.getByRole('alert').filter({ hasText: 'Не удалось подтвердить настройку размышлений' })).toBeVisible();
      await expect(toggle).toHaveAttribute('aria-checked', 'true');
      f.state.preferenceFailure = false; await toggle.click();
      await expect(toggle).toHaveAttribute('aria-checked', 'false');
    } finally { await f.context.close(); }
  });
  await test('modes: accepting a suggested mode handles errors and reflects later mode changes', async () => {
    const f = await fixture({ modeFailure: true, handleRoute: async ({ path, route }) => {
      if (path === '/conversations/chat-a/history') {
        await route.fulfill({ json: { items: [{ id: 'chat-a_0', role: 'assistant', content: 'Для этого подойдёт Студия.', search: [{ query: '__mode_switch__', summary: JSON.stringify({ model: 'studio', label: 'Студия', reason: 'Для визуального результата', accept: 'Перейти в Студию', done: 'Студия выбрана' }) }] }], has_more: false, before: null, has_newer: false } }); return true;
      } return false;
    } });
    try {
      const accept = f.page.getByRole('button', { name: 'Перейти в Студию', exact: true });
      await accept.click(); await expect(f.page.getByRole('alert').filter({ hasText: 'Не удалось подтвердить переключение режима.' })).toBeVisible();
      f.state.modeFailure = false; await accept.click();
      await expect(f.page.getByRole('button', { name: 'Студия выбрана', exact: true })).toBeDisabled();
      await f.page.getByRole('button', { name: /^Режим ответа:/ }).click();
      await f.page.getByRole('dialog', { name: 'Выбор режима', exact: true }).getByRole('button', { name: /^Экспресс / }).click();
      await expect(accept).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('modes: image edit can be cancelled without losing an attached document', async () => {
    const f = await fixture({ imageHistory: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Изменить', exact: true }).click();
      await f.input.fill('Проанализируй документ');
      await f.page.locator('input[type="file"]').setInputFiles({ name: 'proposal.pdf', mimeType: 'application/pdf', buffer: Buffer.from('Synthetic PDF') });
      await expect(f.page.getByRole('alert')).toContainText('подходят только изображения');
      await expect(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true, includeHidden: true })).toBeDisabled();
      await f.page.getByRole('button', { name: 'Вернуться к чату', exact: true }).click();
      await expect(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true, includeHidden: true })).toBeEnabled();
      await expect(f.page.getByText('proposal.pdf', { exact: true })).toBeVisible();
      await expect(f.input).toHaveValue('Проанализируй документ');
    } finally { await f.context.close(); }
  });

  await test('experience: files and draft survive refresh on this device', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Мой сохранённый черновик');
      await f.page.locator('input[type="file"]').setInputFiles({ name: 'local-draft.txt', mimeType: 'text/plain', buffer: Buffer.from('Private local attachment') });
      await expect(f.page.getByText('local-draft.txt', { exact: true })).toBeVisible();
      await expect.poll(() => f.page.evaluate(async () => {
        const db = await new Promise((resolve, reject) => { const request = indexedDB.open('bitthink-drafts', 1); request.onsuccess = () => resolve(request.result); request.onerror = reject; });
        return await new Promise(resolve => { const request = db.transaction('drafts').objectStore('drafts').get('audit-user:chat-a'); request.onsuccess = () => resolve(request.result?.files?.length || 0); });
      })).toBe(1);
      await f.page.reload();
      await expect(f.input).toHaveValue('Мой сохранённый черновик');
      await expect(f.page.getByText('local-draft.txt', { exact: true })).toBeVisible();
      assert.equal(f.state.uploads.length, 0);
    } finally { await f.context.close(); }
  });
  await test('experience: delivery recovers a lost receipt without duplicate execution', async () => {
    const f = await fixture({ dropFirstReceipt: true });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Проверка подтверждения'); await f.input.press('Enter');
      await expect(f.page.getByText('Ответ сохранён до переподключения.', { exact: true })).toBeVisible();
      await expect(f.input).toHaveValue('');
      assert.equal(f.state.sends.length, 1);
      assert(f.state.deliveryAttempts.length >= 2);
      assert.equal(new Set(f.state.deliveryAttempts).size, 1);
    } finally { await f.context.close(); }
  });
  for (const width of [320, 1440]) await test(`experience: search opens matching message and drawers fit ${width}`, async () => {
    const f = await fixture({ viewport: { width, height: 900 }, handleRoute: async ({ path, route }) => {
      if (path === '/conversations/search') { await route.fulfill({ json: [{ id: 'chat-b', title: 'Условия договора', snippet: 'Предоплата тридцать процентов.', message_id: 123 }] }); return true; }
      return false;
    } });
    try {
      await expect(f.input).toBeEnabled();
      const menu = f.page.getByRole('button', { name: 'Открыть список бесед', exact: true }); if (await menu.isVisible()) await menu.click();
      await f.page.getByRole('textbox', { name: 'Найти беседу', exact: true }).fill('Предоплата');
      await f.page.getByRole('button', { name: 'Искать в переписке и файлах', exact: true }).click();
      await expect(f.page.getByText('Предоплата тридцать процентов.', { exact: true })).toBeVisible();
      assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await expect.poll(() => f.page.getByRole('heading', { name: 'Мои беседы и задачи' }).evaluate(element => { const r = element.closest('.MuiDrawer-paper').getBoundingClientRect(); return r.x >= -1 && r.right <= innerWidth + 1; })).toBe(true);
      await f.page.screenshot({ path: `${output}/experience-search-${width}.png`, fullPage: true });
      await f.page.getByRole('button', { name: /Условия договора Предоплата/ }).click();
      await expect(f.page).toHaveURL(/c=chat-b&m=123/);
    } finally { await f.context.close(); }
  });
  await test('experience: trash restores a conversation and task controls reach the right job', async () => {
    const f = await fixture({ handleRoute: async ({ path, method, route, state }) => {
      if (path === '/conversations/trash') { await route.fulfill({ json: state.restored ? [] : [{ id: 'deleted', title: 'Удалённая беседа' }] }); return true; }
      if (path === '/conversations/deleted/restore') { state.restored = true; await route.fulfill({ json: { ok: true } }); return true; }
      if (path === '/chat/activity') { await route.fulfill({ json: [{ id: 'job-1', conversation_id: 'chat-a', prompt: 'Долгая проверка', status: 'running', progress: 'Проверяю источники', kind: 'chat' }] }); return true; }
      if (path === '/chat/activity/job-1/stop' && method === 'POST') { state.stopped = true; await route.fulfill({ json: { ok: true } }); return true; }
      return false;
    } });
    try {
      await expect(f.input).toBeEnabled(); await f.page.getByRole('button', { name: 'Корзина', exact: true }).click();
      await expect(f.page.getByText('Удалённая беседа', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Восстановить', exact: true }).click(); await expect(f.page.getByText('Корзина пуста.', { exact: true })).toBeVisible();
      await f.page.getByRole('tab', { name: 'Задачи', exact: true }).click();
      await expect(f.page.getByText('Долгая проверка', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Остановить', exact: true }).click(); await expect.poll(() => f.state.stopped).toBe(true);
      await f.page.screenshot({ path: `${output}/experience-tasks.png`, fullPage: true });
    } finally { await f.context.close(); }
  });
  await test('experience: older history loads without losing the current conversation', async () => {
    const f = await fixture({ handleRoute: async ({ path, route, state }) => {
      if (path === '/conversations/chat-a/history') {
        (state.historyRequests ||= []).push(route.request().url());
        const before = new URL(route.request().url()).searchParams.has('before');
        await route.fulfill({ json: { items: before ? [{ id: 'chat-a_0', role: 'user', content: 'Самое раннее сообщение' }] : [{ id: 'chat-a_80', role: 'assistant', content: 'Последняя часть переписки' }], has_more: !before, before: before ? 1 : 81, has_newer: false } }); return true;
      } return false;
    } });
    try {
      await expect(f.page.getByText('Последняя часть переписки', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Предыдущие сообщения', exact: true }).click();
      await expect(f.page.locator('#main').getByText('Самое раннее сообщение', { exact: true })).toBeVisible();
      await expect(f.page.getByText('Последняя часть переписки', { exact: true })).toBeVisible();
      await expect(f.page).toHaveURL(/c=chat-a/);
    } finally { await writeFile(`${output}/history-debug.txt`, JSON.stringify({ requests: f.state.historyRequests, text: await f.page.locator('body').innerText() })); await f.page.screenshot({ path: `${output}/history-debug.png` }); await f.context.close(); }
  });
  await test('experience: a guided scenario prepares a draft without sending it', async () => {
    const f = await fixture({ handleRoute: async ({ path, route, history }) => {
      if (path.endsWith('/history')) { await route.fulfill({ json: { items: [], has_more: false, before: null, has_newer: false } }); return true; } return false;
    } });
    try {
      await expect(f.input).toBeEnabled(); await f.page.getByRole('button', { name: 'Разобрать документ', exact: true }).click();
      await expect(f.input).toHaveValue(/Разбери прикреплённый документ/);
      assert.equal(f.state.sends.length, 0);
    } finally { await f.context.close(); }
  });
  await test('switching: restoring an existing conversation never mounts the welcome screen', async () => {
    const f = await fixture({ observeWelcome: true, listDelay: 250, historyDelay: { 'chat-a': 250 } });
    try {
      await expect(f.page.getByText('Ответ первой беседы. Здесь удобно читать и продолжать работу.', { exact: true })).toBeVisible();
      assert.deepEqual(await f.page.evaluate(() => window.auditWelcomeMounts), [], 'restoring history must not render the new-chat welcome screen');
    } finally { await f.context.close(); }
  });
  for (const width of [1440, 390]) await test('switching: cold and cached conversations never mount the welcome screen ' + width, async () => {
    const f = await fixture({ observeWelcome: true, viewport: { width, height: 844 }, touch: width < 900, historyDelay: { 'chat-b': 450 } });
    try {
      await expect(f.page.getByText('Ответ первой беседы. Здесь удобно читать и продолжать работу.', { exact: true })).toBeVisible();
      await f.page.evaluate(() => { window.auditWelcomeMounts = []; });
      await f.select('Вторая беседа');
      await expect(f.page.getByText('Ответ второй беседы.', { exact: true })).toBeVisible();
      await f.select('Первая беседа');
      await expect(f.page.getByText('Ответ первой беседы. Здесь удобно читать и продолжать работу.', { exact: true })).toBeVisible();
      await f.select('Вторая беседа');
      await expect(f.page.getByText('Ответ второй беседы.', { exact: true })).toBeVisible();
      assert.deepEqual(await f.page.evaluate(() => window.auditWelcomeMounts), [], 'neither a slow history nor a cached history may show welcome content');
    } finally { await f.context.close(); }
  });
  await test('switching: a genuinely new conversation still shows the welcome screen', async () => {
    const f = await fixture();
    try {
      await expect(f.page.getByText('Ответ первой беседы. Здесь удобно читать и продолжать работу.', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).click();
      await expect(f.page.getByText('С чего начнём?', { exact: true })).toBeVisible();
      await expect(f.input).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('sidebar: desktop drag moves a chat into the project', async () => {
    const f = await sidebarFixture();
    try {
      const source = f.sidebar.getByRole('button', { name: 'Открыть беседу Первая беседа', exact: true });
      const target = f.sidebar.getByRole('button', { name: /^Презентация продукта/ });
      await source.dragTo(target);
      await expect.poll(() => f.state.moves?.length).toBe(1);
      assert.deepEqual(f.state.moves[0], { id: 'chat-a', pid: 'demo' });
      await expect(f.sidebar.getByRole('button', { name: 'Открыть беседу Первая беседа', exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('sidebar: search includes project chats and restores the grouped list', async () => {
    const f = await sidebarFixture();
    try {
      const search = f.sidebar.getByRole('textbox', { name: 'Найти беседу', exact: true });
      await search.fill('Вторая');
      await expect(f.sidebar.getByRole('button', { name: 'Открыть беседу Вторая беседа', exact: true })).toBeVisible();
      await expect(f.sidebar.getByText('Презентация продукта', { exact: true })).toBeVisible();
      await expect(f.sidebar.getByRole('heading', { name: 'Проекты', exact: true })).toHaveCount(0);
      await search.fill('Нет такой беседы');
      await expect(f.sidebar.getByText('Беседа не найдена', { exact: true })).toBeVisible();
      await f.sidebar.getByRole('button', { name: 'Очистить поиск', exact: true }).click();
      await expect(f.sidebar.getByRole('heading', { name: 'Проекты', exact: true })).toBeVisible();
      await expect(f.sidebar.getByRole('button', { name: 'Открыть беседу Первая беседа', exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  for (const width of [1440, 320]) await test('sidebar: consistent actions, inline editing and move navigation ' + width, async () => {
    const f = await sidebarFixture({ viewport: { width, height: 900 }, touch: width < 900 });
    try {
      const actions = f.sidebar.getByRole('button', { name: 'Действия с беседой Первая беседа', exact: true });
      await actions.focus(); await actions.press('Enter');
      await f.page.getByRole('menuitem', { name: 'Переименовать', exact: true }).click();
      const name = f.sidebar.getByRole('textbox', { name: 'Название беседы', exact: true });
      await expect(name).toBeFocused();
      await name.fill('Несохранённое название'); await name.press('Escape');
      await expect(actions).toBeAttached();
      await actions.focus(); await actions.press('Enter');
      await f.page.getByRole('menuitem', { name: 'Переименовать', exact: true }).click();
      await name.fill('План презентации'); await name.press('Enter');
      await expect(f.sidebar.getByRole('button', { name: 'Открыть беседу План презентации', exact: true })).toBeVisible();
      assert.deepEqual(f.state.renames, ['План презентации']);
      const renamedActions = f.sidebar.getByRole('button', { name: 'Действия с беседой План презентации', exact: true });
      await renamedActions.focus(); await renamedActions.press('Enter');
      await f.page.getByRole('menuitem', { name: 'Переместить в проект…', exact: true }).click();
      await expect(f.page.getByRole('menuitem', { name: 'Переименовать', exact: true })).toHaveCount(0);
      await f.page.getByRole('menuitem', { name: 'Назад', exact: true }).click();
      await f.page.getByRole('menuitem', { name: 'Переместить в проект…', exact: true }).click();
      await f.page.getByRole('menuitem', { name: 'Презентация продукта', exact: true }).click();
      await expect.poll(() => f.state.moves?.length).toBe(1);
      const nested = f.sidebar.getByRole('button', { name: 'Открыть беседу План презентации', exact: true });
      await expect(nested).toBeVisible();
      const nestedActions = f.sidebar.getByRole('button', { name: 'Действия с беседой План презентации', exact: true });
      if (width < 900) {
        const bounds = await nestedActions.boundingBox(); assert(bounds.width >= 44 && bounds.height >= 44);
        assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      }
      await nestedActions.focus(); await nestedActions.press('Enter');
      await f.page.getByRole('menuitem', { name: 'Удалить', exact: true }).click();
      await f.page.getByRole('button', { name: 'Отмена', exact: true }).click();
      await expect(nested).toBeVisible();
      assert.equal(await f.sidebar.getByRole('button', { name: 'Действия с беседой Общий чат команды', exact: true }).count(), 0);
    } finally { await f.context.close(); }
  });
  await test('architecture: a burst of frames is consumed in order without a saved-answer fallback', async () => {
    const f = await fixture({ streamBurst: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Проверка потока'); await f.input.press('Enter');
      await expect.poll(() => Boolean(f.state.burstAnswer)).toBe(true);
      await expect(f.page.getByText(f.state.burstAnswer.trim(), { exact: true })).toBeVisible();
      assert.equal(f.state.sends.length, 1);
    } finally { await f.context.close(); }
  });
  await test('architecture: interrupted durable job is visible once after reconnect', async () => {
    const text = 'Выполнение было прервано перезапуском обработчика. Повторите запрос.';
    const f = await fixture({ handleRoute: async ({ path, route }) => {
      if (path !== '/chat/jobs') return false;
      await route.fulfill({ json: { jobs: [{ conversation_id: 'chat-a', thinking: false, error: text, text: '' }] } }); return true;
    } });
    try {
      await expect(f.input).toBeEnabled();
      await expect(f.page.getByText(text, { exact: true })).toHaveCount(1);
      await f.page.reload();
      await expect(f.page.getByText(text, { exact: true })).toHaveCount(1);
      await expect(f.input).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('architecture: diagnostics exclude content, tokens and invitation URLs', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.page.evaluate(async () => {
        const { reportClientError } = await import('/src/api/diagnostics.ts');
        history.replaceState({}, '', '/join/PRIVATE_INVITE?token=PRIVATE_TOKEN');
        const error = new Error('PRIVATE_MESSAGE');
        error.stack = 'Error: PRIVATE_MESSAGE\n at f (https://bit-think.space/assets/ChatPage-fixture.js:2:3)';
        reportClientError(error, 'render');
        reportClientError(error, 'render');
      });
      await expect.poll(() => f.state.diagnostics?.length).toBe(1);
      const report = f.state.diagnostics[0];
      assert.equal(report.route, '/join/:token');
      assert.equal(report.frames[0].file, 'ChatPage-fixture.js');
      assert(!JSON.stringify(report).includes('PRIVATE_'));
      assert.deepEqual(Object.keys(report).sort(), ['build', 'category', 'frames', 'report_id', 'route']);
    } finally { await f.context.close(); }
  });
  await test('navigation: deep links keep the selected conversation in the address', async () => {
    const f = await fixture({ startPath: '/chat?c=chat-b', observeWelcome: true });
    try {
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
      assert.equal(new URL(f.page.url()).searchParams.get('c'), 'chat-b');
      assert.deepEqual(await f.page.evaluate(() => window.auditWelcomeMounts), []);
    } finally { await f.context.close(); }
  });
  await test('navigation: conversation opens before its slow selection is saved', async () => {
    const f = await fixture({ delay: { 'chat-b': 1600 } });
    try {
      await expect(f.input).toBeEnabled();
      await f.select('Вторая беседа');
      await baseExpect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible({ timeout: 800 });
      assert.equal(new URL(f.page.url()).searchParams.get('c'), 'chat-b');
      await expect.poll(() => f.state.activeId).toBe('chat-b');
    } finally { await f.context.close(); }
  });
  await test('navigation: Back and Forward restore conversation and draft', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик первой беседы');
      await f.select('Вторая беседа');
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
      await f.input.fill('Черновик второй беседы');
      await f.page.goBack();
      await expect(f.page.getByText('Вопрос первой беседы', { exact: true }).first()).toBeVisible();
      await expect(f.input).toHaveValue('Черновик первой беседы');
      await f.page.goForward();
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
      await expect(f.input).toHaveValue('Черновик второй беседы');
      assert.equal(f.state.socketAuths, 1);
    } finally { await f.context.close(); }
  });
  await test('navigation: rapid selections persist in the same order as the screen', async () => {
    const f = await fixture({ delay: { 'chat-b': 900 } });
    try {
      await expect(f.input).toBeEnabled();
      await f.select('Вторая беседа');
      await f.select('Первая беседа');
      await expect(f.page.getByText('Вопрос первой беседы', { exact: true }).first()).toBeVisible();
      await expect.poll(() => f.state.activations?.slice(-2)).toEqual(['chat-b', 'chat-a']);
      assert.equal(f.state.activeId, 'chat-a');
      assert.equal(new URL(f.page.url()).searchParams.get('c'), 'chat-a');
    } finally { await f.context.close(); }
  });
  for (const width of [1440, 390]) await test('navigation: chat settings and billing preserve the last selection before it is saved ' + width, async () => {
    const f = await fixture({ delay: { 'chat-b': 3000 }, viewport: { width, height: 844 }, touch: width < 900 });
    try {
      await expect(f.input).toBeEnabled();
      await f.select('Вторая беседа');
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
      await f.input.fill('Черновик во второй беседе');
      for (const [menu, heading] of [['Настройки', 'Настройки'], ['Кабинет', 'Кабинет']]) {
        await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
        await f.page.getByRole('menuitem', { name: menu, exact: true }).click();
        await expect(f.page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
        assert.equal(await f.page.evaluate(() => window.scrollY), 0);
        if (width < 900) await f.page.getByRole('button', { name: 'Меню', exact: true }).click();
        await f.page.getByRole('link', { name: 'Чат', exact: true }).click();
        await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
        await expect(f.input).toHaveValue('Черновик во второй беседе');
        assert.equal(new URL(f.page.url()).searchParams.get('c'), 'chat-b');
      }
      assert.equal(f.state.socketAuths, 1);
    } finally { await f.context.close(); }
  });
  await test('navigation: failed conversation list offers retry instead of a new-chat screen', async () => {
    const f = await fixture({ listFailure: true, handleRoute: async ({ path, route, state }) => {
      if (path === '/conversations' && state.listFailure) { await route.fulfill({ status: 503, json: { detail: 'Temporary outage' } }); return true; }
    } });
    try {
      await expect(f.page.getByRole('alert')).toContainText('Не удалось загрузить список бесед');
      f.state.listFailure = false;
      await f.page.getByRole('button', { name: 'Повторить загрузку', exact: true }).click();
      await expect(f.page.getByText('Вопрос первой беседы', { exact: true }).first()).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('navigation: runtime error does not blame the connection and allows returning to chat', async () => {
    const f = await fixture({ runtimeSettingsError: true, startPath: '/settings' });
    try {
      await expect(f.page.getByRole('alert')).toContainText('В этом разделе произошла ошибка');
      await expect(f.page.getByRole('alert')).not.toContainText('соединение');
      await expect(f.page.getByRole('button', { name: 'Открыть заново', exact: true })).toBeVisible();
      await f.page.getByRole('link', { name: 'Вернуться в чат', exact: true }).click();
      await expect(f.input).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('navigation: a transient chat download recovers with one bounded refresh', async () => {
    const f = await fixture({ failChatChunkOnce: true });
    try {
      await expect(f.input).toBeEnabled();
      await expect(f.page.getByText('Вопрос первой беседы', { exact: true }).first()).toBeVisible();
      assert(await f.page.evaluate(() => Boolean(sessionStorage.getItem('bit-think-route-refresh'))));
    } finally { await f.context.close(); }
  });
  await test('navigation: persistent chat download failure never loops document refreshes', async () => {
    const f = await fixture({ failChatChunkPersistent: true });
    try {
      await expect.poll(() => f.state.chatDownloadAttempts).toBe(2);
      await expect(f.page.getByRole('alert')).toContainText('Не удалось загрузить раздел');
      await expect(f.page.getByRole('button', { name: 'Повторить загрузку', exact: true })).toBeVisible();
      // Long enough for another automatic document navigation to be observed.
      await f.page.waitForTimeout(500);
      assert.equal(f.state.chatDownloadAttempts, 2);
    } finally { await f.context.close(); }
  });
  await test('navigation: a section failure preserves unsent attachments and the live connection', async () => {
    const f = await fixture({ failSettingsChunk: true, allowAutoRecovery: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик с файлом');
      await f.page.locator('input[type=file][multiple]').setInputFiles({ name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('draft') });
      await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
      await f.page.getByRole('menuitem', { name: 'Настройки', exact: true }).click();
      await expect(f.page.getByRole('alert')).toContainText('Не удалось загрузить раздел');
      await f.page.getByRole('link', { name: 'Вернуться в чат', exact: true }).click();
      await expect(f.input).toHaveValue('Черновик с файлом');
      await expect(f.page.getByRole('button', { name: 'Убрать draft.txt', exact: true })).toBeVisible();
      assert.equal(f.state.socketAuths, 1);
    } finally { await f.context.close(); }
  });
  for (const width of [1440, 320]) await test('navigation: error recovery controls fit and retry runtime failures ' + width, async () => {
    const f = await fixture({ runtimeSettingsError: true, startPath: '/settings', viewport: { width, height: 720 }, theme: width === 320 ? 'light' : 'dark' });
    try {
      await expect(f.page.getByRole('alert')).toContainText('В этом разделе произошла ошибка');
      const retry = f.page.getByRole('button', { name: 'Открыть заново', exact: true });
      await reachable(retry, f.page, 'Retry after runtime failure');
      await reachable(f.page.getByRole('link', { name: 'Вернуться в чат', exact: true }), f.page, 'Return from runtime failure');
      assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await f.page.screenshot({ path: `${output}/route-error-${width}.png`, animations: 'disabled' });
      await f.page.evaluate(() => { window.auditRuntimeRecovered = true; });
      await retry.click();
      await expect(f.page.getByText('Раздел восстановлен', { exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('connection: answer completed in settings is restored once on return', async () => {
    const f = await fixture({ holdAnswer: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Продолжить ответ в фоне'); await f.input.press('Enter');
      await expect.poll(() => Boolean(f.state.finishHeldAnswer)).toBe(true);
      await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
      await f.page.getByRole('menuitem', { name: 'Настройки', exact: true }).click();
      await expect(f.page.getByRole('heading', { name: 'Настройки', exact: true })).toBeVisible();
      f.state.finishHeldAnswer();
      await f.page.getByRole('link', { name: 'Чат', exact: true }).click();
      await expect(f.page.getByText('Ответ завершён в другом разделе.', { exact: true })).toHaveCount(1);
      await expect(f.input).toBeEnabled();
      assert.equal(f.state.socketAuths, 1);
    } finally { await f.context.close(); }
  });
  await test('connection: failed section download offers recovery without losing chat access', async () => {
    const f = await fixture({ failSettingsChunk: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик после сетевого сбоя');
      await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
      await f.page.getByRole('menuitem', { name: 'Настройки', exact: true }).click();
      await expect(f.page.getByRole('alert')).toContainText('Не удалось загрузить раздел');
      await expect(f.page.getByRole('button', { name: 'Повторить загрузку', exact: true })).toBeVisible();
      await f.page.getByRole('link', { name: 'Вернуться в чат', exact: true }).click();
      await expect(f.input).toHaveValue('Черновик после сетевого сбоя');
      assert.equal(f.state.socketAuths, 1);
    } finally { await f.context.close(); }
  });
  await test('connection: section navigation preserves socket and composer draft', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await expect.poll(() => f.state.socketAuths).toBe(1);
      const connections = f.state.socketConnections;
      const closes = f.state.socketCloses || 0;
      await f.input.fill('Вернуться к этому черновику');
      for (const [menu, heading] of [['Настройки', 'Настройки'], ['Кабинет', 'Кабинет']]) {
        await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
        await f.page.getByRole('menuitem', { name: menu, exact: true }).click();
        await expect(f.page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
        assert.equal(f.state.socketConnections, connections, 'navigation must reuse the authenticated connection');
        await f.page.getByRole('link', { name: 'Чат', exact: true }).click();
        await expect(f.input).toHaveValue('Вернуться к этому черновику');
        assert.equal(f.state.socketConnections, connections);
        assert.equal(f.state.socketCloses || 0, closes);
      }
    } finally { await f.context.close(); }
  });
  await test('connection: silent socket recovers without waiting for TCP close', async () => {
    const f = await fixture({ clock: true, silentFirstSocket: true });
    try {
      await expect(f.input).toBeEnabled();
      await expect.poll(() => f.state.socketAuths).toBe(1);
      await f.page.clock.runFor(26000);
      await expect.poll(() => f.state.socketAuths).toBe(2);
      await f.input.fill('Сообщение после восстановления');
      await f.input.press('Enter');
      await expect.poll(() => f.state.sends.length).toBe(1);
      assert.equal(f.state.sends[0].content, 'Сообщение после восстановления');
    } finally { await f.context.close(); }
  });
  await test('connection: returning to chat does not replay consumed reply chunks', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await expect.poll(() => f.state.socketAuths).toBe(1);
      const connections = f.state.socketConnections;
      await f.input.fill('Первое сообщение'); await f.input.press('Enter');
      await expect(f.page.getByText('Проверенный новый ответ.', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Аккаунт', exact: true }).last().click();
      await f.page.getByRole('menuitem', { name: 'Настройки', exact: true }).click();
      await expect(f.page.getByRole('heading', { name: 'Настройки', exact: true })).toBeVisible();
      await f.page.getByRole('link', { name: 'Чат', exact: true }).click();
      await expect(f.page.getByText('Проверенный новый ответ.', { exact: true })).toHaveCount(1);
      assert.equal(f.state.sends.length, 1);
      assert.equal(f.state.socketConnections, connections);
    } finally { await f.context.close(); }
  });
  await test('journey: answer mode sheet stays above a simulated keyboard and can be closed', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 844 }, touch: true });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Сохранить запрос при выборе режима');
      await f.page.evaluate(() => {
        Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => 360 });
        window.visualViewport.dispatchEvent(new Event('resize'));
      });
      await f.page.getByRole('button', { name: 'Режим ответа: Оркестратор', exact: true }).click();
      const heading = f.page.getByText('Как отвечать', { exact: true });
      await expect.poll(async () => { const b = await heading.boundingBox(); return b.y + b.height; }).toBeLessThanOrEqual(360);
      await f.page.getByRole('button', { name: 'Закрыть выбор режима', exact: true }).click();
      await expect(heading).toBeHidden();
      await expect(f.input).toHaveValue('Сохранить запрос при выборе режима');
    } finally { await f.context.close(); }
  });
  await test('journey: orchestrator skill import failure remains visible and Escape returns focus', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 844 }, touch: true, handleRoute: async ({ path, route }) => {
      if (path === '/skills') { await route.fulfill({ json: { items: [] } }); return true; }
      if (path === '/skills/import') { await route.fulfill({ status: 400, json: { detail: 'В архиве нет SKILL.md' } }); return true; }
    } });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true }).click();
      const panel = f.page.getByRole('region', { name: 'Инструменты Оркестратора', exact: true });
      await panel.getByRole('button', { name: /^Навыки/ }).click();
      await panel.locator('input[type=file]').setInputFiles({ name: 'skill.zip', mimeType: 'application/zip', buffer: Buffer.from('invalid') });
      await expect(panel.getByRole('alert')).toContainText('В архиве нет SKILL.md');
      await panel.getByRole('button', { name: 'Закрыть инструменты', exact: true }).focus();
      await f.page.keyboard.press('Escape');
      await expect(panel).toBeHidden();
      await expect(f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true })).toBeFocused();
    } finally { await f.context.close(); }
  });
  await test('journey: clarification shortcuts do not steal Enter from navigation buttons', async () => {
    const f = await fixture({ clarify: true, handleRoute: async ({ path, route }) => {
      if (path === '/conversations/chat-a/files') { await route.fulfill({ json: [] }); return true; }
    } });
    try {
      await expect(f.page.getByText('Какой формат результата нужен?', { exact: true }).first()).toBeVisible();
      const files = f.page.getByRole('button', { name: 'Файлы беседы', exact: true });
      await files.focus(); await files.press('Enter');
      await expect(f.page.getByRole('button', { name: 'Закрыть список файлов', exact: true })).toBeVisible();
      assert.deepEqual(f.state.sends, [], 'Opening files must not skip and submit clarification');
      await f.page.getByRole('button', { name: 'Закрыть список файлов', exact: true }).click();
      await expect(f.page.getByText('Какой формат результата нужен?', { exact: true }).first()).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('journey: visual viewport shrink keeps the composer above a simulated keyboard', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 844 }, touch: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Текст при открытой клавиатуре. '.repeat(30));
      await f.page.evaluate(() => {
        Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => 360 });
        window.visualViewport.dispatchEvent(new Event('resize'));
      });
      await expect.poll(async () => (await f.input.boundingBox())?.y).toBeGreaterThanOrEqual(54);
      await f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true }).click();
      const send = f.page.getByRole('button', { name: 'Отправить сообщение', exact: true });
      await expect.poll(async () => { const b = await send.boundingBox(); return b.y + b.height; }).toBeLessThanOrEqual(360);
      const input = await f.input.boundingBox(); assert(input.y >= 54 && input.y + input.height <= 360);
      await f.page.getByRole('button', { name: 'Закрыть инструменты', exact: true }).click();
      await expect(f.input).toHaveValue('Текст при открытой клавиатуре. '.repeat(30));
    } finally { await f.context.close(); }
  });
  await test('journey: quota notice, attachments and tools remain dismissible on a short phone', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 360 }, touch: true, handleRoute: async ({ path, route }) => {
      if (path !== '/billing/subscription') return false;
      await route.fulfill({ json: { tier: 'pro', shared_budget: true, windows: { shared: { session: { ratio: .95, limit: 1000, resets_at: Math.floor(Date.now() / 1000) + 3600 } } } } }); return true;
    } });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Запрос с вложениями. '.repeat(25));
      await f.page.locator('input[type=file][multiple]').setInputFiles([{ name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('brief') }, { name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('notes') }]);
      await f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true }).click();
      await reachable(f.input, f.page, 'Input with quota and files');
      await reachable(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }), f.page, 'Send with quota and files');
      await reachable(f.page.getByRole('button', { name: 'Закрыть инструменты', exact: true }), f.page, 'Close tools with files');
      await f.page.getByRole('button', { name: 'Закрыть инструменты', exact: true }).click();
      await f.page.getByRole('button', { name: 'Убрать brief.txt', exact: true }).click();
      await f.page.getByRole('button', { name: 'Убрать notes.txt', exact: true }).click();
      await reachable(f.page.getByRole('button', { name: 'Скрыть уведомление', exact: true }), f.page, 'Dismiss quota');
      await f.page.getByRole('button', { name: 'Скрыть уведомление', exact: true }).click();
      await expect(f.page.getByText(/Потрачено 95%/)).toBeHidden();
    } finally { await f.context.close(); }
  });
  await test('journey: share outage and denied clipboard have recovery and do not trap the user', async () => {
    const f = await fixture({ viewport: { width: 390, height: 844 }, touch: true, shareFail: true, handleRoute: async ({ path, route, state }) => {
      if (path !== '/conversations/chat-a/share') return false;
      if (state.shareFail) await route.fulfill({ status: 503, json: { detail: 'Temporary outage' } });
      else await route.fulfill({ json: { shared: true, token: 'demo-invite', role: 'owner', people: [] } });
      return true;
    } });
    try {
      await expect(f.input).toBeEnabled(); await f.input.fill('Сохранить мой черновик');
      await f.page.getByRole('button', { name: 'Ещё действия', exact: true }).tap();
      await f.page.getByRole('menuitem', { name: 'Поделиться диалогом', exact: true }).tap();
      const dialog = f.page.getByRole('dialog');
      await expect(dialog.getByRole('alert')).toContainText('Не удалось загрузить доступ');
      await expect(dialog.getByRole('button', { name: 'Создать ссылку', exact: true })).toBeHidden();
      f.state.shareFail = false;
      await dialog.getByRole('button', { name: 'Повторить', exact: true }).tap();
      await f.page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new DOMException('Denied', 'NotAllowedError'); } } }); });
      await dialog.getByRole('button', { name: 'Скопировать ссылку', exact: true }).tap();
      await expect(dialog.getByRole('alert')).toContainText('Не удалось скопировать');
      await expect(dialog.getByRole('textbox', { name: 'Ссылка на диалог', exact: true })).toHaveValue(base + '/join/demo-invite');
      await dialog.getByRole('button', { name: 'Закрыть', exact: true }).tap();
      await reachable(f.input, f.page, 'Input after sharing');
      await expect(f.input).toHaveValue('Сохранить мой черновик');
    } finally { await f.context.close(); }
  });
  await test('journey: task settings do not submit the main conversation on Enter', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 844 }, touch: true, handleRoute: async ({ path, method, route, state }) => {
      if (path === '/computer/tasks' && method === 'POST') { state.enrollments = (state.enrollments || 0) + 1; await route.fulfill({ json: { id: 'unexpected', status: 'paused', conversation_id: 'chat-a', enabled: false, prompt: '', progress: '', error: '', run_number: 1 } }); return true; }
    } });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Этот запрос пока не отправлять');
      await f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true }).click();
      const panel = f.page.getByRole('region', { name: 'Инструменты Оркестратора', exact: true });
      await panel.getByRole('button', { name: /^Задачи/ }).click();
      await panel.getByRole('button', { name: 'Новая задача', exact: true }).click();
      await panel.getByLabel('Начать', { exact: true }).fill('2026-11-01T12:00');
      await panel.getByLabel('Начать', { exact: true }).press('Enter');
      await f.page.waitForTimeout(250);
      assert.equal(f.state.enrollments, undefined, 'Changing a task date must not send the chat draft');
      assert.deepEqual(f.state.sends, []);
      await expect(f.input).toHaveValue('Этот запрос пока не отправлять');
    } finally { await f.context.close(); }
  });
  await test('journey: file drawer and mobile action menu release the composer after closing', async () => {
    const f = await fixture({ viewport: { width: 390, height: 844 }, touch: true, handleRoute: async ({ path, route }) => {
      if (path === '/conversations/chat-a/files' || path === '/conversations/library') { await route.fulfill({ json: [] }); return true; }
    } });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик не должен пропасть');
      await f.page.getByRole('button', { name: 'Ещё действия', exact: true }).tap();
      await f.page.getByRole('menuitem', { name: 'Файлы беседы', exact: true }).tap();
      await f.page.getByRole('button', { name: 'Закрыть список файлов', exact: true }).tap();
      await expect(f.page.getByRole('button', { name: 'Закрыть список файлов', exact: true })).toBeHidden();
      await reachable(f.input, f.page, 'Input after file drawer');
      await reachable(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }), f.page, 'Send after file drawer');
      await expect(f.input).toHaveValue('Черновик не должен пропасть');
    } finally { await f.context.close(); }
  });
  await test('journey: context controls remain reachable with a long mobile draft', async () => {
    const f = await projectFixture({ viewport: { width: 320, height: 568 }, touch: true });
    try {
      await f.workspace.getByRole('button', { name: 'Вернуться к беседе', exact: true }).tap();
      await f.input.fill('Подробный запрос. '.repeat(30));
      await f.page.getByRole('button', { name: /^Контекст проекта/ }).tap();
      await f.page.getByRole('checkbox', { name: 'Все материалы проекта', exact: true }).uncheck();
      await reachable(f.input, f.page, 'Input with project settings');
      await reachable(f.page.getByRole('button', { name: 'Сохранить', exact: true }), f.page, 'Save project settings');
      await f.page.getByRole('button', { name: 'Отмена', exact: true }).tap();
      await expect(f.page.getByRole('checkbox', { name: 'Все материалы проекта', exact: true })).toBeHidden();
      await expect(f.input).toHaveValue('Подробный запрос. '.repeat(30));
    } finally { await f.context.close(); }
  });
  for (const viewport of [{ width: 320, height: 568 }, { width: 390, height: 360 }, { width: 1440, height: 900 }]) await test(`journey: tools and long draft leave composer usable ${viewport.width}x${viewport.height}`, async () => {
    const f = await fixture({ model: 'director', viewport, touch: viewport.width < 600 });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Длинный запрос с требованиями к результату. '.repeat(20));
      await f.page.getByRole('button', { name: 'Задачи и инструменты Оркестратора', exact: true }).click();
      await expect(f.page.getByRole('region', { name: 'Инструменты Оркестратора', exact: true })).toBeVisible();
      await f.page.screenshot({ path: `${output}/journey-tools-${viewport.width}x${viewport.height}.png`, animations: 'disabled' });
      await reachable(f.input, f.page, 'Message input');
      await reachable(f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }), f.page, 'Send');
      await reachable(f.page.getByRole('button', { name: 'Закрыть инструменты', exact: true }), f.page, 'Close tools');
      await f.page.getByRole('button', { name: 'Закрыть инструменты', exact: true }).click();
      await expect(f.input).toHaveValue('Длинный запрос с требованиями к результату. '.repeat(20));
    } finally { await f.context.close(); }
  });
  for (const width of [320, 768]) await test(`presentation: project table at narrow and tablet width ${width}`, async () => {
    const f = await projectFixture({ viewport: { width, height: width === 320 ? 568 : 1024 }, touch: true });
    try {
      await f.workspace.getByRole('tab', { name: 'Результаты', exact: true }).tap();
      await f.workspace.getByRole('button', { name: /Сравнение поставщиков/ }).tap();
      await expect(f.workspace.getByRole('region', { name: 'Сравнение поставщиков', exact: true })).toBeVisible();
      assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await f.workspace.getByRole('button', { name: 'Редактировать', exact: true }).tap();
      await f.workspace.getByRole('textbox', { name: 'Цена, строка r1', exact: true }).fill('1800');
      await f.workspace.getByRole('button', { name: 'Сохранить', exact: true }).tap();
      await expect.poll(() => f.state.savedSpec?.rows[0].cells.price).toBe('1800');
      await f.page.screenshot({ path: `${output}/project-${width}-touch.png`, animations: 'disabled' });
    } finally { await f.context.close(); }
  });
  await test('presentation: nested admin routes navigate after router upgrade', async () => {
    const f = await fixture({ admin: true, startPath: '/admin', handleRoute: async ({ path, route }) => {
      if (path === '/admin/users') { await route.fulfill({ json: { total: 0, offset: 0, limit: 25, items: [] } }); return true; }
      if (path === '/admin/stats') { await route.fulfill({ json: { total_users: 12, total_conversations: 34, total_messages: 56 } }); return true; }
    } });
    try {
      await expect(f.page).toHaveURL(/\/admin\/users$/);
      await expect(f.page.getByText('Админ-панель', { exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Статистика', exact: true }).click();
      await expect(f.page).toHaveURL(/\/admin\/stats$/);
      await expect(f.page.getByText('56', { exact: true })).toBeVisible();
      await f.page.goBack();
      await expect(f.page).toHaveURL(/\/admin\/users$/);
    } finally { await f.context.close(); }
  });
  await test('presentation: non-admin cannot render nested admin pages', async () => {
    const f = await fixture({ startPath: '/admin/stats' });
    try { await expect(f.page.getByText('Доступ запрещён', { exact: true })).toBeVisible(); }
    finally { await f.context.close(); }
  });
  await test('presentation: registration preserves protected destination', async () => {
    const f = await fixture({ signedOut: true, startPath: '/register?next=%2Fbilling', handleRoute: async ({ path, route }) => {
      if (path === '/auth/register') { await route.fulfill({ json: { access_token: 'registered-access', refresh_token: 'registered-refresh' } }); return true; }
      if (path === '/billing/plans') { await route.fulfill({ json: { plans: [] } }); return true; }
    } });
    try {
      await f.page.getByRole('textbox', { name: /^Имя/ }).fill('Анна');
      await f.page.getByRole('textbox', { name: /Email/ }).fill('new@example.com');
      await f.page.getByLabel(/^Пароль/).fill('password123');
      await f.page.locator('form').getByRole('button', { name: 'Зарегистрироваться', exact: true }).click();
      await expect(f.page).toHaveURL(/\/billing$/);
      await expect(f.page.getByText('Общий запас', { exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('presentation: settings memory outage blocks overwrite; skill import and prompt deletion failures stay visible', async () => {
    const f = await fixture({ startPath: '/settings', memoryFail: true, skillFail: true, promptFail: true, handleRoute: async ({ path, method, route, state }) => {
      let data;
      if (path === '/memory') {
        if (state.memoryFail) { await route.fulfill({ status: 503, json: { detail: 'Temporary outage' } }); return true; }
        data = { notes: 'Предпочитаю краткие ответы', enabled: true, updated_at: 1 };
      } else if (path === '/skills') data = { items: [], custom_count: 0, custom_limit: 20 };
      else if (path === '/skills/import') {
        state.skillImports = (state.skillImports || 0) + 1;
        if (state.skillFail) { await route.fulfill({ status: 400, json: { detail: 'В архиве нет SKILL.md' } }); return true; }
        data = { ok: true };
      } else if (path === '/models/prompts') data = { prompts: state.promptDeleted ? [] : ['Показывать итог первым'], active: null };
      else if (path === '/models/prompts/0' && method === 'DELETE') {
        if (state.promptFail) { await route.fulfill({ status: 503, json: { detail: 'Не удалось удалить правило' } }); return true; }
        state.promptDeleted = true; data = { ok: true };
      } else return false;
      await route.fulfill({ json: data }); return true;
    } });
    try {
      const memory = f.page.getByRole('region', { name: 'Память аккаунта', exact: true });
      await expect(memory.getByRole('alert')).toContainText('Не удалось загрузить память');
      await expect(memory.getByRole('button', { name: 'Изменить', exact: true })).toBeDisabled();
      await expect(memory.getByRole('switch')).toBeDisabled();
      f.state.memoryFail = false;
      await memory.getByRole('button', { name: 'Повторить', exact: true }).click();
      await expect(memory.getByText('Предпочитаю краткие ответы', { exact: true })).toBeVisible();
      const skills = f.page.getByRole('region', { name: 'Навыки аккаунта', exact: true });
      const upload = skills.locator('input[type=file]');
      const skill = { name: 'SKILL.md', mimeType: 'text/markdown', buffer: Buffer.from('invalid') };
      await upload.setInputFiles(skill);
      await expect(skills.getByRole('alert')).toContainText('В архиве нет SKILL.md');
      f.state.skillFail = false;
      await upload.setInputFiles(skill);
      await expect(skills.getByRole('alert')).toBeHidden();
      assert.equal(f.state.skillImports, 2);
      await f.page.getByRole('button', { name: 'Удалить', exact: true }).click();
      await expect(f.page.getByRole('alert')).toContainText('Не удалось удалить правило');
      await expect(f.page.getByText('Показывать итог первым', { exact: true })).toBeVisible();
      f.state.promptFail = false;
      await f.page.getByRole('button', { name: 'Удалить', exact: true }).click();
      await expect(f.page.getByText('Показывать итог первым', { exact: true })).toBeHidden();
      await expect(f.page.getByRole('alert')).toBeHidden();
    } finally { await f.context.close(); }
  });
  await test('presentation: orchestrator enrollment retry preserves draft and idempotency; pause and resume work on mobile', async () => {
    const f = await fixture({ model: 'director', viewport: { width: 390, height: 844 }, touch: true, enrollmentFail: true, handleRoute: async ({ path, method, route, state }) => {
      if (path === '/computer/tasks') {
        if (method === 'POST') {
          const payload = route.request().postDataJSON();
          (state.taskRequests ||= []).push(payload);
          if (state.enrollmentFail) { await route.fulfill({ status: 503, json: { detail: 'Временно недоступно' } }); return true; }
          state.task = { id: 'task-demo', status: 'queued', enabled: true, conversation_id: payload.conversation_id, prompt: payload.prompt, progress: '', error: '', run_number: 1 };
          await route.fulfill({ json: state.task });
        } else await route.fulfill({ json: state.task ? [state.task] : [] });
        return true;
      }
      if (path === '/computer/tasks/task-demo/pause' || path === '/computer/tasks/task-demo/resume') {
        state.task.status = path.endsWith('/pause') ? 'paused' : 'running';
        await route.fulfill({ json: state.task }); return true;
      }
    } });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Подготовь отчёт из документов проекта');
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).tap();
      await expect(f.input).toHaveValue('Подготовь отчёт из документов проекта');
      await expect(f.page.getByText(/Не удалось отправить сообщение:/).first()).toBeVisible();
      f.state.enrollmentFail = false;
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).tap();
      const task = f.page.getByRole('region', { name: 'Фоновая задача', exact: true });
      await expect(task).toBeVisible();
      assert.equal(f.state.taskRequests[0].idempotency_key, f.state.taskRequests[1].idempotency_key);
      await task.getByRole('button', { name: 'Приостановить', exact: true }).tap();
      await expect(task.getByText('Задача на паузе', { exact: true })).toBeVisible();
      await task.getByRole('button', { name: 'Продолжить задачу', exact: true }).tap();
      await expect(task.getByText('Задача выполняется в фоне', { exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('presentation: image edit failure preserves prompt and retries the original image', async () => {
    const f = await fixture({ imageHistory: true, imageFail: true, handleRoute: async ({ path, route, state, history }) => {
      if (path !== '/media/images/generate') return false;
      const payload = route.request().postDataJSON(); (state.imageRequests ||= []).push(payload);
      if (state.imageFail) await route.fulfill({ status: 503, json: { detail: 'Рисование временно недоступно' } });
      else {
        history['chat-a'].push({ id: 'image-edited', role: 'assistant', content: '![Отредактированное изображение](/uploads/audit-edited.png)' });
        await route.fulfill({ json: { kind: 'edit', url: '/uploads/audit-edited.png', message: { id: 'image-edited' } } });
      }
      return true;
    } });
    try {
      await f.page.getByRole('button', { name: 'Изменить', exact: true }).click();
      await f.input.fill('Сделай фон светлее');
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).click();
      await expect(f.page.getByText(/Рисование временно недоступно/).first()).toBeVisible();
      await expect(f.input).toHaveValue('Сделай фон светлее');
      f.state.imageFail = false;
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).click();
      await expect(f.page.getByRole('button', { name: 'Открыть изображение: Отредактированное изображение', exact: true })).toBeVisible();
      assert.deepEqual(f.state.imageRequests.map(r => r.source_urls), [['/uploads/audit-source.png'], ['/uploads/audit-source.png']]);
      assert(f.state.imageRequests.every(r => r.conversation_id === 'chat-a'));
    } finally { await f.context.close(); }
  });
  for (const uploadError of [false, true]) await test(`presentation: project upload ${uploadError ? 'failure blocks binding' : 'uses working API and binds document'}`, async () => {
    const f = await projectFixture({ uploadError });
    try {
      await f.workspace.locator('input[type=file]').setInputFiles({ name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('Материалы для презентации') });
      if (uploadError) {
        await expect(f.workspace.getByRole('alert')).toContainText('Не удалось прочитать документ');
        assert.equal(f.state.documentReads, undefined); assert.equal(f.state.boundDocument, undefined);
      } else {
        await expect.poll(() => f.state.boundDocument).toBe(42);
        assert.equal(f.state.lookupFilename, 'brief.txt');
        await expect(f.workspace.getByText('Материалы для презентации', { exact: true })).toBeVisible();
      }
      assert.equal(f.state.wrongUpload, undefined);
    } finally { await f.context.close(); }
  });
  await test('presentation: project table save conflict preserves edits and retry saves exact revision', async () => {
    const f = await projectFixture({ saveError: true });
    try {
      await f.workspace.getByRole('tab', { name: 'Результаты', exact: true }).click();
      await f.workspace.getByRole('button', { name: /Сравнение поставщиков/ }).click();
      await f.workspace.getByRole('button', { name: 'Редактировать', exact: true }).click();
      const price = f.workspace.getByRole('textbox', { name: 'Цена, строка r1', exact: true });
      await price.fill('1700');
      await f.workspace.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(f.workspace.getByRole('alert')).toContainText('Версия изменилась');
      await expect(price).toHaveValue('1700');
      f.state.saveError = false;
      await f.workspace.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect.poll(() => f.state.savedSpec?.rows[0].cells.price).toBe('1700');
      await expect(price).toBeHidden();
    } finally { await f.context.close(); }
  });
  await test('presentation: billing outage has retry instead of invented free limits', async () => {
    const f = await fixture({ startPath: '/billing', handleRoute: async ({ path, route, state }) => {
      if (path !== '/billing/subscription') return false;
      if (!state.recovered) await route.fulfill({ status: 503, json: { detail: 'Temporary outage' } });
      else await route.fulfill({ json: { tier: 'pro', name: 'Профи', unlimited: true } });
      return true;
    } });
    try {
      await expect(f.page.getByRole('alert')).toContainText('Не удалось загрузить тариф');
      await expect(f.page.getByText('без срока', { exact: true })).toBeHidden();
      f.state.recovered = true;
      await f.page.getByRole('button', { name: 'Повторить', exact: true }).click();
      await expect(f.page.getByText('Профи', { exact: true })).toBeVisible();
      await expect(f.page.getByRole('alert')).toBeHidden();
    } finally { await f.context.close(); }
  });
  await test('presentation: login preserves invite destination while profile is loading', async () => {
    const f = await fixture({ signedOut: true, startPath: '/join/demo-invite', handleRoute: async ({ path, route, profile, state }) => {
      if (path === '/auth/login') { await route.fulfill({ json: { access_token: 'new-access', refresh_token: 'new-refresh' } }); return true; }
      if (path === '/auth/me') { await new Promise(resolve => setTimeout(resolve, 350)); await route.fulfill({ json: profile }); return true; }
      if (path === '/share/demo-invite/join') { state.joined = true; await route.fulfill({ json: { id: 'chat-b' } }); return true; }
    } });
    try {
      await f.page.getByRole('textbox', { name: /Email/ }).fill('audit@example.com');
      await f.page.getByLabel(/^Пароль/).fill('password123');
      await f.page.locator('form').getByRole('button', { name: 'Войти', exact: true }).click();
      await expect.poll(() => f.state.joined).toBe(true);
      await expect(f.page).toHaveURL(/\/chat(?:\?c=chat-b)?$/);
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('presentation: mobile public menu has a working login', async () => {
    const f = await fixture({ signedOut: true, startPath: '/', viewport: { width: 390, height: 844 }, touch: true });
    try {
      await f.page.getByRole('button', { name: 'Меню', exact: true }).tap();
      await f.page.getByRole('link', { name: 'Войти', exact: true }).tap();
      await expect(f.page.getByRole('textbox', { name: /Email/ })).toBeVisible();
      await expect(f.page.getByRole('button', { name: 'Закрыть меню', exact: true })).toBeHidden();
    } finally { await f.context.close(); }
  });
  await test('new conversation creates a separate empty chat every time', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      const create = f.page.getByRole('button', { name: 'Новый вопрос', exact: true });
      await create.click();
      await expect.poll(() => f.state.created.length).toBe(1);
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик первого нового чата');
      await create.click();
      await expect.poll(() => f.state.created.length).toBe(2);
      await expect(f.input).toBeEnabled();
      await expect(f.input).toHaveValue('');
      await expect(f.page.getByRole('button', { name: 'Открыть беседу Новый чат', exact: true })).toHaveCount(2);
      await f.page.getByRole('button', { name: 'Открыть беседу Новый чат', exact: true }).last().click();
      await expect(f.input).toHaveValue('Черновик первого нового чата');
    } finally { await f.context.close(); }
  });
  await test('new conversation rapid clicks create distinct chats and keep latest active', async () => {
    const f = await fixture({ createDelay: 180 });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).evaluate(button => { button.click(); button.click(); button.click(); });
      await expect.poll(() => f.state.created.length).toBe(3);
      await expect(f.input).toBeEnabled();
      assert.equal(new Set(f.state.created).size, 3);
      await expect.poll(() => f.state.historyLoads.at(-1)).toBe(f.state.created.at(-1));
      assert.equal(f.state.activeId, f.state.created.at(-1));
      await f.page.reload();
      await expect(f.input).toBeEnabled();
      await expect.poll(() => f.state.historyLoads.at(-1)).toBe(f.state.created.at(-1));
    } finally { await f.context.close(); }
  });
  await test('new conversation works while another chat generates an answer', async () => {
    const f = await fixture({ holdAnswer: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Долгий вопрос в первой беседе');
      await f.input.press('Enter');
      await expect(f.page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
      await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).click();
      await expect.poll(() => f.state.created.length).toBe(1);
      await expect(f.input).toBeEnabled();
      await f.input.fill('Независимый вопрос');
      await f.input.press('Enter');
      await expect.poll(() => f.state.sends.length).toBe(2);
      assert.deepEqual(f.state.sends.map(item => item.conversation_id), ['chat-a', f.state.created[0]]);
    } finally { await f.context.close(); }
  });
  await test('new conversation failure preserves current chat and allows retry', async () => {
    const f = await fixture({ failCreate: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Сохранить текущий черновик');
      const create = f.page.getByRole('button', { name: 'Новый вопрос', exact: true });
      await create.click();
      await expect(f.page.getByText(/Не удалось создать беседу/)).toBeVisible();
      await expect(f.input).toHaveValue('Сохранить текущий черновик');
      f.state.failCreate = false;
      await create.click();
      await expect.poll(() => f.state.created.length).toBe(1);
      await expect(f.input).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('new conversation creates separate chats from the mobile sidebar', async () => {
    const f = await fixture({ viewport: { width: 390, height: 844 }, touch: true });
    try {
      await expect(f.input).toBeEnabled();
      for (let count = 1; count <= 2; count++) {
        await f.page.getByRole('button', { name: 'Открыть список бесед', exact: true }).click();
        await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).click();
        await expect.poll(() => f.state.created.length).toBe(count);
        await expect.poll(() => f.state.historyLoads.at(-1)).toBe(f.state.created.at(-1));
        await expect(f.input).toBeEnabled();
        await expect(f.page.getByRole('button', { name: 'Закрыть меню', exact: true })).toBeHidden();
      }
      await f.page.getByRole('button', { name: 'Открыть список бесед', exact: true }).click();
      await expect(f.page.getByRole('button', { name: 'Открыть беседу Новый чат', exact: true })).toHaveCount(2);
    } finally { await f.context.close(); }
  });
  await test('new conversation finishing late preserves a later chat selection', async () => {
    const f = await fixture({ createDelay: 500 });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).click();
      await f.select('Вторая беседа');
      await expect.poll(() => f.state.created.length).toBe(1);
      await expect.poll(() => f.state.activeId).toBe('chat-b');
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
      await f.page.reload();
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true }).first()).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('new conversation queued requests stop after logout', async () => {
    const f = await fixture({ createDelay: 300 });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Новый вопрос', exact: true }).evaluate(button => { button.click(); button.click(); button.click(); });
      await expect.poll(() => f.state.createRequests).toBe(1);
      await f.page.evaluate(async () => {
        const { useAuthStore } = await import('/src/stores/authStore.ts');
        useAuthStore.getState().logout();
      });
      await expect(f.page.locator('form').getByRole('button', { name: 'Войти', exact: true })).toBeVisible();
      await f.page.waitForTimeout(800);
      assert.equal(f.state.createRequests, 1);
    } finally { await f.context.close(); }
  });
  for (const auth of ['network', '500', 'refresh-network', 'refresh-500']) await test('temporary auth failure keeps session: ' + auth, async () => {
    const f = await fixture({ auth });
    try {
      try { await expect(f.input).toBeVisible(); }
      catch (error) { console.error('PAGE', f.page.url(), await f.page.locator('body').innerText()); throw error; }
      await expect(f.page).toHaveURL(/\/chat(?:\?[^#]*)?$/);
      assert.equal(await f.page.evaluate(() => JSON.parse(localStorage.getItem('gpt-ultra-auth')).state.accessToken), 'audit-access');
    } finally { await f.context.close(); }
  });
  await test('revoked refresh returns to login', async () => {
    const f = await fixture({ auth: 'refresh-invalid' });
    try { await expect(f.page.locator('form').getByRole('button', { name: 'Войти', exact: true })).toBeVisible(); }
    finally { await f.context.close(); }
  });
  await test('drafts and files belong to their chat; text survives reload', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик первой беседы');
      await f.page.locator('input[type=file]').setInputFiles({ name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('draft attachment') });
      await f.select('Вторая беседа');
      await expect(f.input).toHaveValue('');
      await expect(f.page.getByRole('button', { name: 'Убрать draft.txt' })).toHaveCount(0);
      await f.input.fill('Черновик второй беседы');
      await f.select('Первая беседа');
      await expect(f.input).toHaveValue('Черновик первой беседы');
      await expect(f.page.getByRole('button', { name: 'Убрать draft.txt' })).toBeVisible();
      await f.page.reload();
      await expect(f.input).toHaveValue('Черновик первой беседы');
    } finally { await f.context.close(); }
  });
  await test('IME confirmation does not send; Enter sends once and clears accepted draft', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('日本語');
      await f.input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true });
      assert.equal(f.state.sends.length, 0);
      await expect(f.input).toHaveValue('日本語');
      await f.input.press('Enter');
      await expect.poll(() => f.state.sends.length).toBe(1);
      await expect(f.input).toHaveValue('');
    } finally { await f.context.close(); }
  });
  await test('history failure has explicit retry and preserves draft', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Не потерять этот текст');
      f.state.historyError = true;
      await f.page.reload();
      await expect(f.page.getByRole('button', { name: 'Повторить загрузку' })).toBeVisible();
      await expect(f.input).toHaveValue('Не потерять этот текст');
      f.state.historyError = false;
      await f.page.getByRole('button', { name: 'Повторить загрузку' }).click();
      await expect(f.input).toBeEnabled();
    } finally { await f.context.close(); }
  });
  await test('late chat activation cannot override latest selection', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      f.state.delay['chat-b'] = 900;
      await f.select('Вторая беседа');
      await f.select('Первая беседа');
      await f.page.waitForTimeout(1100);
      await expect(f.page.getByText('Вопрос первой беседы', { exact: true }).first()).toBeVisible();
      await expect(f.page.getByText('Вопрос второй беседы', { exact: true })).toHaveCount(0);
    } finally { await f.context.close(); }
  });
  await test('partial attachment failure blocks send; retry only uploads failed file', async () => {
    const f = await fixture({ failFile: 'failed.txt' });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Прочитай оба файла');
      await f.page.locator('input[type=file]').setInputFiles([
        { name: 'ready.txt', mimeType: 'text/plain', buffer: Buffer.from('ready') },
        { name: 'failed.txt', mimeType: 'text/plain', buffer: Buffer.from('failed') },
      ]);
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).click();
      await expect(f.input).toBeEnabled();
      await expect(f.page.getByText(/Не загружено файлов: 1/).first()).toBeVisible();
      assert.equal(f.state.sends.length, 0);
      await expect(f.input).toHaveValue('Прочитай оба файла');
      f.state.failFile = '';
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).click();
      await expect.poll(() => f.state.sends.length).toBe(1);
      assert.deepEqual(f.state.uploads.sort(), ['failed.txt', 'failed.txt', 'ready.txt']);
    } finally { await f.context.close(); }
  });
  await test('microphone stops when conversation changes', async () => {
    const f = await fixture({ mockVoice: true });
    try {
      await expect(f.input).toBeEnabled();
      await f.page.getByRole('button', { name: 'Голосовой ввод', exact: true }).click();
      await expect(f.page.getByRole('button', { name: 'Остановить запись', exact: true })).toBeVisible();
      await f.select('Вторая беседа');
      await expect.poll(() => f.page.evaluate(() => window.auditStoppedTracks)).toBe(1);
      await expect(f.page.getByRole('button', { name: 'Голосовой ввод', exact: true })).toBeVisible();
    } finally { await f.context.close(); }
  });
  await test('late upload error stays in its original conversation', async () => {
    const f = await fixture({ failFile: 'failed.txt', uploadDelay: 700 });
    try {
      await expect(f.input).toBeEnabled();
      await f.input.fill('Черновик с неготовым файлом');
      await f.page.locator('input[type=file]').setInputFiles({ name: 'failed.txt', mimeType: 'text/plain', buffer: Buffer.from('failed') });
      await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).click();
      await f.select('Вторая беседа');
      await expect(f.input).toBeEnabled();
      await expect(f.input).toHaveValue('');
      await expect(f.page.getByText(/Не загружено файлов:/)).toHaveCount(0);
      await f.select('Первая беседа');
      await expect(f.input).toHaveValue('Черновик с неготовым файлом');
    } finally { await f.context.close(); }
  });
  await test('pre-cancelled document upload rejects without uploading', async () => {
    const f = await fixture();
    try {
      await expect(f.input).toBeEnabled();
      const result = await f.page.evaluate(async () => {
        const { apiFormDataProgress } = await import('/src/api/client.ts');
        const controller = new AbortController(); controller.abort();
        try { await apiFormDataProgress('/documents', new FormData(), { signal: controller.signal }); return 'unexpected success'; }
        catch (error) { return error.name; }
      });
      assert.equal(result, 'AbortError');
      assert.deepEqual(f.state.uploads, []);
    } finally { await f.context.close(); }
  });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 568 }]) {
    for (const theme of ['dark', 'light']) await test(`layout ${viewport.width}x${viewport.height} ${theme}`, async () => {
      const f = await fixture({ viewport, theme, touch: viewport.width < 600 });
      try {
        await expect(f.input).toBeEnabled();
        await f.input.fill('Длинный вопрос с подробностями. '.repeat(16));
        assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        const bounds = await f.input.boundingBox();
        assert(bounds.x >= 0 && bounds.x + bounds.width <= viewport.width + 1 && bounds.y >= 0 && bounds.y + bounds.height <= viewport.height);
        const send = await f.page.getByRole('button', { name: 'Отправить сообщение', exact: true }).boundingBox();
        assert(send.x >= 0 && send.x + send.width <= viewport.width && send.y + send.height <= viewport.height);
        await f.page.screenshot({ path: `${output}/chat-${viewport.width}-${theme}.png`, animations: 'disabled' });
      } finally { await f.context.close(); }
    });
  }
  const accessibility = [];
  for (const width of process.env.BITTHINK_UI_SKIP_SURFACES ? [] : [390, 1440]) for (const theme of ['light', 'dark']) for (const surface of ['login', 'landing', 'billing', 'settings', 'project']) {
    await test(`presentation: surface ${surface} ${width} ${theme}`, async () => {
      const options = { viewport: { width, height: width < 600 ? 844 : 900 }, touch: width < 600, theme };
      const f = surface === 'project' ? await projectFixture(options) : await fixture({ ...options, startPath: { login: '/login', landing: '/', billing: '/billing', settings: '/settings' }[surface], signedOut: surface === 'login' || surface === 'landing', handleRoute: async ({ path, route }) => {
        if (path === '/models/prompts') { await route.fulfill({ json: { prompts: [], active: null } }); return true; }
        if (path === '/billing/plans') { await route.fulfill({ json: { plans: [] } }); return true; }
      } });
      try {
        if (surface === 'project') {
          await f.workspace.getByRole('tab', { name: 'Результаты', exact: true }).click();
          await f.workspace.getByRole('button', { name: /Сравнение поставщиков/ }).click();
          await expect(f.workspace.getByRole('region', { name: 'Сравнение поставщиков', exact: true })).toBeVisible();
        } else await expect(f.page.locator('#main')).toContainText({ login: 'С возвращением', landing: 'Bit', billing: 'Общий запас', settings: 'Настройки' }[surface]);
        await f.page.evaluate(() => document.fonts.ready);
        assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${surface} overflows at ${width}`);
        await f.page.screenshot({ path: `${output}/${surface}-${width}-${theme}.png`, animations: 'disabled', fullPage: true });
        if (process.env.BITTHINK_AXE_PATH) {
          await f.page.addScriptTag({ path: process.env.BITTHINK_AXE_PATH });
          const violations = await f.page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } })).violations.map(v => ({ id: v.id, impact: v.impact, description: v.description, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })));
          accessibility.push({ surface, width, theme, violations });
          console.log(`A11Y ${surface} ${width} ${theme}: ${violations.map(v => v.id + '(' + v.nodes.length + ')').join(', ') || 'no violations'}`);
        }
      } finally { await f.context.close(); }
    });
  }
  if (accessibility.length) await writeFile(`${output}/accessibility.json`, JSON.stringify(accessibility, null, 2));
  assert.deepEqual(errors, [], 'No uncaught browser exceptions');
  console.log(`PASS ${passed} UX checks; no browser exceptions`);
} finally { await browser.close(); }
