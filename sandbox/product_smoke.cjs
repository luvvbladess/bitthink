// Dependency-free Chromium CDP smoke: render the built product at two sizes.
// This file is outside user workspaces and is not model-editable.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { spawn } = require('node:child_process');
const root = path.resolve(process.argv[2]);
const stack = process.argv[3];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const children = [];
let server, socket, profile;

async function main() {
  let port;
  if (stack === 'next' || stack === 'node') {
    const probe = http.createServer();
    await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
    port = probe.address().port;
    await new Promise(resolve => probe.close(resolve));
    const args = stack === 'next' ? ['run', 'start', '--', '--hostname', '127.0.0.1', '--port', String(port)] : ['run', 'start'];
    children.push(spawn('npm', args, { cwd: root, env: { ...process.env, PORT: String(port), HOST: '127.0.0.1' }, stdio: ['ignore', 'ignore', 'pipe'] }));
    children.at(-1).stderr.on('data', () => {});
  } else {
    const base = stack === 'static' ? root : path.join(root, 'dist');
    const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json', '.woff2': 'font/woff2' };
    server = http.createServer((req, res) => {
      try {
        let target = path.resolve(base, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname));
        if (!target.startsWith(base + path.sep) && target !== base) { res.writeHead(403).end(); return; }
        if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
        if (!fs.existsSync(target) && !path.extname(target)) target = path.join(base, 'index.html');
        res.writeHead(200, { 'Content-Type': types[path.extname(target)] || 'application/octet-stream' });
        fs.createReadStream(target).on('error', () => res.destroy()).pipe(res);
      } catch { res.writeHead(404).end(); }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    port = server.address().port;
  }
  const url = `http://127.0.0.1:${port}/`;
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(url)).ok) { ready = true; break; } } catch {}
    await wait(200);
  }
  if (!ready) throw new Error('Product HTTP server did not return success.');
  profile = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'bt-chromium-'));
  const chrome = spawn('/usr/lib/chromium/chromium', ['--headless', '--no-sandbox', '--disable-dev-shm-usage', '--no-zygote', '--single-process', '--disable-gpu', '--disable-crash-reporter', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  children.push(chrome);
  let diagnostic = '';
  chrome.stderr.on('data', value => { diagnostic = (diagnostic + value).slice(-4000); });
  const active = path.join(profile, 'DevToolsActivePort');
  for (let attempt = 0; attempt < 100 && !fs.existsSync(active); attempt++) await wait(100);
  if (!fs.existsSync(active)) throw new Error('Chromium failed to launch: ' + diagnostic.slice(-1000));
  const debugPort = fs.readFileSync(active, 'utf8').split('\n')[0];
  const pages = await (await fetch(`http://127.0.0.1:${debugPort}/json`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  const errors = [];
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id); pending.delete(message.id);
      message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
    }
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  };
  function call(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
  }
  await call('Page.enable'); await call('Runtime.enable');
  const qa = path.join(root, 'qa'); fs.mkdirSync(qa, { recursive: true });
  const measurements = [];
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: name === 'mobile' });
    await call('Page.navigate', { url });
    for (let attempt = 0; attempt < 40; attempt++) {
      const state = await call('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
      if (state.result.value === 'complete') break;
      await wait(100);
    }
    await wait(800);
    const result = await call('Runtime.evaluate', { expression: `JSON.stringify({title:document.title,text:(document.body?.innerText||'').trim().length,width:innerWidth,contentWidth:document.documentElement.scrollWidth,interactive:document.querySelectorAll('a[href],button,input,select,textarea').length})`, returnByValue: true });
    const metrics = JSON.parse(result.result.value);
    measurements.push({ screen: name, ...metrics });
    if (metrics.text < 10) throw new Error('Rendered product is empty at ' + name);
    if (name === 'mobile' && Math.abs(metrics.width - width) > 3) throw new Error('Mobile viewport meta tag is missing or incorrect.');
    if (stack !== 'node' && !metrics.title.trim()) throw new Error('Product page needs a document title.');
    if (metrics.contentWidth > metrics.width + 3) throw new Error('Horizontal overflow at ' + name + ': ' + metrics.contentWidth);
    const shot = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(path.join(qa, name + '.png'), Buffer.from(shot.data, 'base64'));
  }
  if (errors.length) throw new Error('Uncaught JavaScript errors: ' + errors.join('; '));
  console.log(JSON.stringify({ passed: true, measurements, screenshots: ['qa/desktop.png', 'qa/mobile.png'] }));
}

const deadline = setTimeout(() => { console.error('Browser smoke timed out'); process.exit(124); }, 70000);
main().catch(error => { console.error(error.message); process.exitCode = 1; }).finally(() => {
  clearTimeout(deadline);
  socket?.close();
  server?.close();
  for (const child of children) { try { child.kill('SIGKILL'); } catch {} }
  if (profile) { try { fs.rmSync(profile, { recursive: true, force: true }); } catch {} }
});
