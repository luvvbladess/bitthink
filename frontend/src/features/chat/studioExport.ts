import { downloadBlob } from '@/api/client';

export type CanvasKind = 'slides' | 'page';
export type ExportFormat = 'html' | 'pdf' | 'pptx' | 'png';

const SLIDE_W = 1600;
const SLIDE_H = 900;

export function canvasKindFromHtml(html: string): CanvasKind {
  return /class\s*=\s*['"][^'"]*\bslide\b/i.test(html || '') ? 'slides' : 'page';
}

export function exportStem(name?: string): string {
  return (name || 'maket').replace(/\.(html?|pdf|pptx|png)$/i, '') || 'maket';
}

export function formatsForKind(kind: CanvasKind): { id: ExportFormat; label: string }[] {
  if (kind === 'slides') {
    return [
      { id: 'pdf', label: 'PDF' },
      { id: 'pptx', label: 'PowerPoint' },
      { id: 'png', label: 'PNG' },
      { id: 'html', label: 'HTML' },
    ];
  }
  return [
    { id: 'png', label: 'PNG' },
    { id: 'pdf', label: 'PDF' },
    { id: 'html', label: 'HTML' },
  ];
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function friendlyExportError(error: unknown): Error {
  const raw = error instanceof Error ? error.message : String(error || '');
  const text = raw.toLowerCase();
  if (/не удалось|макет пустой|не удалось открыть/.test(raw)) return error instanceof Error ? error : new Error(raw);
  if (/tainted|securityerror|cors|unable to load/.test(text)) {
    return new Error('В макете есть картинки, которые браузер не даёт снять. Скачайте HTML.');
  }
  if (/oklch|oklab|color function|unsupported/.test(text)) {
    return new Error('Не удалось снять макет. Скачайте HTML или попробуйте PNG.');
  }
  if (/memory|allocation|maximum call|too large|quota/.test(text)) {
    return new Error('Макет слишком тяжёлый для этого формата. Скачайте HTML.');
  }
  return new Error('Не удалось собрать файл. Скачайте HTML или попробуйте ещё раз.');
}

function prepareCaptureHtml(html: string): string {
  const freeze =
    '<style data-studio-capture="1">.slide.is-on,.slide.is-on *{animation:none!important;transition:none!important}'
    + '.slide.is-on{opacity:1!important;visibility:visible!important}'
    + '.nav,.counter,[data-deck-ui]{display:none!important}</style>';
  const next = html || '';
  if (/<\/head>/i.test(next)) return next.replace(/<\/head>/i, `${freeze}</head>`);
  return freeze + next;
}

function rgbToHex(color: string): string {
  const match = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(color || '');
  if (!match) return '';
  return [match[1], match[2], match[3]]
    .map((part) => Number(part).toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase();
}

function readSlideCopy(slide: HTMLElement): { title: string; body: string[]; background: string; color: string } {
  const title = (slide.querySelector('h1, h2, h3')?.textContent || '').replace(/\s+/g, ' ').trim();
  const body = [...slide.querySelectorAll('p, li')]
    .map((node) => (node.textContent || '').replace(/\s+/g, ' ').trim())
    .filter((text) => text && text !== title)
    .slice(0, 8);
  const style = getComputedStyle(slide);
  return {
    title,
    body,
    background: rgbToHex(style.backgroundColor) || rgbToHex(getComputedStyle(slide.ownerDocument.body).backgroundColor) || '111111',
    color: rgbToHex(style.color) || 'F4F1EA',
  };
}

function captureLooksEmpty(dataUrl: string): boolean {
  const payload = (dataUrl.split(',')[1] || '').length;
  return payload < 32000;
}

function thawSlide(slide: HTMLElement) {
  slide.style.visibility = 'visible';
  slide.style.opacity = '1';
  slide.querySelectorAll<HTMLElement>('*').forEach((node) => {
    node.style.animation = 'none';
    node.style.transition = 'none';
    const opacity = node.style.opacity;
    if (opacity === '0') node.style.opacity = '1';
    if (node.style.visibility === 'hidden') node.style.visibility = 'visible';
  });
}

function flattenColors(doc: Document) {
  const win = doc.defaultView;
  if (!win) return;
  doc.querySelectorAll('link[rel="stylesheet"]').forEach((node) => node.remove());
  doc.querySelectorAll<HTMLElement>('*').forEach((node) => {
    const style = win.getComputedStyle(node);
    node.style.backgroundColor = style.backgroundColor;
    node.style.color = style.color;
    node.style.borderTopColor = style.borderTopColor;
    node.style.borderRightColor = style.borderRightColor;
    node.style.borderBottomColor = style.borderBottomColor;
    node.style.borderLeftColor = style.borderLeftColor;
    node.style.outlineColor = style.outlineColor;
    node.style.caretColor = style.caretColor;
    node.style.columnRuleColor = style.columnRuleColor;
    node.style.textDecorationColor = style.textDecorationColor;
  });
}

async function withCaptureFrame<T>(html: string, run: (doc: Document, frame: HTMLIFrameElement) => Promise<T>): Promise<T> {
  const frame = document.createElement('iframe');
  frame.setAttribute('sandbox', 'allow-same-origin');
  frame.setAttribute('title', 'Экспорт макета');
  frame.style.cssText = [
    'position:fixed',
    'left:-12000px',
    'top:0',
    `width:${SLIDE_W}px`,
    `height:${SLIDE_H}px`,
    'border:0',
    'opacity:0',
    'pointer-events:none',
    'background:#fff',
  ].join(';');
  document.body.appendChild(frame);
  frame.srcdoc = prepareCaptureHtml(html);
  try {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error('не удалось открыть макет')), 12000);
      frame.onload = () => {
        window.clearTimeout(timer);
        resolve();
      };
    });
    const doc = frame.contentDocument;
    if (!doc?.body) throw new Error('макет пустой');
    try {
      await doc.fonts?.ready;
    } catch {
      /* ignore */
    }
    await Promise.all(
      [...doc.images].map(
        (image) =>
          image.complete
            ? Promise.resolve()
            : new Promise<void>((resolve) => {
                image.onload = () => resolve();
                image.onerror = () => resolve();
                window.setTimeout(resolve, 2500);
              }),
      ),
    );
    flattenColors(doc);
    await wait(80);
    return await run(doc, frame);
  } finally {
    frame.remove();
  }
}

async function nodeToImage(node: HTMLElement, width: number, height: number): Promise<string> {
  node.style.width = `${width}px`;
  node.style.height = `${height}px`;
  node.style.maxWidth = `${width}px`;
  node.style.maxHeight = `${height}px`;
  node.style.visibility = 'visible';
  node.style.opacity = '1';
  const { toJpeg, toPng } = await import('html-to-image');
  const opts = {
    width,
    height,
    canvasWidth: width,
    canvasHeight: height,
    pixelRatio: 1,
    cacheBust: false,
    skipFonts: false,
    backgroundColor: getComputedStyle(node).backgroundColor || '#111111',
    quality: 0.86,
  };
  try {
    return await toJpeg(node, opts);
  } catch {
    try {
      return await toPng(node, { ...opts, quality: undefined });
    } catch (error) {
      const mod = await import('html2canvas');
      const html2canvas = (mod as { default: (el: HTMLElement, opts?: Record<string, unknown>) => Promise<HTMLCanvasElement> }).default;
      const canvas = await html2canvas(node, {
        scale: 1,
        width,
        height,
        windowWidth: width,
        windowHeight: height,
        backgroundColor: '#111111',
        useCORS: true,
        allowTaint: true,
        logging: false,
        foreignObjectRendering: false,
      });
      if (!canvas.width || !canvas.height) throw error;
      return canvas.toDataURL('image/jpeg', 0.86);
    }
  }
}

function showOnly(slides: HTMLElement[], index: number) {
  slides.forEach((slide, itemIndex) => {
    const on = itemIndex === index;
    slide.classList.toggle('is-on', on);
    slide.style.visibility = on ? 'visible' : 'hidden';
    slide.style.opacity = on ? '1' : '0';
    slide.style.pointerEvents = on ? 'auto' : 'none';
    slide.style.zIndex = on ? '1' : '0';
  });
}

type SlideCopy = { title: string; body: string[]; background: string; color: string };

async function capturePages(html: string): Promise<{ kind: CanvasKind; images: string[]; copies: SlideCopy[] }> {
  return withCaptureFrame(html, async (doc, frame) => {
    const slides = [...doc.querySelectorAll<HTMLElement>('.slide')];
    if (slides.length) {
      frame.style.width = `${SLIDE_W}px`;
      frame.style.height = `${SLIDE_H}px`;
      const images: string[] = [];
      const copies: SlideCopy[] = [];
      for (let index = 0; index < slides.length; index += 1) {
        showOnly(slides, index);
        const slide = slides[index];
        slide.style.position = 'absolute';
        slide.style.inset = '0';
        thawSlide(slide);
        copies.push(readSlideCopy(slide));
        await wait(40);
        images.push(await nodeToImage(slide, SLIDE_W, SLIDE_H));
      }
      return { kind: 'slides' as const, images, copies };
    }
    const root = doc.documentElement;
    const width = 1080;
    const height = Math.min(Math.max(root.scrollHeight || SLIDE_H, 640), 2400);
    frame.style.width = `${width}px`;
    frame.style.height = `${height}px`;
    await wait(40);
    const target = (doc.body as HTMLElement) || root;
    return { kind: 'page' as const, images: [await nodeToImage(target, width, height)], copies: [] };
  });
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [head, body] = dataUrl.split(',');
  const mime = /data:([^;]+)/.exec(head)?.[1] || 'image/jpeg';
  const bytes = atob(body || '');
  const buffer = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i += 1) buffer[i] = bytes.charCodeAt(i);
  return new Blob([buffer], { type: mime });
}

export function downloadHtml(html: string, name?: string) {
  downloadBlob(new Blob([html], { type: 'text/html;charset=utf-8' }), `${exportStem(name)}.html`);
}

export async function exportCanvas(html: string, format: ExportFormat, name?: string) {
  const stem = exportStem(name);
  if (format === 'html') {
    downloadHtml(html, stem);
    return;
  }
  try {
    const { images, kind, copies } = await capturePages(html);
    if (!images.length) throw new Error('не удалось снять кадры макета');
    if (format === 'png') {
      const png = images[0].startsWith('data:image/png')
        ? images[0]
        : await jpegToPng(images[0]);
      downloadBlob(dataUrlToBlob(png), `${stem}.png`);
      return;
    }
    const imageType = images[0].startsWith('data:image/png') ? 'PNG' : 'JPEG';
    if (format === 'pdf') {
      const { jsPDF } = await import('jspdf');
      const landscape = kind === 'slides';
      const pdf = new jsPDF({
        orientation: landscape ? 'landscape' : 'portrait',
        unit: 'px',
        format: landscape ? [SLIDE_W, SLIDE_H] : [1080, Math.max(640, Math.min(2400, SLIDE_H * 2))],
        hotfixes: ['px_scaling'],
      });
      images.forEach((image, index) => {
        if (index) pdf.addPage();
        const pageW = pdf.internal.pageSize.getWidth();
        const pageH = pdf.internal.pageSize.getHeight();
        pdf.addImage(image, imageType, 0, 0, pageW, pageH, undefined, 'FAST');
      });
      pdf.save(`${stem}.pdf`);
      return;
    }
    const PptxGenJS = (await import('pptxgenjs')).default;
    const deck = new PptxGenJS();
    deck.defineLayout({ name: 'WIDE16', width: 13.333, height: 7.5 });
    deck.layout = 'WIDE16';
    images.forEach((image, index) => {
      const slide = deck.addSlide();
      const copy = copies[index] || { title: '', body: [], background: '111111', color: 'F4F1EA' };
      if (captureLooksEmpty(image) && (copy.title || copy.body.length)) {
        slide.addShape('rect', { x: 0, y: 0, w: 13.333, h: 7.5, fill: { color: copy.background } });
        if (copy.title) {
          slide.addText(copy.title, {
            x: 0.7,
            y: 0.55,
            w: 12,
            h: 1.3,
            fontSize: 28,
            fontFace: 'Georgia',
            color: copy.color,
            bold: true,
          });
        }
        if (copy.body.length) {
          slide.addText(copy.body.join('\n'), {
            x: 0.7,
            y: 2.1,
            w: 12,
            h: 4.6,
            fontSize: 16,
            fontFace: 'Calibri',
            color: copy.color,
          });
        }
        return;
      }
      slide.addImage({ data: image, x: 0, y: 0, w: 13.333, h: 7.5 });
    });
    await deck.writeFile({ fileName: `${stem}.pptx` });
  } catch (error) {
    throw friendlyExportError(error);
  }
}

async function jpegToPng(dataUrl: string): Promise<string> {
  if (dataUrl.startsWith('data:image/png')) return dataUrl;
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const node = new Image();
    node.onload = () => resolve(node);
    node.onerror = () => reject(new Error('не удалось подготовить PNG'));
    node.src = dataUrl;
  });
  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth || SLIDE_W;
  canvas.height = image.naturalHeight || SLIDE_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return dataUrl;
  ctx.fillStyle = '#111111';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0);
  return canvas.toDataURL('image/png');
}
