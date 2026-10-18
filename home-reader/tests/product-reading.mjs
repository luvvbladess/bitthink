import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {chromium} from 'file:///E:/progs/BitClient/node_modules/@playwright/test/index.mjs';
const source=fs.readFileSync('home-reader/extension/worker.js','utf8').split('async function api(')[0];
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
 const fullSource=fs.readFileSync('home-reader/extension/worker.js','utf8');
 const session={},called=[],removed=[];
 const event=()=>({addListener(){}});
 const ozon='https://www.ozon.ru/product/model-123/';
 const chrome={runtime:{onStartup:event(),onInstalled:event(),onMessage:event(),getManifest:()=>({version:'1.9.2'})},alarms:{onAlarm:event(),create(){}},
 storage:{local:{get:async()=>({enabled:false})},session:{get:async()=>session,set:async v=>Object.assign(session,v)}},
 tabs:{create:async()=>({id:1,url:ozon,status:'complete'}),get:async()=>({id:1,url:ozon,status:'complete'}),remove:async id=>removed.push(id)},
 scripting:{executeScript:async request=>{called.push(request.func.name);return [{result:{status:'ok',url:ozon,text:'Цена 1500 ₽. Есть в наличии. Рейтинг 4.8.'}}]}}};
 const ctx=vm.createContext({chrome,URL,AbortSignal,setTimeout:fn=>{queueMicrotask(fn)},console});
 vm.runInContext(fullSource,ctx);
 const overview=await vm.runInContext('readJob({url:'+JSON.stringify(ozon)+',mode:"overview"})',ctx);
 assert.equal(overview.review_diagnostics.stage,'not_requested');assert.deepEqual(called,['readProduct']);assert.deepEqual(removed,[1]);
 let activeId=90, userSwitched=false;const updates=[];
 chrome.tabs.create=async()=>({id:1,url:ozon,status:'complete',windowId:1});
 chrome.tabs.query=async()=>[{id:activeId}];
 chrome.tabs.get=async id=>({id,url:ozon,status:'complete',windowId:1,active:id===activeId});
 chrome.tabs.update=async(id,props)=>{if(props.active)activeId=id;updates.push(id);return {id,url:ozon,status:'complete',windowId:1,active:id===activeId}};
 chrome.scripting.executeScript=async request=>{
  if(request.func.name==='readProduct' && request.args[1]==='отзывы') {
   if(userSwitched)activeId=91;
   return [{result:{status:'ok',url:ozon,text:'ТЕКСТЫ ОТЗЫВОВ: хороший звук.',review_diagnostics:{count:1,source:'dom'}}}];
  }
  return [{result:{status:'ok',url:ozon,text:'Цена 1500 ₽. Есть в наличии. Рейтинг 4.8.'}}];
 };
 await vm.runInContext('readJob({url:'+JSON.stringify(ozon)+',mode:"full"})',ctx);
 assert.deepEqual(updates,[1,90]);assert.equal(activeId,90);
 updates.length=0;userSwitched=true;
 await vm.runInContext('readJob({url:'+JSON.stringify(ozon)+',mode:"full"})',ctx);
 assert.deepEqual(updates,[1]);assert.equal(activeId,91);
 assert.equal(vm.runInContext('sameProduct("https://www.ozon.ru/product/model-123/","https://www.ozon.ru/product/other-999/")',ctx),false);
 assert.equal(vm.runInContext('sameProduct("https://www.chipdip.ru/product/stm32f103c8t6","https://www.chipdip.ru/product/stm32f103c8t6-mikrokontroller-9000099899")',ctx),true);
 const page=await browser.newPage();
 await page.route('**/*',route=>route.fulfill({status:200,contentType:'text/html',body:'<title>Товар</title><main></main>'}));
 async function read(url,html,section='overview') {
  await page.goto(url);await page.setContent('<style>[data-auto="review-item"] {white-space:pre-wrap}</style>'+html);await page.addScriptTag({content:source});
  return page.evaluate(({url,section})=>readProduct(url,section,readerProfile(url)),{url,section});
 }
 const wb='https://www.wildberries.ru/catalog/123/detail.aspx';
 let r=await read(wb,'<title>Wildberries</title><main><a href="/catalog/999/detail.aspx">Другой товар 1200 ₽</a></main>');
 assert.equal(r.status,'error');assert.equal(r.error_code,'product_not_confirmed');
 r=await read(wb,'<title>Wildberries</title><main><h1>По Вашему запросу ничего не найдено</h1>Перейти в каталог</main>');
 assert.equal(r.status,'error');assert.match(r.text,/#PAGE_NOT_FOUND#/);
 const ym='https://market.yandex.ru/card/model/123';
 r=await read(ym,'<title>Model</title><main><h1>Беспроводная компьютерная гарнитура Logitech G435</h1>Товар распродан<div data-zone-name="snippet"><span data-auto="rating-value">4.9</span>Ещё может подойти Другой товар 1200 ₽</div></main>');
 assert.equal(r.status,'ok');assert.doesNotMatch(r.text,/1200|4\.9/);assert.match(r.text,/распродан/);
 r=await read(ym,'<main><h1>Model</h1><div><span data-auto="rating-value">4.7</span>Цена 1500 ₽</div><div data-auto="product-card"><span data-auto="rating-value">1.1</span>Другой товар 99999 ₽</div></main>');
 assert.match(r.text,/4\.7|1500/);assert.doesNotMatch(r.text,/1\.1|99999/);
 const oz='https://www.ozon.ru/product/model-123/';
 const state={reviews:Array.from({length:30},(_,i)=>({content:{comment:'Покупатель '+i+' сообщает о хорошем звуке и качестве сборки.'}}))};
 r=await read(oz,'<main><h1>Model</h1><div id="state-webListReviews-1" data-state="'+JSON.stringify(state).replaceAll('"','&quot;')+'"></div></main>','отзывы');
 assert.equal(r.review_diagnostics.source,'widget_state');assert.equal(r.review_diagnostics.count,20);assert.doesNotMatch(r.text,/Покупатель 20/);
 const revealSource=fullSource.slice(fullSource.indexOf('async function revealSections('),fullSource.indexOf('async function readJob('));
 await read(oz,'<main><h1>Model</h1><div data-widget="webReviewProductScore" style="display:contents"><span id="score">4.9 • 3318 отзывов</span></div></main>');
 await page.addScriptTag({content:revealSource});
 await page.evaluate(()=>document.getElementById('score').addEventListener('click',()=>{
  const panel=document.createElement('div');panel.dataset.widget='webListReviews';panel.innerHTML='<div data-widget="webReview">Комментарий: Отличный звук и надёжная сборка.</div>';document.querySelector('main').append(panel);
 }));
 const clicked=await page.evaluate(url=>revealSections(url,'отзывы',readerProfile(url)),oz);
 assert.equal(clicked.control,'span');assert.match(clicked.click_caption,/3318/);
 r=await page.evaluate(url=>readProduct(url,'отзывы',readerProfile(url)),oz);assert.equal(r.review_diagnostics.count,1);
 r=await read(ym,'<main><h1>Model</h1><div data-auto="review-item">Имя скрыто\n26 сентября\nОтветить\n0\nЦвет товара: синий</div><div data-auto="review-item">Иван\n26 сентября\nКомментарий: Хороший звук\nОтвет продавца\nКупите другой товар</div></main>','отзывы');
 assert.equal(r.review_diagnostics.count,1);assert.match(r.text,/Хороший звук/);assert.doesNotMatch(r.text,/Купите другой/);
 r=await read(ym,'<main><h1>Model</h1><div data-auto="review-item">Иван\n26 сентября\nКомментарий: Хороший звук\nЦвет товара: синий\nВерсия: для других стран</div></main>','отзывы');
 assert.match(r.text,/Вариант: Цвет товара: синий; Версия: для других стран/);
 const cards=Array.from({length:20},(_,i)=>'<div data-auto="review-item">Иван\n26 сентября\nКомментарий: Отзыв '+i+' '+('Хороший звук. '.repeat(60))+'</div>').join('');
 r=await read(ym,'<main><h1>Model</h1>'+cards+'</main>','отзывы');
 const count=[...r.text.matchAll(/^\d+\. /gm)].length;
 assert.equal(count,r.review_diagnostics.count);assert.ok(r.text.length<7500);assert.match(r.text,/\[сокращено\]$/);
 console.log('PASS overview skips sections and closes owned tab; product identity; missing card, recommendation exclusion, Ozon public widget state, empty feedback/seller reply exclusion, accurate whole-entry review budget');
} finally {await browser.close();}
