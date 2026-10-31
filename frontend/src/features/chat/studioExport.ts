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
    + (canvasKindFromHtml(html) === 'slides' ? '.nav,.counter,[data-deck-ui]{display:none!important}' : '') + '</style>';
  const next = html || '';
  if (/<\/head>/i.test(next)) return next.replace(/<\/head>/i, `${freeze}</head>`);
  return freeze + next;
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
      await Promise.race([doc.fonts?.ready, wait(5000)]);
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
  const { toPng } = await import('html-to-image');
  // 4K for 16:9 slides; dense long pages retain at least native resolution.
  const desiredRatio = width === SLIDE_W && height === SLIDE_H ? 2.4 : 2;
  const pixelRatio = Math.min(desiredRatio, Math.sqrt(24_000_000 / (width * height)));
  if (pixelRatio < 1 || Math.max(width, height) * pixelRatio > 32760) {
    throw new Error('Макет слишком большой для картинки. Скачайте HTML.');
  }
  const clear = (color: string) => !color || color === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(color);
  let backgroundColor = getComputedStyle(node).backgroundColor;
  if (clear(backgroundColor)) backgroundColor = getComputedStyle(node.ownerDocument.body).backgroundColor;
  if (clear(backgroundColor)) backgroundColor = getComputedStyle(node.ownerDocument.documentElement).backgroundColor;
  if (clear(backgroundColor)) backgroundColor = '#ffffff';
  const opts = { width, height, pixelRatio, cacheBust: false, skipFonts: false, backgroundColor };
  try {
    return await toPng(node, opts);
  } catch {
    const mod = await import('html2canvas');
    const canvas = await mod.default(node, { scale: pixelRatio, width, height,
      windowWidth: width, windowHeight: height, backgroundColor: opts.backgroundColor,
      useCORS: true, allowTaint: false, logging: false });
    if (!canvas.width || !canvas.height) throw new Error('Не удалось снять макет. Скачайте HTML.');
    return canvas.toDataURL('image/png');
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

async function capturePages(html: string): Promise<{ kind: CanvasKind; images: string[]; width: number; height: number }> {
  return withCaptureFrame(html, async (doc, frame) => {
    const slides = [...doc.querySelectorAll<HTMLElement>('.slide')];
    if (slides.length) {
      const images: string[] = [];
      for (let index = 0; index < slides.length; index += 1) {
        showOnly(slides, index);
        const slide = slides[index];
        slide.style.position = 'absolute'; slide.style.inset = '0';
        thawSlide(slide);
        await wait(40);
        images.push(await nodeToImage(slide, SLIDE_W, SLIDE_H));
      }
      return { kind: 'slides' as const, images, width: SLIDE_W, height: SLIDE_H };
    }
    const width = 1080;
    frame.style.width = `${width}px`;
    frame.style.height = `${SLIDE_H}px`;
    await wait(80);
    const root = doc.documentElement;
    const height = Math.max(root.scrollHeight, doc.body.scrollHeight, 640);
    if (height > 20000) throw new Error('Макет слишком большой для картинки. Скачайте HTML.');
    frame.style.height = `${height}px`;
    await wait(40);
    const target = doc.body as HTMLElement;
    return { kind: 'page' as const, images: [await nodeToImage(target, width, height)], width, height };
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

const SAVEABLE_PICTURES = '<script data-studio-save>(function(){document.querySelectorAll("img").forEach(function(img){var src=img.getAttribute("src")||"";if(src.indexOf("data:")!==0)return;fetch(src).then(function(r){return r.blob()}).then(function(blob){img.src=URL.createObjectURL(blob)}).catch(function(){})})})();</script>';

/** A downloaded page must not leave its picture as a data URL: browsers show it and then refuse Save and Copy. */
export function withSaveablePictures(html: string): string {
  const text = html || '';
  if (!/data:image\//i.test(text) || /data-studio-save/.test(text)) return text;
  return /<\/body>/i.test(text) ? text.replace(/<\/body>/i, `${SAVEABLE_PICTURES}</body>`) : text + SAVEABLE_PICTURES;
}

export function downloadHtml(html: string, name?: string) {
  downloadBlob(new Blob([withSaveablePictures(html)], { type: 'text/html;charset=utf-8' }), `${exportStem(name)}.html`);
}

// A saved canvas keeps its pictures as files on this site and points to them by path
// (`/uploads/generated/….png`). Opened from a download, that path leads nowhere: the page shows
// a black screen. So a downloaded page carries its pictures inside.
const SITE_PICTURE = /(\bsrc=["']|url\(\s*["']?)(\/uploads\/[^"')\s]+)/gi;

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export async function inlineSitePictures(html: string): Promise<string> {
  const paths = [...new Set([...html.matchAll(SITE_PICTURE)].map((match) => match[2]))];
  if (!paths.length) return html;
  const inlined = new Map<string, string>();
  await Promise.all(
    paths.map(async (path) => {
      try {
        const response = await fetch(path, { credentials: 'same-origin' });
        if (response.ok) inlined.set(path, await blobToDataUrl(await response.blob()));
      } catch {
        // a picture that cannot be fetched stays a link
      }
    }),
  );
  return html.replace(SITE_PICTURE, (whole, head: string, path: string) => (inlined.has(path) ? head + inlined.get(path) : whole));
}

/** A Studio picture canvas is a page around one image; its source, or null for any other canvas. */
export function studioPictureSrc(html: string): string | null {
  if (!/data-studio-image/i.test(html || '')) return null;
  return /<img[^>]+\bsrc=["']([^"']+)["']/i.exec(html)?.[1] || null;
}

async function downloadStudioPicture(src: string, name?: string): Promise<void> {
  let blob: Blob;
  if (src.startsWith('data:')) {
    blob = dataUrlToBlob(src);
  } else {
    const response = await fetch(src, { credentials: 'same-origin' });
    if (!response.ok) throw new Error('Не удалось скачать картинку');
    blob = await response.blob();
  }
  const ext = /jpe?g/i.test(blob.type) ? 'jpg' : /webp/i.test(blob.type) ? 'webp' : 'png';
  downloadBlob(blob, `${exportStem(name)}.${ext}`);
}

/** What "download" should give for a saved canvas: the picture itself, or a page that works offline. */
export async function saveCanvasFile(html: string, name?: string): Promise<void> {
  const picture = studioPictureSrc(html);
  if (picture) {
    await downloadStudioPicture(picture, name);
    return;
  }
  downloadHtml(await inlineSitePictures(html), name);
}

/** The chat card's download: fetch the stored canvas and save it in a form that opens anywhere. */
export async function downloadCanvasFromUrl(url: string, name?: string): Promise<void> {
  const response = await fetch(url, { credentials: 'same-origin' });
  if (!response.ok) throw new Error('Не удалось скачать файл');
  await saveCanvasFile(await response.text(), name);
}

export async function exportCanvas(html: string, format: ExportFormat, name?: string) {
  const stem = exportStem(name);
  if (format === 'html') {
    const picture = studioPictureSrc(html);
    if (picture) {
      await downloadStudioPicture(picture, stem);
      return;
    }
    downloadHtml(await inlineSitePictures(html), stem);
    return;
  }
  // The PNG of a picture canvas is the picture, not a screenshot of the canvas around it.
  const picture = format === 'png' ? studioPictureSrc(html) : null;
  if (picture) {
    await downloadStudioPicture(picture, stem);
    return;
  }
  try {
    const { images, kind, width, height } = await capturePages(html);
    if (!images.length) throw new Error('не удалось снять кадры макета');
    if (format === 'png') {
      downloadBlob(dataUrlToBlob(images[0]), `${stem}.png`);
      return;
    }
    if (format === 'pdf') {
      const { jsPDF } = await import('jspdf');
      const pageHeight = kind === 'slides' ? height : Math.min(height, Math.round(width * Math.SQRT2));
      const pdf = new jsPDF({ orientation: width > pageHeight ? 'landscape' : 'portrait',
        unit: 'px', format: [width, pageHeight], hotfixes: ['px_scaling'], compress: true });
      let pageIndex = 0;
      for (const image of images) {
        for (let offset = 0; offset < height; offset += pageHeight) {
          if (pageIndex++) pdf.addPage([width, pageHeight], width > pageHeight ? 'landscape' : 'portrait');
          // Same aspect ratio on every page; PDF clips at its page boundary.
          pdf.addImage(image, 'PNG', 0, -offset, width, height, undefined, 'FAST');
        }
      }
      pdf.save(`${stem}.pdf`);
      return;
    }
    const PptxGenJS = (await import('pptxgenjs')).default;
    const deck = new PptxGenJS();
    deck.defineLayout({ name: 'WIDE16', width: 13.333, height: 7.5 });
    deck.layout = 'WIDE16';
    images.forEach((image) => {
      const slide = deck.addSlide();
      slide.addImage({ data: image, x: 0, y: 0, w: 13.333, h: 7.5 });
    });
    await deck.writeFile({ fileName: `${stem}.pptx` });
  } catch (error) {
    throw friendlyExportError(error);
  }
}
