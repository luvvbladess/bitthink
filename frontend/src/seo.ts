export const SITE_URL = 'https://bit-think.space';
export const SITE_NAME = 'Bit-Think';
export const SITE_ALTERNATE_NAME = 'Bit Think';
export const SITE_ALTERNATE_NAMES = [
  'Bit Think',
  'BitThink',
  'бит синк',
  'бит-синк',
  'битсинк',
  'бит think',
] as const;

export const SITE_TITLE = 'Bit-Think – ИИ-чат с поиском и документами';
/** Without the brand: messengers already prepend og:site_name. */
export const SITE_OG_TITLE = 'ИИ-чат с поиском, файлами и Студией';
export const SITE_DESCRIPTION =
  'Нейросеть в браузере: ответы с источниками, PDF и таблицы, слайды и картинки. Один чат, без установки.';
export const SITE_KEYWORDS =
  'Bit-Think, Bit Think, бит синк, ИИ-чат, нейросеть, поиск с источниками, Perplexity, документы, презентации';

export type FaqItem = { q: string; a: string };

export const SITE_FAQ: FaqItem[] = [
  {
    q: 'Что такое Bit-Think?',
    a: 'Bit-Think – ИИ-ассистент в браузере. Задаёте вопрос и получаете ответ с источниками, прикладываете документы, собираете слайды в Студии и генерируете картинки в том же чате.',
  },
  {
    q: 'Bit-Think – это как Perplexity?',
    a: 'По задаче близко: вопрос, ответ и ссылки. Плюс файлы, картинки и Студия для презентаций, с упором на работу на русском.',
  },
  {
    q: 'Что умеет Студия?',
    a: 'Слайды, инфографика и макеты по брифу или файлу. Готовую презентацию можно править следующим сообщением и скачать.',
  },
  {
    q: 'Bit-Think бесплатный?',
    a: 'Зарегистрироваться и открыть чат можно сразу. Расширенные лимиты, Пилот и Студия – на тарифах Pro, Pro+ и Ultra.',
  },
  {
    q: 'Как ещё ищут Bit-Think?',
    a: 'Вслух и в поиске часто пишут Bit Think или бит синк. Это тот же сервис, сайт bit-think.space.',
  },
];

export type PageMeta = {
  title: string;
  description?: string;
  ogTitle?: string;
  canonicalPath?: string;
  noindex?: boolean;
  ogType?: string;
};

function upsertMeta(attr: 'name' | 'property', key: string, content: string) {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`) as HTMLMetaElement | null;
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.content = content;
}

function upsertLink(rel: string, href: string) {
  let el = document.head.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement | null;
  if (!el) {
    el = document.createElement('link');
    el.rel = rel;
    document.head.appendChild(el);
  }
  el.href = href;
}

export function applyPageMeta({
  title,
  description = SITE_DESCRIPTION,
  ogTitle,
  canonicalPath = '/',
  noindex = false,
  ogType = 'website',
}: PageMeta) {
  const shareTitle = ogTitle || title;
  document.title = title;
  upsertMeta('name', 'description', description);
  upsertMeta('name', 'keywords', SITE_KEYWORDS);
  upsertMeta('name', 'application-name', SITE_NAME);
  upsertMeta('name', 'robots', noindex ? 'noindex, nofollow' : 'index, follow, max-image-preview:large, max-snippet:-1');
  upsertLink('canonical', `${SITE_URL}${canonicalPath}`);

  upsertMeta('property', 'og:type', ogType);
  upsertMeta('property', 'og:site_name', SITE_NAME);
  upsertMeta('property', 'og:locale', 'ru_RU');
  upsertMeta('property', 'og:url', `${SITE_URL}${canonicalPath}`);
  upsertMeta('property', 'og:title', shareTitle);
  upsertMeta('property', 'og:description', description);
  upsertMeta('property', 'og:image', `${SITE_URL}/og-image.png`);
  upsertMeta('property', 'og:image:width', '1200');
  upsertMeta('property', 'og:image:height', '630');
  upsertMeta('property', 'og:image:alt', 'Bit-Think – ИИ-чат в браузере');

  upsertMeta('name', 'twitter:card', 'summary_large_image');
  upsertMeta('name', 'twitter:title', shareTitle);
  upsertMeta('name', 'twitter:description', description);
  upsertMeta('name', 'twitter:image', `${SITE_URL}/og-image.png`);
}
