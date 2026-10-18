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

function sameProduct(source,destination) {
  try {
    const a=new URL(source),b=new URL(destination);
    if(a.hostname.replace(/^www\./,'')!==b.hostname.replace(/^www\./,'') || !productUrl(destination))return false;
    if(/chipdip\.ru$/.test(a.hostname) && /^\/product\/[^/]+\/?$/.test(a.pathname)) {
      const original=a.pathname.replace(/\/$/,'');
      if(b.pathname.replace(/\/$/,'').startsWith(original+'-'))return true;
    }
    const identity=u=>{
      if(/ozon\.ru$/.test(u.hostname))return u.pathname.match(/^\/product\/(?:.*-)?(\d+)\/?/)?.[1] || u.pathname.split('/')[2];
      if(/wildberries\.ru$|wb\.ru$/.test(u.hostname))return u.pathname.match(/^\/catalog\/(\d+)\//)?.[1];
      if(u.hostname==='market.yandex.ru')return u.pathname.replace(/\/reviews\/?$/,'').split('/').filter(Boolean).at(-1);
      if(/dns-shop\.ru$/.test(u.hostname))return u.pathname.match(/^\/product\/(?:(?:opinion|characteristics)\/)?([^/]+)/)?.[1];
      return u.pathname.replace(/\/(reviews|opinion|otzyvy)\/?$/,'').replace(/\/$/,'');
    };
    return identity(a)===identity(b);
  } catch {return false;}
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
    add('Ozon','[data-widget="webReview"], [id^="state-webReview-"]','[data-widget="webListReviews"], [data-widget="webSingleProductReview"], [data-widget="webReviews"], [data-widget="pinnedReview"], [id^="state-webListReviews-"], [id^="state-webSingleProductReview-"]','[data-widget*="ReviewProductScore"]','[data-widget="webReviewProductScore"], [data-widget="pinnedReview"], [data-widget="webReviewProductScore"] span, a[href*="tab=reviews"], a[href*="#section-reviews"], a[href*="/reviews/"]');
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
    const card=path.replace(/^\/product\/(?:opinion|characteristics)\//,'/product/').replace(/\/opinion$/,'');
    common.reviewPaths=[card+'/opinion',card.replace('/product/','/product/opinion/')];
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
  const recommendationSelector='[data-zone-name="Recommendations"], [data-zone-name="snippet"], [data-zone-name="productSnippet"], [data-auto="product-snippet"], [data-auto="product-card"], .recommendations, .product-card, [data-testid="recommendations"], [data-widget*="Reco"], [data-widget="webSimilarProducts"]';
  const heading=document.querySelector('h1, [role="heading"][aria-level="1"]');
  const isRecommendation=el=>{
    const block=el.closest?.(recommendationSelector);
    return Boolean(block && !block.contains?.(heading));
  };
  const buyerText=raw=>{
    let s=String(raw || '').trim();
    s=s.split(/\n\s*(?:Ответ продавца|Ответ магазина)\s*\n/i)[0];
    let lines=s.split('\n').map(v=>v.trim()).filter(Boolean);
    const variants=lines.filter(v=>/^(?:Цвет товара|Версия|Разъем штекера):/i.test(v) || /·.*\d+\s*(?:мл|л|см|мм|гб|gb|шт)(?:\s|$)/i.test(v)).slice(0,3).map(v=>v.slice(0,100));
    const date=lines.findIndex(v=>/^(?:\d{1,2} [а-я]+(?: \d{4})?|Вчера|Сегодня)(?:[, ·].*)?$/i.test(v));
    if(date>=0) lines=lines.slice(date+1);
    const useful=lines.filter(v=>!(/^(?:Ответить|Показать(?: \d+)? ответ[а-я]*|Показать ещ[её]|ещ[её]|Выкупили|Отказались|Имя скрыто|Покупатель|Первоначальный отзыв|\d+|(?:Цвет товара|Версия|Разъем штекера):.*)$/i.test(v) || /^(?:\d{1,2} [а-я]+|Вчера|Сегодня)(?:[, ·].*)?$/i.test(v)));
    // A named/date-only card or a variant selector is not buyer feedback.
    const body=useful.join('\n');
    if(body.length<5 || !/[а-яa-z]{3}/i.test(body)) return '';
    const metadata=variants.length ? '\nВариант: '+variants.join('; ') : '';
    const limit=600-metadata.length;
    return (body.length>limit ? body.slice(0,limit-13)+' [сокращено]' : body)+metadata;
  };
  let sampleSource='dom';
  const reviewCards=profile.cards || '[itemprop="review"], [data-review-id], [data-review-uuid], [data-widget="webReview"], [data-testid="review"], [class*="review-text"], [class*="reviewText"]';
  const reviewContainers=profile.containers || '[data-widget="webListReviews"], [data-widget="webSingleProductReview"], #section-reviews, #reviews';
function reviewSample() {
  const nodes=[...document.querySelectorAll(reviewCards)].filter(el=>
    (!el.getClientRects || el.getClientRects().length) && !isRecommendation(el));
  // A body and its containing review card may both match. Keep one per review.
  const samples=nodes.filter(el=>!nodes.some(other=>other!==el && other.contains?.(el))).map(el=>buyerText(el.innerText)).filter(Boolean);
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
            const parts=[node.reviewBody,(content?.positive || node.positive)?('Достоинства: '+(content?.positive || node.positive)):'',(content?.negative || node.negative)?('Недостатки: '+(content?.negative || node.negative)):'',(content?.comment || node.comment)?('Комментарий: '+(content?.comment || node.comment)):''].filter(v=>typeof v==='string' && v.trim());
            if(parts.length) {samples.push(parts.join('\n'));return;}
            for(const child of (Array.isArray(node)?node.slice(0,20):Object.values(node))) visit(child,depth+1);
          };
          visit(value);if(samples.length) sampleSource='widget_state';
        } catch {}
      }
    }
  }
  return [...new Set(samples.map(buyerText).filter(Boolean))].slice(0,20);
}

  if (expectedUrl && location.href !== expectedUrl) return {status:'error',url:location.href,text:'',title:''};
  const root = document.querySelector('main, [role="main"]') || document.body;
  const extra = [...document.querySelectorAll('[role="dialog"], [role="tabpanel"]')].filter(el => !root?.contains(el)).map(el => el.innerText || '').join('\n');
  let text = (root?.innerText || '') + '\n' + extra;
  for(const block of document.querySelectorAll(recommendationSelector)) {
    if(!block.contains?.(heading) && block.innerText) text=text.split(block.innerText).join('');
  }
  // Sold-out Yandex cards can be followed entirely by unrelated offers.
  if(profile.name==='Яндекс Маркет' && /Товар распродан|Нет в продаже/i.test(text)) text=text.split(/Ещ[её] может подойти|Похожие товары|Рекомендуем также/)[0];
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
  if(/^(?:по вашему запросу ничего не найдено|ничего не нашлось|товар не найден|такого товара нет)\s*$/im.test(text)) return {status:'error',url:location.href,title,text:'#PAGE_NOT_FOUND# Магазин сообщает, что товар или страница не найдены.'};
  if(/^(?:500|502|503|504|service unavailable|bad gateway|internal server error)$/i.test(title.trim()) || /^(?:внутренняя ошибка сервера|service unavailable|bad gateway|internal server error)$/i.test(pageHeading)) return {status:'error',url:location.href,title,text:'#PAGE_UNAVAILABLE# Ошибка сервера магазина.'};
  // DNS can return only its Qrator script, without a heading or visible text.
  // Keep that owned tab for the browser's normal challenge instead of closing
  // and restarting the challenge on every attempt.
  const scriptChallenge = text.trim().length < 800 && [...document.querySelectorAll('script[src]')].some(s => /\/__qrator\/|\/cdn-cgi\/challenge-platform\//i.test(s.getAttribute?.('src') || ''));
  const wall = scriptChallenge || text.length < 3000 && /похоже, нет соединения|вы не робот|проверяем браузер|подозрительная активность|доступ ограничен|доступ к.{0,40}сервису временно запрещ[её]н|captcha|access denied|verify you are human/i.test(text.replace(/\s+/g, ' '));
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
      // JSON-LD may also describe recommendation cards. Match the main title.
      const normalize=s=>String(s || '').toLowerCase().replace(/[^а-яa-z0-9]/g,'');
      if(!pageHeading || normalize(item.name)===normalize(pageHeading)) facts.push(JSON.stringify(product));
    }
    Object.values(item).forEach(visit);
  };
  for (const script of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0, 10)) {
    try { visit(JSON.parse(script.textContent.slice(0, 80000))); } catch {}
  }
  const body = (facts.length ? 'Данные товара (JSON-LD):\n' + facts.join('\n') + '\n\n' : '') + text.trim();
  const reviewPage=/\/(reviews|feedbacks|opinion|otzyvy)\/?$/.test(location.pathname || new URL(location.href).pathname) || /\/product\/opinion\//.test(location.href) || new URL(location.href).searchParams.get('tab')==='reviews';
  if(!wall && profile.name && ['Ozon','Wildberries','Яндекс Маркет','DNS'].includes(profile.name) && !facts.length && !pageHeading && !reviewPage) return {status:'error',url:location.href,title,text:'#PRODUCT_NOT_CONFIRMED# Карточка нужного товара не найдена или ещё не загрузилась. Подборка не подтверждает цену и наличие.',error_code:'product_not_confirmed'};
  if (section === 'отзывы' && !wall) {
    const samples = reviewSample();
    let source=samples.length?sampleSource:'none';
    for (const raw of facts) {
      if (samples.length) break;
      try {
        const p = JSON.parse(raw);
        for (const review of [].concat(p.review || []).slice(0,20)) {
          const value=buyerText(review.reviewBody || review.description);
          if (value) {samples.push(value);source='jsonld';}
        }
      } catch {}
    }
    if (samples.length) {
      const selected=[];let used=0;
      for(const s of samples.slice(0,20)) {if(used+s.length+10>7200)break;selected.push(s);used+=s.length+10;}
      return {status:'ok',url:location.href,title,review_diagnostics:{source,count:selected.length,dom_nodes:document.querySelectorAll(reviewCards).length,containers:document.querySelectorAll(reviewContainers).length},
        text:'ТЕКСТЫ ОТЗЫВОВ (не более 20; только видимая выборка; '+(profile.scope || 'товар')+'):\n'+selected.map((s,i)=>`${i+1}. ${s}`).join('\n\n')};
    }
    const emptyText=(text+'\n'+[...document.querySelectorAll(reviewContainers)].map(el=>el.innerText || '').join('\n')).replace(/\s+/g,' ');
    const noReviews=emptyText.match(/(?:отзывов (?:пока |ещ[её] )?нет|пока нет отзывов|нет отзывов|no reviews yet)/i);
    if(noReviews) return {status:'ok',url:location.href,title,review_diagnostics:{source:'none',count:0,stage:'empty'},text:'На странице прямо указано отсутствие отзывов: «'+noReviews[0]+'». Это не ошибка загрузки.'};
    return {status: body.length >= 50 ? 'ok' : 'error',url:location.href,title,
      review_diagnostics:{source:'none',count:0,stage:'not_extracted',containers:document.querySelectorAll(reviewContainers).length,dom_nodes:document.querySelectorAll(reviewCards).length,
        widgets:[...document.querySelectorAll('[data-widget]')].map(el=>el.getAttribute('data-widget')).filter(v=>/review|opinion/i.test(v)).slice(0,12).join(',').slice(0,400),
        controls_seen:[...document.querySelectorAll('a,button,[role="button"], [data-widget="webReviewProductScore"], [data-widget="pinnedReview"]')].map(el=>(el.innerText || '').replace(/\s+/g,' ').trim()).filter(v=>/отзыв/i.test(v) && v.length<160).slice(0,8).join(' | ').slice(0,600),
        path:new URL(location.href).pathname.slice(0,300)},
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
    if(isRecommendation(el)) continue;
    if(profile.name==='Яндекс Маркет' && /Товар распродан|Нет в продаже/i.test(text)) continue;
    const value=(el.innerText || el.getAttribute('content') || el.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim();
    if(value) widgets.push('Рейтинг/число оценок ('+(profile.scope || 'товар')+'): '+value.slice(0,500));
  }
  for(const el of [...document.querySelectorAll(selector)].slice(0,20)) {
    if(isRecommendation(el)) continue;
    if(profile.name==='Яндекс Маркет' && /Товар распродан|Нет в продаже/i.test(text)) continue;
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
      for(const key of [...u.searchParams.keys()]) if(/^(?:cpc|ogV|cc|sponsored|show-?uid|showUid|from-show-uid|utm_.+|track|sh|short|perehod|from|from_share|from_global|share_id|tracking)$/i.test(key)) u.searchParams.delete(key);
      const label=(a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim().slice(0,180);
      if(!cards.has(u.href)) cards.set(u.href,label || 'Карточка товара');
      if(cards.size>=24) break;
    } catch {}
  }
  const candidateLines=[];let candidateSize=0;
  for(const [url,label] of cards) {
    const line=label+' — '+url;
    if(candidateSize+line.length+1>1800)continue;
    candidateLines.push(line);candidateSize+=line.length+1;
  }
  const candidates=candidateLines.join('\n');
  return {status: wall ? 'blocked' : body.length >= 50 ? 'ok' : 'error', url: location.href,
    ...(wall ? {error_code:'browser_challenge'} : {}),
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
  let clicked='none', clickCaption='';
  const currentPage=new URL(location.href);
  const alreadyReviews=section==='отзывы' && (/\/(reviews|feedbacks|opinion|otzyvy)\/?$/.test(currentPage.pathname) || currentPage.searchParams.get('tab')==='reviews');
  for (const label of (alreadyReviews?[]:[labels[section]]).filter(Boolean)) {
    if (location.href !== expectedUrl) break;
    const candidates = [...document.querySelectorAll('button, [role="tab"], [role="button"], a'+(profile.controls ? ', '+profile.controls : ', [data-widget="webReviewProductScore"]'))];
    const control = candidates.find(el => {
      const caption=(el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g,' ').trim();
      const knownControl=section==='отзывы' && profile.controls && el.matches(profile.controls) && /отзыв/i.test(caption);
      const childVisible=knownControl && [...el.querySelectorAll('a,button,span')].some(child=>child.getClientRects().length && /отзыв/i.test(child.innerText || ''));
      if ((!label.test(caption) && !knownControl) || (!el.getClientRects().length && !childVisible)) return false;
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
      const child=[...control.querySelectorAll('a, button, [role="button"], span')].find(el=>(label.test((el.innerText || '').replace(/\s+/g,' ').trim()) || section==='отзывы' && /отзыв/i.test(el.innerText || '')) && el.getClientRects().length);
      let target=child || control;
      if(target.tagName==='A') {
        const dest=new URL(target.href,location.href),current=new URL(location.href);
        if(dest.origin!==current.origin || (dest.pathname!==current.pathname && !(profile.reviewPaths || []).includes(dest.pathname.replace(/\/$/,'')))) target=control;
      }
      target.scrollIntoView({block:'center'});clickCaption=(target.innerText || '').replace(/\s+/g,' ').slice(0,100); target.click();clicked=target.tagName.toLowerCase();await wait(1000);
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
  return {control:clicked,click_caption:clickCaption,dom_nodes:document.querySelectorAll(profile.cards || '[itemprop="review"], [data-review-id]').length};
}

async function readJob(job) {
  const version = chrome.runtime.getManifest?.().version || '1.9.4';
  const empty = {status:'error', url:job.url, text:'', title:'',reader_version:version,reader_source:'owned_tab',error_code:'empty_page'};
  if (!browseUrl(job.url)) return empty;
  // A DNS card already open in this browser is a better source than another
  // background tab. Read only that exact public card; never navigate, scroll,
  // click its sections, take ownership of it or close it.
  if (productUrl(job.url) && /(^|\.)dns-shop\.ru$/.test(new URL(job.url).hostname) && chrome.tabs.query) {
    const {owned=[]}=await chrome.storage.session.get('owned');
    const wanted=new URL(job.url);
    const tabs=await chrome.tabs.query({url:'https://*.dns-shop.ru/*'});
    const matches=tabs.filter(tab=>{
      if(owned.some(item=>item.id===tab.id) || !tab.url || !productUrl(tab.url)) return false;
      const u=new URL(tab.url);
      return u.origin===wanted.origin && u.pathname.replace(/\/$/,'')===wanted.pathname.replace(/\/$/,'') && u.search===wanted.search;
    }).sort((a,b)=>Number(Boolean(b.active))-Number(Boolean(a.active)));
    for(const tab of matches.slice(0,2)) try {
      const [read]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:readProduct,args:[tab.url,'overview',readerProfile(tab.url)]});
      const observed=read?.result?.url ? new URL(read.result.url) : null;
      if(read?.result?.status==='ok' && productUrl(read.result.url) && observed.origin===wanted.origin && observed.search===wanted.search && observed.pathname.replace(/\/$/,'')===wanted.pathname.replace(/\/$/,'')) {
        return {...read.result,reader_version:version,reader_source:'existing_tab',review_diagnostics:{stage:'not_extracted',source:'none',count:0},text:read.result.text.slice(0,10800)+'\n\nПрочитана уже открытая публичная карточка. Вкладка не изменялась. Тексты отзывов отдельно не открывались.'};
      }
    } catch {}
  }
  const {retained = []} = await chrome.storage.session.get('retained');
  let tab, keep = false, restoreActiveId = null;
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
      if(productUrl(job.url) && !sameProduct(job.url,tab.url)) return {...empty,error_code:'product_not_confirmed',text:'#PRODUCT_NOT_CONFIRMED# Ссылка перенаправила на другой товар или подборку.'};
      if (tab.status !== 'complete') continue;
      if (shortUrl(job.url)) {
        if (shortUrl(tab.url)) continue;
        if (!shortDestinationAllowed(job.url,tab.url)) return empty;
      }
      const [injected] = await chrome.scripting.executeScript({target:{tabId:tab.id}, func:readProduct, args:[tab.url,'overview',readerProfile(tab.url)]});
      const result = injected?.result;
      if (!result || !browseUrl(result.url)) continue;
      if(result.status==='error' && /^#PAGE_(NOT_FOUND|UNAVAILABLE)#/.test(result.text || '')) return {...result,reader_version:version,reader_source:'owned_tab'};
      if (result.status === 'ok' && (attempt >= 2 || job.mode==='overview')) {
        if(!productUrl(result.url)) return {...result,text:('Это подборка/поиск, не отдельное предложение. Не рекомендуй этот URL как товар. Открой найденные карточки и сравни их.\n\n'+result.text).slice(0,80000)};
        if(job.mode==='overview') return {...result,reader_version:version,reader_source:'owned_tab',review_diagnostics:{stage:'not_requested',source:'none',count:0},text:result.text.slice(0,5000)};
        // Ozon's public interactive review controls can remain unrendered in
        // a background tab. Activate only our own tab, then restore the former
        // active tab if the user has not switched to another tab meanwhile.
        if(/(^|\.)ozon\.ru$/.test(new URL(tab.url).hostname) && chrome.tabs.query && chrome.tabs.update && tab.windowId != null) try {
          const active=await chrome.tabs.query({active:true,windowId:tab.windowId});
          if(active[0] && active[0].id!==tab.id) {
            restoreActiveId=active[0].id;
            await chrome.tabs.update(tab.id,{active:true});await pause(500);
            tab=await chrome.tabs.get(tab.id);
          }
        } catch {}
        // Keep the initial description when a section replaces the main panel.
        const chunks = [result.text.slice(0,2800)];
        let reviews={stage:'not_extracted',source:'none',count:0,foreground_read:Boolean(restoreActiveId)};
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
          if (more?.result?.status === 'ok' && productUrl(more.result.url)) chunks.push(section.toUpperCase() + '\n' + (section === 'отзывы' ? more.result.text : more.result.text.slice(0,1950)));
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
                    const value='ОТЗЫВЫ\n'+sample.result.text;
                    if(old>=0)chunks[old]=value;else chunks.push(value);
                  }
                }
              }
            } catch {reviews.stage='section_retry_failed';}
          }
        }
        if(!chunks.some(chunk=>chunk.startsWith('ОТЗЫВЫ\n'))) chunks.push('ОТЗЫВЫ\nТексты отзывов не извлечены: раздел не удалось открыть или прочитать. Рейтинг и число оценок не заменяют тексты покупателей.');
        if(reviews.count) reviews.stage='read';
        return {...result, reader_version:version,reader_source:'owned_tab',review_diagnostics:reviews,text:[...new Set(chunks)].join('\n\n')};
      }
      if(attempt>=10 && result.error_code==='product_not_confirmed') return {...result,reader_version:version,reader_source:'owned_tab'};
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
        return {...result,reader_version:version,reader_source:'owned_tab',error_code:'browser_challenge',url:job.url,text:''};
      }
    }
    return {...empty,error_code:'navigation_timeout'};
  } finally {
    if(restoreActiveId!==null) try {
      const current=await chrome.tabs.get(tab.id);
      if(current.active) await chrome.tabs.update(restoreActiveId,{active:true});
    } catch {}
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
        try { result = await readJob(job); } catch { result = {status:'error', url:job.url, text:'', title:'',reader_version:chrome.runtime.getManifest?.().version || '1.9.1',reader_source:'owned_tab',error_code:'script_error'}; }
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
