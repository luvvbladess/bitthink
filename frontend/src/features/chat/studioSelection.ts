export type CanvasSelection = { text: string; tag: string; slide?: number };

// Runs inside the existing opaque-origin sandbox. It only reports a bounded
// description of the clicked element; it cannot read the host application's DOM.
export function withCanvasSelection(html: string): string {
  const script = `<script data-studio-selection>
(() => {
  let selecting = false, selected, previousOutline = '', previousOffset = '';
  const clear = () => { if (selected) { selected.style.outline = previousOutline; selected.style.outlineOffset = previousOffset; } selected = null; };
  addEventListener('message', e => {
    if (e.source !== parent || e.data?.type !== 'bt-select-mode') return;
    selecting = !!e.data.enabled;
    document.documentElement.style.cursor = selecting ? 'crosshair' : '';
    if (!selecting) clear();
  });
  document.addEventListener('click', e => {
    if (!selecting || !(e.target instanceof Element)) return;
    e.preventDefault(); e.stopImmediatePropagation(); clear();
    selected = e.target.closest('h1,h2,h3,h4,p,li,button,a,img,label,input,section,article') || e.target;
    previousOutline = selected.style.outline; previousOffset = selected.style.outlineOffset;
    selected.style.outline = '2px solid #21a0ce'; selected.style.outlineOffset = '3px';
    const slide = selected.closest('.slide');
    parent.postMessage({ type: 'bt-canvas-selection', text: (selected.innerText || selected.getAttribute('alt') || selected.getAttribute('aria-label') || '').trim().slice(0, 240), tag: selected.tagName.toLowerCase(), slide: slide ? [...document.querySelectorAll('.slide')].indexOf(slide) + 1 : undefined }, '*');
  }, true);
})();
<\/script>`;
  return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, `${script}</body>`) : html + script;
}

export function selectionPrompt(selection: CanvasSelection, change: string): string {
  const target = selection.text ? `элемент «${selection.text}»` : `элемент ${selection.tag}`;
  return `В текущем макете измени ${target}${selection.slide ? ` на слайде ${selection.slide}` : ''}: ${change.trim()}. Сохрани остальные элементы и содержание.`;
}
