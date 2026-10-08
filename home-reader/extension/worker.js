const BASE = 'https://bit-think.space/api/marketplace-relay';
let running = false;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const TAB_TTL = 5 * 60 * 1000;

async function cleanTabs(all = false) {
  const {owned = [], retained = []} = await chrome.storage.session.get(['owned','retained']);
  const live = [];
  for (const item of owned) {
    try {
      await chrome.tabs.get(item.id);
      if (all || item.expires <= Date.now()) await chrome.tabs.remove(item.id);
      else live.push(item);
    } catch {}
  }
  await chrome.storage.session.set({owned:live, retained:retained.filter(item => live.some(t => t.id === item.id))});
}

async function forgetTab(id) {
  const {owned = [], retained = []} = await chrome.storage.session.get(['owned','retained']);
  await chrome.storage.session.set({owned:owned.filter(t => t.id !== id), retained:retained.filter(t => t.id !== id)});
}

function productUrl(raw) {
  try {
    const u = new URL(raw), h = u.hostname.toLowerCase();
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    const domain = d => h === d || h.endsWith('.' + d);
    if (domain('ozon.ru')) return /^\/product\/[^/]+/.test(u.pathname);
    if (domain('wildberries.ru') || domain('wb.ru')) return /^\/catalog\/\d+\/(?:detail\.aspx|feedbacks\/?)$/i.test(u.pathname);
    if (h === 'market.yandex.ru') return /^\/(product--|product\/|card\/)/.test(u.pathname);
    if (domain('avito.ru')) return /^\/[^/]+\/[^/]+\/[^/]+_\d+\/?$/.test(u.pathname);
    if (domain('aliexpress.ru')) return /^\/item\/\d+/.test(u.pathname);
    if (domain('megamarket.ru') || domain('sbermegamarket.ru')) return /^\/catalog\/details\//.test(u.pathname);
    if (domain('lamoda.ru')) return /^\/p\//.test(u.pathname);
    if (['citilink.ru','dns-shop.ru','lemanapro.ru','leroymerlin.ru'].some(domain)) return /^\/product\//.test(u.pathname);
    if (domain('mvideo.ru')) return /^\/products\//.test(u.pathname);
    if (domain('eldorado.ru')) return /^\/cat\/detail\//.test(u.pathname);
    if (domain('chipdip.ru')) return /^\/product0?\/[^/]+/.test(u.pathname);
    if (domain('terraelectronica.ru') || domain('promelec.ru')) return /^\/product\/[^/]+/.test(u.pathname);
    if (domain('compel.ru')) return /^\/(item|product)\/[^/]+/.test(u.pathname);
    if (domain('platan.ru')) {
      if (/^\/(product|item)\/[^/]+/.test(u.pathname)) return true;
      return ['/shop/','/cgi-bin/qwery.pl'].includes(u.pathname) && [...u.searchParams.keys()].every(k => ['id','code','article','part','query','search','text','page','group','name','partnumber'].includes(k.toLowerCase()));
    }
    return false;
  } catch { return false; }
}

function shortUrl(raw) {
  try {
    const u=new URL(raw), h=u.hostname.toLowerCase();
    if(u.protocol!=='https:' || u.username || u.password || u.port) return false;
    if(h==='ozon.ru' || h.endsWith('.ozon.ru')) return /^\/t\/[A-Za-z0-9_-]+\/?$/.test(u.pathname);
    if(h==='market.yandex.ru') return /^\/cc\/[A-Za-z0-9_-]+\/?$/.test(u.pathname);
    return h==='sl.aliexpress.ru' && u.pathname==='/p' && u.searchParams.getAll('key').length===1 && /^[A-Za-z0-9_-]{1,128}$/.test(u.searchParams.get('key') || '') && [...u.searchParams.keys()].every(k=>['key','erid'].includes(k));
  } catch {return false;}
}

function shortDestinationAllowed(source, destination) {
  if(!shortUrl(source) || !productUrl(destination)) return false;
  const a=new URL(source).hostname.toLowerCase(), b=new URL(destination).hostname.toLowerCase();
  if(a==='market.yandex.ru') return b===a;
  if(a==='sl.aliexpress.ru') return b==='aliexpress.ru' || b.endsWith('.aliexpress.ru');
  return b==='ozon.ru' || b.endsWith('.ozon.ru');
}

function readerProfile(raw) {
  const u=new URL(raw), h=u.hostname.toLowerCase(), domain=d=>h===d || h.endsWith('.'+d);
  const common={name:'магазин', reviewPaths:[], reviewQueryKeys:['tab'],
    cards:'[itemprop="review"], [data-review-id], [data-review-uuid], [data-testid="review"], [data-testid="review-item"], [data-testid="review-card"], [itemprop="reviewBody"], [class*="review-text"], [class*="reviewText"]',
    containers:'#reviews, #section-reviews, [data-testid="reviews-list"]',
    rating:'[itemprop="aggregateRating"], [itemprop="ratingValue"], [itemprop="reviewCount"], [itemprop="ratingCount"]',
    controls:'', scope:'товар'};
  let path=u.pathname.replace(/\/$/,'');
  const add=(name,cards,containers,rating,controls='')=>Object.assign(common,{name,cards:common.cards+', '+cards,containers:common.containers+', '+containers,rating:common.rating+', '+rating,controls});
  if(domain('ozon.ru')) {
    add('Ozon','[data-widget="webReview"]','[data-widget="webListReviews"], [data-widget="webSingleProductReview"]','[data-widget*="ReviewProductScore"]','[data-widget="webReviewProductScore"]');
    common.reviewPaths=[path.replace(/\/reviews$/,''),path.replace(/\/reviews$/,'')+'/reviews'];
  } else if(domain('wildberries.ru') || domain('wb.ru')) {
    add('Wildberries','.feedback__text, .feedback__item, .comments__item, [data-feedback-id]','.feedbacks, .comments__list, .product-feedbacks','.product-review__rating, .product-review__count-review, .product-page__rating, .product-page__rating-count','a.product-review__count-review, .product-review__rating');
    const id=path.match(/^\/catalog\/(\d+)\//)?.[1];
    if(id) common.reviewPaths=['/catalog/'+id+'/feedbacks'];
    common.reviewQueryKeys.push('imtId','targetUrl');
  } else if(h==='market.yandex.ru') {
    add('Яндекс Маркет','[data-auto="review-item"], [data-auto="review-text"], [data-zone-name="Review"]','[data-auto="reviews-list"], [data-zone-name="Reviews"]','[data-auto="rating-value"], [data-auto="reviews-count"], [data-zone-name="rating"]','[data-auto="reviews-link"], [data-auto="reviews-tab"]');
    common.reviewPaths=[path.replace(/\/reviews$/,'')+'/reviews'];
  } else if(domain('aliexpress.ru')) {
    add('AliExpress RU','.feedback-item, .feedback-item__text, [data-pl="review-item"]','.feedback-list-wrap, .product-review-list','.product-rating, .product-evaluation, [data-testid="rating"]','[data-testid="reviews-tab"]');
    common.reviewPaths=[path];
  } else if(domain('dns-shop.ru')) {
    add('DNS','.ow-opinion-item, .opinion-item','.ow-opinions, .opinions-list','.product-card-top__rating, .product-card-top__reviews, .rating__value','a[href*="/opinion/"]');
    common.reviewPaths=[path.replace(/\/opinion$/,'')+'/opinion'];
  } else if(domain('citilink.ru')) {
    add('Ситилинк','[data-meta-name="Review"], .review-item','.reviews-list, [data-meta-name="Reviews"]','[data-meta-name="Rating"], [data-meta-name="ReviewsCount"]');
    common.reviewPaths=[path.replace(/\/otzyvy$/,'')+'/otzyvy'];
  } else if(domain('mvideo.ru') || domain('eldorado.ru')) {
    add(domain('mvideo.ru')?'М.Видео':'Эльдорадо','.review-item, .reviews-item, .review__item','.reviews-list, .reviews__list','.rating-value, .product-rating, .rating__value');
    common.reviewPaths=[path.replace(/\/reviews$/,'')+'/reviews'];
    if(domain('mvideo.ru')) {const id=path.replace(/\/reviews$/,'').match(/(?:-|\/)(\d+)$/)?.[1];if(id)common.reviewPaths.push('/products/'+id+'/reviews');}
  } else if(domain('megamarket.ru') || domain('sbermegamarket.ru')) {
    add('Мегамаркет','.review-item, .review-item__text','.reviews-list, .product-reviews','.product-rating, .rating-value, .reviews-count');
    common.reviewPaths=[path];
  } else if(domain('lamoda.ru')) {
    add('Lamoda','.review__item, .reviews__item','.reviews__list, .product-reviews','.product-rating, .rating__value, .reviews-count');
    common.reviewPaths=[path];
  } else if(domain('avito.ru')) {
    add('Авито','[data-marker="review/item"], [data-marker="reviews/item"], [data-marker="review-text"]','[data-marker="reviews/list"]','[data-marker="seller-rating/score"], [data-marker="seller-rating/summary"]');
    common.scope='продавец';
  } else {
    // Public store pages can expose standard Product JSON-LD and semantic
    // review cards without a marketplace-specific application.
    common.cards+=', .review-item, .product-review__item';
    common.containers+=', .reviews-list, .product-reviews';
    common.rating+=', .product-rating, .rating__value';
  }
  return common;
}

function reviewDestinationAllowed(source, destination) {
  try {
    const a=new URL(source), b=new URL(destination);
    const p=readerProfile(source);
    const allowedQuery=[...b.searchParams].every(([key,value])=>
      a.searchParams.get(key)===value ||
      (p.reviewQueryKeys.includes(key) && (key==='tab' ? /^(reviews?|feedbacks?|opinion)$/i.test(value) : /^[A-Za-z0-9_-]{1,100}$/.test(value))) ||
      (/^(track|utm_source|utm_medium|utm_campaign)$/.test(key) && /^[A-Za-z0-9_-]{1,200}$/.test(value)));
    return productUrl(source) && productUrl(destination) && a.origin===b.origin
      && p.reviewPaths.includes(b.pathname.replace(/\/$/,'')) && allowedQuery;
  } catch { return false; }
}

function browseUrl(raw) {
  if (productUrl(raw) || shortUrl(raw)) return true;
  try {
    const u=new URL(raw), h=u.hostname.toLowerCase();
    if(u.protocol!=='https:' || u.username || u.password || u.port) return false;
    if(h==='ozon.ru' || h.endsWith('.ozon.ru')) return /^\/(category|search)(\/|$)/.test(u.pathname);
    if(h==='wildberries.ru' || h.endsWith('.wildberries.ru') || h==='wb.ru' || h.endsWith('.wb.ru')) return /^\/catalog(\/|$)/.test(u.pathname);
    return h==='market.yandex.ru' && /^\/(search|catalog|catalog--[^/]+)(\/|$)/.test(u.pathname);
  } catch {return false;}
}

// Executed only in a tab created by this extension. No form values or cookies.
function readProduct(expectedUrl, section = 'overview', profile = {}) {
  let sampleSource='dom';
  const reviewCards=profile.cards || '[itemprop="review"], [data-review-id], [data-review-uuid], [data-widget="webReview"], [data-testid="review"], [class*="review-text"], [class*="reviewText"]';
  const reviewContainers=profile.containers || '[data-widget="webListReviews"], [data-widget="webSingleProductReview"], #section-reviews, #reviews';
function reviewSample() {
  const nodes=[...document.querySelectorAll(reviewCards)].filter(el=>
    (!el.getClientRects || el.getClientRects().length) && !el.closest?.('[data-zone-name="Recommendations"], .recommendations, [data-testid="recommendations"]'));
  // A body and its containing review card may both match. Keep one per review.
  const samples=nodes.filter(el=>!nodes.some(other=>other!==el && other.contains?.(el))).map(el=>(el.innerText || '').trim()).filter(Boolean);
  if (!samples.length) {
    // Ozon uses generated class names. Keep buyer text within its review widget,
    // rather than mistaking the score/count in the card header for reviews.
    for (const container of document.querySelectorAll(reviewContainers)) {
      const lines = (container.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      let current = [];
      for (const line of lines) {
        if (/^(?:Достоинства|Недостатки|Комментарий|Плюсы|Минусы)\s*:?$/i.test(line)) {
          if (current.some(s => s.replace(/\s*:\s*$/, '').toLowerCase() === line.replace(/\s*:\s*$/, '').toLowerCase())) {
            samples.push(current.join('\n')); current = [];
            if (samples.length >= 20) break;
          }
          current.push(line);
        } else if (current.length && !/^(?:Полезно|Ответить|Пожаловаться|Читать полностью|Показать ещё|\d+)$/i.test(line)) current.push(line);
      }
      if (current.length) samples.push(current.join('\n'));
      if (!samples.length) {
        // Generated CSS classes: locate repeated review blocks, strictly inside
        // the public review panel, rather than matching arbitrary page text.
        const queue=[{el:container,depth:0}];let seen=0;
        while(queue.length && seen++<600 && !samples.length) {
          const {el,depth}=queue.shift();
          const children=[...el.children].filter(child=>child.getClientRects().length);
          const cards=children.filter(child=>{const s=(child.innerText || '').trim();return s.length>=60 && s.length<=2500 && /[а-яa-z]{3}/i.test(s)});
          if(cards.length>=2 && cards.length>=children.length/2) samples.push(...cards.slice(0,20).map(child=>child.innerText.trim()));
          else if(depth<7) queue.push(...children.slice(0,40).map(child=>({el:child,depth:depth+1})));
        }
      }
      if (!samples.length) {
        // Some review widgets expose their own rendered-state JSON before the
        // text appears. Read that widget only, never whole application state.
        const raw=container.getAttribute('data-state');
        if(raw && raw.length<=80000) try {
          const value=JSON.parse(raw);let visited=0;
          const visit=(node,depth=0)=>{
            if(!node || typeof node!=='object' || visited++>500 || depth>8 || samples.length>=20) return;
            const content=node.content;
            const parts=[node.reviewBody,content?.positive?('Достоинства: '+content.positive):'',content?.negative?('Недостатки: '+content.negative):'',content?.comment?('Комментарий: '+content.comment):''].filter(v=>typeof v==='string' && v.trim());
            if(parts.length) {samples.push(parts.join('\n'));return;}
            for(const child of (Array.isArray(node)?node.slice(0,20):Object.values(node))) visit(child,depth+1);
          };
          visit(value);if(samples.length) sampleSource='widget_state';
        } catch {}
      }
    }
  }
  return [...new Set(samples)].slice(0,20).map(s => s.slice(0,1000));
}

  if (expectedUrl && location.href !== expectedUrl) return {status:'error',url:location.href,text:'',title:''};
  const root = document.querySelector('main, [role="main"]') || document.body;
  const extra = [...document.querySelectorAll('[role="dialog"], [role="tabpanel"]')].filter(el => !root?.contains(el)).map(el => el.innerText || '').join('\n');
  let text = (root?.innerText || '') + '\n' + extra;
  // Keep generated review lists out of the generic full-page snapshot. Their
  // bounded sample is extracted separately, including widgets outside <main>.
  for (const container of document.querySelectorAll(reviewContainers)) {
    if (container.innerText) text = text.split(container.innerText).join('');
  }
  // Exclude already loaded review cards beyond the twenty-review sample.
  const reviewTexts = [...new Set([...document.querySelectorAll(reviewCards)].map(el => (el.innerText || '').trim()).filter(Boolean))];
  for (const skipped of reviewTexts.slice(20)) text = text.split(skipped).join('');
  const title = document.title.slice(0, 500);
  const pageHeading=(document.querySelector('h1, [role="heading"][aria-level="1"]')?.innerText || '').replace(/\s+/g,' ').trim();
  const missing=/^(?:404(?:\s*[-–:|]\s*.*)?|страница не найдена|страница удалена|товар не найден|такого товара нет|page not found)$/i;
  if(missing.test(title.trim()) || missing.test(pageHeading)) return {status:'error',url:location.href,title,text:'#PAGE_NOT_FOUND# Страница или товар не найдены.'};
  if(/^(?:500|502|503|504|service unavailable|bad gateway|internal server error)$/i.test(title.trim()) || /^(?:внутренняя ошибка сервера|service unavailable|bad gateway|internal server error)$/i.test(pageHeading)) return {status:'error',url:location.href,title,text:'#PAGE_UNAVAILABLE# Ошибка сервера магазина.'};
  const wall = text.length < 3000 && /похоже, нет соединения|вы не робот|проверяем браузер|подозрительная активность|доступ ограничен|доступ к.{0,40}сервису временно запрещ[её]н|captcha|access denied|verify you are human/i.test(text.replace(/\s+/g, ' '));
  const facts = [];
  const visit = item => {
    if (Array.isArray(item)) return item.forEach(visit);
    if (!item || typeof item !== 'object') return;
    const kinds = [].concat(item['@type'] || []);
    if (kinds.some(k => String(k).split('/').pop() === 'Product')) {
      const product = {};
      for (const key of ['name','description','sku','brand','offers','aggregateRating','review']) {
        if (key in item) product[key] = key === 'review' && Array.isArray(item[key]) ? item[key].slice(0,20) : item[key];
      }
      facts.push(JSON.stringify(product));
    }
    Object.values(item).forEach(visit);
  };
  for (const script of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0, 10)) {
    try { visit(JSON.parse(script.textContent.slice(0, 80000))); } catch {}
  }
  const body = (facts.length ? 'Данные товара (JSON-LD):\n' + facts.join('\n') + '\n\n' : '') + text.trim();
  if (section === 'отзывы' && !wall) {
    const samples = reviewSample();
    let source=samples.length?sampleSource:'none';
    for (const raw of facts) {
      if (samples.length) break;
      try {
        const p = JSON.parse(raw);
        for (const review of [].concat(p.review || []).slice(0,20)) {
          if (review.reviewBody || review.description) {samples.push(String(review.reviewBody || review.description).slice(0,1000));source='jsonld';}
        }
      } catch {}
    }
    if (samples.length) return {status:'ok',url:location.href,title,review_diagnostics:{source,count:Math.min(20,samples.length),dom_nodes:document.querySelectorAll(reviewCards).length,containers:document.querySelectorAll(reviewContainers).length},
      text:'ТЕКСТЫ ОТЗЫВОВ (не более 20; только видимая выборка; '+(profile.scope || 'товар')+'):\n'+samples.slice(0,20).map((s,i)=>`${i+1}. ${s}`).join('\n\n').slice(0,7500)};
    const emptyText=(text+'\n'+[...document.querySelectorAll(reviewContainers)].map(el=>el.innerText || '').join('\n')).replace(/\s+/g,' ');
    const noReviews=emptyText.match(/(?:отзывов (?:пока |ещ[её] )?нет|пока нет отзывов|нет отзывов|no reviews yet)/i);
    if(noReviews) return {status:'ok',url:location.href,title,review_diagnostics:{source:'none',count:0,stage:'empty'},text:'На странице прямо указано отсутствие отзывов: «'+noReviews[0]+'». Это не ошибка загрузки.'};
    return {status: body.length >= 50 ? 'ok' : 'error',url:location.href,title,
      review_diagnostics:{source:'none',count:0,stage:'not_extracted',containers:document.querySelectorAll(reviewContainers).length,dom_nodes:document.querySelectorAll(reviewCards).length},
      text:'Тексты отзывов не извлечены: раздел не загрузился либо его разметка не распознана. Рейтинг и число оценок не заменяют чтение отзывов.'};
  }
  // Preserve stock and lead-time passages before long descriptions are clipped.
  const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
  const commercial = new Set();
  lines.forEach((line, index) => {
    if (/в наличии|наличие|под заказ|нет в продаже|склад|доставк|поставк|отгруз|минимальн.{0,20}заказ|кратност|упаковк|MOQ|lead.?time|in stock/i.test(line)) {
      for (const adjacent of lines.slice(Math.max(0,index-1),index+3)) commercial.add(adjacent.slice(0,500));
    }
  });
  const stock = [...commercial].join('\n').slice(0,5000);
  const focused = new Set();
  const focusPattern = section === 'отзывы' ? /отзыв|оценк|рейтинг|достоинств|недостатк|комментар|покупател/i
    : section === 'характеристики' ? /характеристик|комплект|при[её]мник|микрофон|bluetooth|lightspeed|корпус|размер|материал|модель|артикул/i
    : section === 'описание' ? /описани|комплект|при[её]мник|микрофон|особенност|подключени/i
    : /отзыв|оценк|рейтинг|продавец|магазин|₽|руб\.?|цен[аыу]|комплект|при[её]мник|lightspeed/i;
  lines.forEach((line,index)=>{
    if(focusPattern.test(line)) for(const adjacent of lines.slice(Math.max(0,index-2),index+5)) focused.add(adjacent.slice(0,650));
  });
  // Read rating/price/review widgets that can sit outside <main>.
  const selector = section === 'отзывы'
    ? '[itemprop="review"], [data-review-id], [data-widget="webReview"], [data-testid="review"], [class*="review-text"], [class*="reviewText"]'
    : '[itemprop="price"], [data-widget*="Price"], [data-widget*="Seller"], '+(profile.rating || '[itemprop="aggregateRating"], [itemprop="ratingValue"], [itemprop="reviewCount"], [data-widget*="ReviewProductScore"]');
  const widgets = [];
  // Preserve explicit rating/count widgets before price/seller/description
  // snippets, including semantic content attributes outside <main>.
  for (const el of [...document.querySelectorAll(profile.rating || '[itemprop="ratingValue"], [itemprop="reviewCount"]')].slice(0,12)) {
    if(el.closest?.('[data-zone-name="Recommendations"], .recommendations, [data-testid="recommendations"]')) continue;
    const value=(el.innerText || el.getAttribute('content') || el.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim();
    if(value) widgets.push('Рейтинг/число оценок ('+(profile.scope || 'товар')+'): '+value.slice(0,500));
  }
  for(const el of [...document.querySelectorAll(selector)].slice(0,20)) {
    const value=(el.innerText || el.getAttribute('content') || '').replace(/\s+/g,' ').trim();
    if(value) widgets.push(((el.getAttribute('itemprop') || 'Виджет карточки')+': '+value).slice(0,1200));
  }
  const signals=[...new Set(section === 'отзывы' && widgets.length ? widgets : [...widgets,...focused])].join('\n').slice(0,4500);
  const schemaSummary = facts.map(raw=>{
    try { const p=JSON.parse(raw); if(section==='отзывы') return JSON.stringify({aggregateRating:p.aggregateRating,review:p.review}).slice(0,550);
      if(section!=='overview') return JSON.stringify({name:p.name,sku:p.sku}).slice(0,300);
      if(p.description) p.description=String(p.description).slice(0,200);
      if(p.review) p.review=JSON.stringify(p.review).slice(0,450);return JSON.stringify(p).slice(0,1300);
    } catch{return '';}
  }).filter(Boolean).slice(0,1).join('\n');
  const cards=new Map();
  for(const a of [...document.querySelectorAll('a[href]')]) {
    try {
      const u=new URL(a.href,location.href), current=new URL(location.href);
      if(u.protocol!=='https:' || u.username || u.password || u.origin!==current.origin) continue;
      if(!/^\/(product0?\/|card\/|product--[^/]+\/|catalog\/\d+\/detail\.aspx)/.test(u.pathname)) continue;
      u.hash='';
      const label=(a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim().slice(0,180);
      if(!cards.has(u.href)) cards.set(u.href,label || 'Карточка товара');
      if(cards.size>=24) break;
    } catch {}
  }
  const candidates=[...cards].map(([url,label])=>label+' — '+url).join('\n');
  return {status: wall ? 'blocked' : body.length >= 50 ? 'ok' : 'error', url: location.href,
    title, text: wall ? '' : (title + '\n\nФакты карточки (JSON-LD):\n'+schemaSummary+'\n\nДанные раздела '+section+' (фрагменты, не полная выборка):\n'+signals+(stock ? '\n\nУсловия продажи (фрагменты страницы):\n'+stock : '')+(candidates ? '\n\nСсылки на отдельные карточки из страницы (ещё не проверены):\n'+candidates : '')+'\n\n'+(section === 'отзывы' ? 'Выборка: не более 20 доступных отзывов; полная лента не обходилась.' : body)).slice(0,80000)};
}

async function api(path, method = 'GET', body) {
  const config = await (await fetch(chrome.runtime.getURL('config.json'))).json();
  if (config.server_url !== 'https://bit-think.space' || config.token.length < 32) throw new Error('Нет ключа подключения');
  const response = await fetch(BASE + path, {method, cache: 'no-store', credentials: 'omit',
    signal: AbortSignal.timeout(25000), headers: {'Authorization': 'Bearer ' + config.token, 'Content-Type': 'application/json'},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  if (response.status === 410) return null;
  if (!response.ok) throw new Error('Сервер: HTTP ' + response.status);
  return response.json();
}

// Expand only known informational controls; never cart, account or checkout.
async function revealSections(expectedUrl, section, profile = {}) {
  if (location.href !== expectedUrl) return;
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const labels = {описание:/^(?:описание(?: товара)?|о товаре|description)$/i, характеристики:/^(?:все )?характеристики(?: товара)?$|^specifications$/i, отзывы:/^(?:все |читать все |смотреть все |показать все )?(?:отзывы(?: покупателей| о товаре| и вопросы)?|оценки и отзывы|customer reviews|reviews|feedbacks?)(?:\s*[\d\s.,()]+)?$|^[\d\s.,()]+\s*отзыв[а-я]*$/i};
  const startX = scrollX, startY = scrollY;
  let clicked='none';
  const currentPage=new URL(location.href);
  const alreadyReviews=section==='отзывы' && (/\/(reviews|feedbacks|opinion|otzyvy)\/?$/.test(currentPage.pathname) || currentPage.searchParams.get('tab')==='reviews');
  for (const label of (alreadyReviews?[]:[labels[section]]).filter(Boolean)) {
    if (location.href !== expectedUrl) break;
    const candidates = [...document.querySelectorAll('button, [role="tab"], [role="button"], a'+(profile.controls ? ', '+profile.controls : ', [data-widget="webReviewProductScore"]'))];
    const control = candidates.find(el => {
      const caption=(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g,' ').trim();
      const knownControl=section==='отзывы' && profile.controls && el.matches(profile.controls);
      if ((!label.test(caption) && !knownControl) || !el.getClientRects().length) return false;
      if (el.tagName === 'A') {
        const u = new URL(el.href, location.href), current = new URL(location.href);
        const sameDocument = u.pathname === current.pathname && u.search === current.search;
        const paths=profile.reviewPaths || [current.pathname.replace(/\/reviews\/?$/, '/').replace(/\/$/,'')+'/reviews'];
        const queryAllowed=[...u.searchParams].every(([key,value])=>current.searchParams.get(key)===value ||
          ((profile.reviewQueryKeys || ['tab']).includes(key) && (key==='tab' ? /^(reviews?|feedbacks?|opinion)$/i.test(value) : /^[A-Za-z0-9_-]{1,100}$/.test(value))) ||
          (/^(track|utm_source|utm_medium|utm_campaign)$/.test(key) && /^[A-Za-z0-9_-]{1,200}$/.test(value)));
        const reviewsPage = section === 'отзывы' && paths.includes(u.pathname.replace(/\/$/,'')) && queryAllowed;
        if (u.origin !== current.origin || (!sameDocument && !reviewsPage)) return false;
      }
      return true;
    });
    if (control) {
      const child=[...control.querySelectorAll('a, button, [role="button"], span')].find(el=>label.test((el.innerText || '').replace(/\s+/g,' ').trim()) && el.getClientRects().length);
      const target=child && child.tagName!=='A'?child:control;
      target.scrollIntoView({block:'center'}); target.click();clicked=target.tagName.toLowerCase();await wait(1000);
    }
  }
  if (section === 'отзывы') {
    const panel = document.querySelector(profile.containers || '[data-widget="webListReviews"], #section-reviews, #reviews');
    if (panel) panel.scrollIntoView({block:'start'});
    for (let attempt = 0; attempt < 6; attempt++) {
      if (location.origin !== new URL(expectedUrl).origin) break;
      const loaded = document.querySelector(profile.cards || '[itemprop="review"], [data-review-id], [data-review-uuid], [data-widget="webReview"], [data-testid="review"], [class*="review-text"], [class*="reviewText"]');
      if (loaded?.innerText?.trim().length > 30 || (panel?.innerText || '').trim().length > 100) break;
      await wait(500);
    }
  }
  for (let step = 0; step < 2 && location.href.split('#')[0] === expectedUrl.split('#')[0]; step++) {
    if (section === 'отзывы' && document.querySelectorAll(profile.cards || '[itemprop="review"], [data-review-id], [data-widget="webReview"], [data-testid="review"]').length >= 20) break;
    scrollBy(0, innerHeight * 0.9);
    await wait(350);
  }
  scrollTo(startX, startY);
  return {control:clicked,dom_nodes:document.querySelectorAll(profile.cards || '[itemprop="review"], [data-review-id]').length};
}

async function readJob(job) {
  const empty = {status:'error', url:job.url, text:'', title:''};
  if (!browseUrl(job.url)) return empty;
  const {retained = []} = await chrome.storage.session.get('retained');
  let tab, keep = false;
  const match = retained.find(item => item.url === job.url);
  if (match) { try { tab = await chrome.tabs.get(match.id); } catch {} }
  if (!tab) tab = await chrome.tabs.create({url: job.url, active: false});
  const {owned = []} = await chrome.storage.session.get('owned');
  await chrome.storage.session.set({owned:[...owned.filter(t => t.id !== tab.id), {id:tab.id, expires:Date.now()+TAB_TTL}]});
  await chrome.storage.session.set({retained: retained.filter(item => item.id !== tab.id)});
  try {
    for (let attempt = 0; attempt < 18; attempt++) {
      await pause(1000);
      tab = await chrome.tabs.get(tab.id);
      if (!browseUrl(tab.url)) continue;
      if (tab.status !== 'complete') continue;
      if (shortUrl(job.url)) {
        if (shortUrl(tab.url)) continue;
        if (!shortDestinationAllowed(job.url,tab.url)) return empty;
      }
      const [injected] = await chrome.scripting.executeScript({target:{tabId:tab.id}, func:readProduct, args:[tab.url,'overview',readerProfile(tab.url)]});
      const result = injected?.result;
      if (!result || !browseUrl(result.url)) continue;
      if(result.status==='error' && /^#PAGE_(NOT_FOUND|UNAVAILABLE)#/.test(result.text || '')) return result;
      if (result.status === 'ok' && attempt >= 2) {
        if(!productUrl(result.url)) return {...result,text:('Это подборка/поиск, не отдельное предложение. Не рекомендуй этот URL как товар. Открой найденные карточки и сравни их.\n\n'+result.text).slice(0,80000)};
        // Keep the initial description when a section replaces the main panel.
        const chunks = [result.text.slice(0,2800)];
        let reviews={stage:'not_extracted',source:'none',count:0};
        for (const section of ['описание','характеристики','отзывы']) {
          try {
          const before=tab.url;
          let revealFailed=false;
          try {
            const [revealed]=await chrome.scripting.executeScript({target:{tabId:tab.id}, func:revealSections, args:[tab.url, section, readerProfile(tab.url)]});
            if(section==='отзывы' && revealed?.result) Object.assign(reviews,revealed.result);
          } catch { revealFailed=true; }
          // A click may resolve its script before Chrome commits navigation.
          await pause(250);
          tab = await chrome.tabs.get(tab.id);
          if (revealFailed) for(let retry=0;retry<10 && tab.url===before;retry++) {await pause(200);tab=await chrome.tabs.get(tab.id);}
          if (section==='отзывы' && reviewDestinationAllowed(before,tab.url) && tab.url!==before) {
            // Chrome may reject OR resolve the interrupted injection without a
            // result. Resume after either outcome on the same product only.
            for(let retry=0;retry<10 && tab.status!=='complete';retry++) {await pause(500);tab=await chrome.tabs.get(tab.id);}
            if (!reviewDestinationAllowed(before,tab.url) || tab.status!=='complete') break;
            await chrome.scripting.executeScript({target:{tabId:tab.id}, func:revealSections, args:[tab.url, section, readerProfile(tab.url)]});
          } else if(revealFailed) break;
          if (tab.url!==before && new URL(tab.url).pathname!==new URL(before).pathname && !reviewDestinationAllowed(before,tab.url)) break;
          if (!productUrl(tab.url)) break;
          const [more] = await chrome.scripting.executeScript({target:{tabId:tab.id}, func:readProduct, args:[tab.url,section,readerProfile(tab.url)]});
          if(section==='отзывы' && more?.result?.review_diagnostics) Object.assign(reviews,more.result.review_diagnostics);
          if (more?.result?.status === 'ok' && productUrl(more.result.url)) chunks.push(section.toUpperCase() + '\n' + more.result.text.slice(0, section === 'отзывы' ? 3800 : 1950));
          } catch (err) { console.warn('Reader section unavailable:', section, String(err)); break; }
        }
        if(!reviews.count && reviews.stage!=='empty') {
          const profile=readerProfile(result.url), target=new URL(result.url);
          // One deterministic public-section retry when an app's click handler
          // or lazy section did not expose buyer text. Never paginate reviews.
          if(profile.reviewPaths.length) {
            target.hash='';target.search='';
            if(profile.reviewPaths.includes(target.pathname.replace(/\/$/,''))) target.searchParams.set('tab','reviews');
            else target.pathname=profile.reviewPaths[0];
            if(target.href===tab.url && profile.reviewPaths.length>1) {target.search='';target.pathname=profile.reviewPaths[profile.reviewPaths.length-1];}
            if(reviewDestinationAllowed(result.url,target.href)) try {
              await chrome.tabs.update(tab.id,{url:target.href});await pause(500);
              for(let retry=0;retry<15;retry++) {tab=await chrome.tabs.get(tab.id);if(tab.status==='complete' && tab.url===target.href) break;await pause(300);}
              if(tab.status==='complete' && reviewDestinationAllowed(result.url,tab.url)) {
                const [opened]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:revealSections,args:[tab.url,'отзывы',readerProfile(tab.url)]});
                tab=await chrome.tabs.get(tab.id);
                if(tab.status==='complete' && reviewDestinationAllowed(result.url,tab.url)) {
                  const [sample]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:readProduct,args:[tab.url,'отзывы',readerProfile(tab.url)]});
                  if(sample?.result?.status==='ok') {
                    Object.assign(reviews,opened?.result || {},sample.result.review_diagnostics || {},{retry:true});
                    if(reviews.count)reviews.stage='read';
                    const old=chunks.findIndex(chunk=>chunk.startsWith('ОТЗЫВЫ\n'));
                    const value='ОТЗЫВЫ\n'+sample.result.text.slice(0,3800);
                    if(old>=0)chunks[old]=value;else chunks.push(value);
                  }
                }
              }
            } catch {reviews.stage='section_retry_failed';}
          }
        }
        if(!chunks.some(chunk=>chunk.startsWith('ОТЗЫВЫ\n'))) chunks.push('ОТЗЫВЫ\nТексты отзывов не извлечены: раздел не удалось открыть или прочитать. Рейтинг и число оценок не заменяют тексты покупателей.');
        return {...result, reader_version:chrome.runtime.getManifest?.().version || '1.8.0',review_diagnostics:reviews,text:[...new Set(chunks)].join('\n\n').slice(0,10800)};
      }
      if (attempt >= 10 && result.status === 'blocked') {
        keep = true;
        const current = (await chrome.storage.session.get('retained')).retained || [];
        while (current.length >= 3) {
          const old = current.shift();
          try { await chrome.tabs.remove(old.id); } catch {}
          await forgetTab(old.id);
        }
        current.push({id:tab.id, url:job.url});
        await chrome.storage.session.set({retained:current});
        return {...result, url:job.url, text:''};
      }
    }
    return empty;
  } finally {
    if (!keep) { try { await chrome.tabs.remove(tab.id); } catch {} await forgetTab(tab.id); }
  }
}

async function pump() {
  if (running || !(await chrome.storage.local.get('enabled')).enabled) return;
  running = true;
  try {
    while ((await chrome.storage.local.get('enabled')).enabled) {
      await cleanTabs();
      await api('/heartbeat', 'POST',{reader_version:chrome.runtime.getManifest?.().version || '1.8.0'});
      await chrome.storage.local.set({state:'Подключено. Ожидаю ссылки.'});
      const {job} = await api('/jobs');
      if (job) {
        if (!(await chrome.storage.local.get('enabled')).enabled) break;
        let result;
        try { result = await readJob(job); } catch { result = {status:'error', url:job.url, text:'', title:''}; }
        await api('/jobs/' + encodeURIComponent(job.id), 'POST', result);
        await chrome.storage.local.set({state: result.status === 'ok' ? 'Карточка прочитана.' : 'Страница не прочитана. Проверь вкладку товара.'});
      }
    }
  } catch (error) {
    await chrome.storage.local.set({state:error.message});
  } finally { running = false; }
}

chrome.alarms.onAlarm.addListener(() => { if (!running) void cleanTabs().then(pump); });
chrome.runtime.onStartup.addListener(() => { void pump(); });
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({enabled:false, state:'Нажми «Включить» после остановки старого читателя.'});
});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || !['start','stop'].includes(message.action)) return;
  (async () => {
    const enabled = message.action === 'start';
    await chrome.storage.local.set({enabled, state:enabled ? 'Подключаюсь…' : 'Остановлено.'});
    if (enabled) void pump();
    else { await cleanTabs(true); await api('/disconnect', 'POST'); }
    respond({ok:true});
  })().catch(() => respond({ok:false}));
  return true;
});
// Alarms survive suspension and restart polling if a fetch fails.
void chrome.alarms.create('relay', {periodInMinutes:0.5});
void pump();
