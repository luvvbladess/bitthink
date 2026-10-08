# Home marketplace reader

The Windows computer polls `https://bit-think.space/api/marketplace-relay/jobs`
over verified HTTPS using a dedicated bearer token. The backend enqueues only
HTTPS links to supported Russian marketplaces. The agent renders the page in a
separate persistent Chrome/Edge profile and returns visible text plus product
JSON-LD (offers, ratings, reviews). It never invokes OpenAI or accesses the
personal browser profile. Existing VPN and server routing are unchanged.

The backend uses home results before its existing RU proxy and search fallbacks.
An offline agent is skipped immediately. Jobs have a 60-second expiry and a
bounded queue. Only authenticated agents can poll or submit results; there is no
public URL-submission endpoint. Oversized results and non-marketplace result
URLs are rejected. The worker is limited to two simultaneous pages; navigation
is allowlisted and private/local network resources are blocked. CAPTCHAs are
reported as blocked results, with a bounded set of browser tabs retained for
manual completion. No buying, authentication, or CAPTCHA interaction is automated.

Production currently runs one Uvicorn worker, as required by the in-process
queue. A deployment/restart drops outstanding jobs; callers time out and fall
back. A multi-worker deployment would require moving the queue into a shared
store. Home availability depends on internet access and an interactive Windows
login; autostart runs when the installing Windows user signs in.

## Windows installation

The private ZIP contains `INSTALL.exe`, `config.json`, `START.bat`, `STOP.bat`,
`STATUS.bat`, `UNINSTALL.bat`, and instructions. Fully extract the archive on the
Smart Telecom computer and launch `INSTALL.exe` as a normal user. Python and
dependencies are bundled. Chrome/Edge is used if available; otherwise a separate
Chromium is downloaded. The EXE installs under `%LOCALAPPDATA%/BitThinkHomeReader`,
protects the folder with per-user ACLs and creates one HKCU Run autostart entry.
It opens no listening ports and makes no router/firewall/VPN changes. Uninstall
stops the worker and removes that entry while retaining the dedicated profile
and logs. Marketplace traffic must leave through Smart Telecom directly.

The archive is private because it contains `HOME_RELAY_TOKEN`. It must not be
committed, served publicly, or included in site deployment archives. The token
is also in the server `.env`. Rotate it in both places if exposed. It grants
only the home-reader protocol, not account access or model API access.

## Build and validation

Source is under `home-reader/`. Use an isolated Windows Python environment with
the requirements there and PyInstaller. Build `agent.py` with `--onefile`,
`--collect-all playwright`, `--hidden-import windows_setup`, and the home-reader
source directory on the analysis path. Stage output under ignored `tmp/`, then
package the EXE, per-installation config and helper files. No global execution
policy changes or administrator rights are needed.

Test the queue lifecycle, timeout/offline behavior, authentication, payload
limits and scraper integration with `backend/tests/test_marketplace_relay.py`.
An actual Smart Telecom product-page test is required after installing on the
home computer; a successful deployment or synthetic protocol test is not proof
that a marketplace permits that home connection.

Validation on 2026-10-06: 59 relevant backend tests passed locally and inside
production with a temporary SQLite database. The Windows browser smoke verified
JavaScript hydration, product JSON-LD, CAPTCHA detection/manual recovery and URL
guards using offline fixtures. The frozen EXE was separately started with an
invalid test credential: its bundled Playwright driver launched Chrome, verified
HTTPS, received the expected authentication rejection and stopped gracefully.
The private archive credential was verified against the deployed HTTPS endpoint.
The home reader was offline at delivery, since installation on the Smart Telecom
computer is still required. Existing Nginx/Xray hashes and process IDs, Compose
files and all other container IDs remained unchanged after backend deployment.
The final launcher was also tested in an isolated temporary LocalAppData folder:
the starter process exited while the detached EXE continued to launch its
browser and reach the HTTPS API; the stop flag then released the worker lock.
No real Windows autostart entry or home-reader installation was created on the
development computer. The final private ZIP passed integrity/contents checks.

## Ordinary browser extension

On 2026-10-06 the user confirmed that Ozon opens in ordinary Chrome on the home
PC, while the Playwright reader receives a block. An alternative reader is under
`home-reader/extension/`: an MV3 extension loaded manually into that ordinary
Chrome/Edge browser. It uses the same authenticated relay and requires no server
or VPN changes. Stop and uninstall the EXE reader before enabling the extension:
running both with the same relay credential would distribute jobs between them.
The source config has an empty token; private packages receive the existing
credential only under ignored `tmp/`. Never commit the packaged config.

Only extension-created product tabs are read, with explicit domain/path guards.
The extension collects visible product text and Product JSON-LD and opens known
description/specification/review controls. Reviews on separate pages or custom
widgets are not guaranteed. No cookies, form values, purchases or authentication
actions are collected or performed. Successful/error tabs close immediately;
at most three blocked tabs are retained for manual verification, with a five
minute expiry checked during polling or by the 30-second alarm. Disable closes
all tracked tabs. Session storage preserves ownership across worker suspension.

Synthetic tests cover authenticated delivery, product URL guards, private
redirects, blocked-tab expiry, JSON-LD review/offer extraction and text limits.
A real isolated Chromium extension smoke tests the MV3 worker, scripting API,
description/specification/review controls, tab closure and popup. These fixtures
do not prove that the real marketplace will permit requests from the extension;
the user must verify this on the Smart Telecom PC after installation.

## Kimi employee routing audit

Kimi's `browse_page` now sends Russian shop URLs through the shared
`fetch_url_content` reader first, so a nonempty external fetch response cannot
bypass the home browser. Other sites keep Kimi's original fetch-first path;
challenge text is rejected there and in the scraper's Kimi recovery fallback.
Whitespace normalization catches the nonbreaking spaces in Ozon's block page.
Successful home reads and fallback statuses are logged as `marketplace_read`
events under `uvicorn.error.marketplace_reader`, including hostname, public path
and text length without query strings, credentials or page content. A replayed
real user request can therefore be distinguished from search-only evidence.
The fix passed 35 focused tests, including Kimi tool -> relay job -> home result.


### Обязательная проверка предложений в режиме «Оркестратор»

Перед составлением ответа по задаче покупки сервер независимо от решения поисковой модели запускает `marketplace_verification.verify_marketplace_cards`. Он берёт реальные URL из запроса и результатов поиска, при необходимости читает до двух подборок для извлечения ссылок, Заголовки, URL и фрагменты источников сначала оцениваются на соответствие типу товара, параметрам, бюджету и заданным магазинам. Затем читатель открывает первую группу до четырёх карточек. При недостатке подходящих предложений проверяются следующие кандидаты или выполняется до двух уточняющих поисков. Максимум — восемь карточек; бюджет обхода — 240 секунд, отдельные вызовы оценки ограничены 30 секундами. Это ограниченная проверка кандидатов, не полный обход всех магазинов или BOM.

Результаты чтения передаются составителю без обычной обрезки заметок до 3000 символов; снимок карточки ограничен 10800 символами. Оценка suitable/reject/unknown передаётся отдельно вместе с дословными цитатами; цитаты проверяются на присутствие в прочитанном тексте. Для suitable обязательны подтверждения типа товара, цены и продавца, а для топа или выбора по отзывам — также рейтинга и числа отзывов. Успешное чтение не подтверждает отсутствующие поля, остаток в корзине или цену для другого региона. Поисковые сниппеты не заменяют чтение. При отключённом читателе явно отмечается, что обращения к нему не было. Статус и время каждого проверенного URL сохраняются в источниках, события `marketplace_verify` — в серверном журнале.

Для уточняющего поиска используются Kimi Search Pro и резервный OpenAI web search: пустой ответ или сбой Kimi не завершает подбор. Поисковые результаты проходят повторный отбор перед реальным чтением.


### Проверенные форматы коротких ссылок

Расширение 1.5 поддерживает Ozon `/t/<code>`, Яндекс Маркет `/cc/<code>` и AliExpress Россия `https://sl.aliexpress.ru/p?key=<code>` (значение key сохраняется). Проверены реальные ответы: Яндекс 302 на `/card/...`, AliExpress 303 на `/item/...html`. Формат Яндекса описан в https://yandex.ru/dev/market/affiliate/ru/reference/get-partner-link-create . Примеры AliExpress также встречаются в первичных материалах ФИПС https://www.fips.ru/pps/06_10_25/2025%D0%9200985.pdf .

Промежуточная страница сокращателя не извлекается. Читается только конечная публичная карточка на исходной площадке. Корзины/списки/посторонние домены отклоняются. Wildberries `/catalog/<id>/detail.aspx`, в том числе с параметром targetUrl, уже поддерживается. Отдельные дополнительные короткие форматы WB, Мегамаркета и Lamoda не подтверждены и не добавляются по предположению.

### Извлечение отзывов 1.6

Читатель распознаёт role=button, отдельные отзывы data-review-uuid, виджет Ozon webListReviews и подписанные блоки достоинств/недостатков/комментариев. Переход на /reviews/ разрешён только в пределах того же товара Ozon и origin; после смены документа сценарий продолжается. Ожидание видимых отзывов ограничено тремя секундами, пагинация не используется. Текстам отзывов выделено до 3800 символов в снимке размером до 10800; рейтинг без текстов явно отмечается как отсутствие извлечённых отзывов. Журнал marketplace_read содержит review_texts=present/not_extracted/unknown (unknown для старого расширения). Проверено на Chromium fixtures с отложенной загрузкой и 25 отзывами: извлечено не более 20, тексты дошли до результата. Реальное чтение этих трёх карточек после исправления требует обновления расширения на домашнем ПК.

### Площадки и отзывы 1.7

Профили readerProfile задают селекторы отзывов, контейнеров, рейтинга и элементов открытия раздела для Ozon, WB, Яндекс Маркета, AliExpress RU, DNS, Ситилинка, М.Видео, Эльдорадо, Мегамаркета и Lamoda. У Авито область отзыва/рейтинга — продавец. Прочие магазины используют стандартную разметку и Product JSON-LD. Переходы допускаются только в пределах того же origin и точного пути выбранного товара; служебные параметры раздела ограничены. В WB /catalog/<id>/feedbacks нормализуется к /catalog/<id>/detail.aspx. Несколько DOM-узлов одного отзыва не считаются разными отзывами. Рейтинг и число оценок извлекаются отдельно перед длинными описаниями, скрытые отзывы и блоки рекомендаций пропускаются. Явное сообщение об отсутствии отзывов отличается от ошибки извлечения.

Проверено на Chromium fixtures для девяти площадок: переходы на feedbacks/reviews/opinion/otzyvy и вкладку tab=reviews, отложенная загрузка, рейтинг вне main, ограничение 20 при 25 загруженных отзывах. Это проверка сценария и поддержанной разметки, а не гарантия текущей разметки всех живых карточек. На домашнем ПК требуется расширение 1.7.0 и проверка реальных товаров после установки. Серверный журнал различает present, not_extracted, none, unknown.

### Получение реальных текстов 1.8

В Ozon исправлена поддержка ?tab=reviews, которую 1.7 могла отклонить при проверке перехода. Если обычное открытие не даёт текста, выполняется один переход к публичному разделу того же товара. Пагинации нет. Внутри панели отзывов допускаются повторяющиеся DOM-блоки с генерируемыми классами и reviewBody/content.positive/content.negative/content.comment из ограниченного data-state самого виджета. Полное состояние приложения и аккаунта не читается. Версия и диагностика извлечения передаются в Result и heartbeat.

Защищённые токеном /api/marketplace-relay/inspect и /diagnostics позволяют проверить карточку и последние метаданные чтения. Inspect принимает только поддержанную публичную карточку/короткую ссылку; diagnostics не хранит тексты страницы. Код ограничивает очередь и срок 60 сек как прежде. На Chromium fixture проверен сценарий: карточка со счётчиком без работающей кнопки -> tab=reviews -> 20 из 25 отзывов с генерируемой разметкой или widget_state. Реальный статус этой задачи нужно подтвердить после установки 1.8 на домашнем компьютере; результаты fixtures не являются проверкой живого Ozon.

### Проверка магазинных ссылок 1.9

Перед финальным ответом Оркестратора guard_answer_links оставляет только URL карточек с успешной live_verification текущего запроса. Непроверенные Markdown-ссылки, обычные URL и автоссылки исключаются, короткие адреса заменяются подтверждённым конечным адресом. URL из одних поисковых источников не считаются проверенными. Отклонённый адрес не заменяется произвольным другим товаром. Проверка missing-page на сервере и в расширении отличает явные 404/удаление от отсутствия товара в наличии; ошибки 5xx не подтверждают открытие карточки. Редирект на другую карточку уже отклоняется по идентичности URL. Эта проверка относится к рекомендациям Оркестратора и моменту выполнения запроса, не гарантирует будущую доступность. Клиенту 1.9 нужна установка на домашнем ПК, серверная защита работает и с предыдущим читателем по возвращённому тексту/заголовку.
