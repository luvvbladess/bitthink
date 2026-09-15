const MARK = 'data-studio-nav';

export const SLIDE_DECK_CSS = `
html,body{height:100%;margin:0;overflow:hidden;overscroll-behavior:none;touch-action:none}
html{scroll-snap-type:none!important;scroll-behavior:auto!important}
.slide{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
overflow:hidden;box-sizing:border-box;visibility:hidden;pointer-events:none;z-index:0}
.slide.is-on{visibility:visible;pointer-events:auto;z-index:1}
.slide>.slide-inner{height:100%;min-height:0;display:flex;flex-direction:column;justify-content:center;
overflow:hidden;padding:clamp(1.25rem,4vw,4.5rem);box-sizing:border-box}
.nav,.counter,[data-deck-ui]{display:none!important}
`.trim();

export const SLIDE_DECK_JS = `
(() => {
  if (window.__btDeck) return;
  window.__btDeck = 1;
  const slides = [...document.querySelectorAll('.slide')];
  if (!slides.length) return;
  const index = () => {
    const at = slides.findIndex((slide) => slide.classList.contains('is-on'));
    return at < 0 ? 0 : at;
  };
  const ping = (at) => {
    try { parent.postMessage({ type: 'bt-deck-at', index: at }, '*'); } catch (e) {}
  };
  const show = (n) => {
    const next = Math.max(0, Math.min(slides.length - 1, n | 0));
    slides.forEach((slide, i) => slide.classList.toggle('is-on', i === next));
    ping(next);
  };
  show(index() || 0);
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.type !== 'bt-deck') return;
    if (typeof e.data.index === 'number') show(e.data.index);
    if (e.data.step === 1) show(index() + 1);
    if (e.data.step === -1) show(index() - 1);
  });
  window.addEventListener('keydown', (e) => {
    if (['ArrowDown','PageDown','ArrowRight',' '].includes(e.key)) { e.preventDefault(); show(index() + 1); }
    if (['ArrowUp','PageUp','ArrowLeft'].includes(e.key)) { e.preventDefault(); show(index() - 1); }
    if (e.key === 'Home') { e.preventDefault(); show(0); }
    if (e.key === 'End') { e.preventDefault(); show(slides.length - 1); }
  }, true);
  let lock = 0;
  let ignoreWheelUntil = 0;
  const step = (dir) => {
    const now = Date.now();
    if (now < lock) return;
    lock = now + 520;
    show(index() + dir);
  };
  window.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey) return;
    if (Date.now() < ignoreWheelUntil) { e.preventDefault(); return; }
    const dy = e.deltaY;
    const dx = e.deltaX;
    if (Math.abs(dy) < 12 || Math.abs(dy) < Math.abs(dx)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    step(dy > 0 ? 1 : -1);
  }, { passive: false, capture: true });
  let touchY = 0;
  let touchX = 0;
  window.addEventListener('touchstart', (e) => {
    touchY = e.changedTouches[0].clientY;
    touchX = e.changedTouches[0].clientX;
  }, { passive: true, capture: true });
  window.addEventListener('touchend', (e) => {
    const dy = touchY - e.changedTouches[0].clientY;
    const dx = touchX - e.changedTouches[0].clientX;
    if (Math.abs(dy) < 48 || Math.abs(dy) < Math.abs(dx) * 1.15) return;
    ignoreWheelUntil = Date.now() + 700;
    e.preventDefault();
    step(dy > 0 ? 1 : -1);
  }, { passive: false, capture: true });
})();
`.trim();

export function countSlides(html: string): number {
  const matches = (html || '').match(/class\s*=\s*['"][^'"]*\bslide\b/gi);
  return matches ? matches.length : 0;
}

export function ensureSlideRuntime(html: string): string {
  const text = html || '';
  if (!/\bslide\b/i.test(text) || !/class\s*=\s*['"][^'"]*\bslide\b/i.test(text)) return text;
  let next = text.replace(/<script\b[\s\S]*?<\/script>/gi, '');
  next = next.replace(new RegExp(`<style[^>]*${MARK}[^>]*>[\\s\\S]*?</style>`, 'gi'), '');
  const css = `<style ${MARK}="css">${SLIDE_DECK_CSS}</style>`;
  const js = `<script ${MARK}="js">${SLIDE_DECK_JS}</script>`;
  if (/<\/head>/i.test(next)) next = next.replace(/<\/head>/i, `${css}\n</head>`);
  else next = css + next;
  if (/<\/body>/i.test(next)) next = next.replace(/<\/body>/i, `${js}\n</body>`);
  else next = next + js;
  return next;
}
