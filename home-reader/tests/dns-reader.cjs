const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('home-reader/extension/worker.js','utf8');
const url='https://www.dns-shop.ru/product/abc/logitech-g435/';
const event=()=>({addListener(){}});
const session={}, calls={created:0,removed:0,scripts:0};
const chrome={runtime:{id:'test',getManifest:()=>({version:'1.9.1'}),onStartup:event(),onInstalled:event(),onMessage:event()},
 alarms:{onAlarm:event(),create(){}},
 storage:{local:{get:async()=>({enabled:false})},session:{get:async()=>({...session}),set:async v=>Object.assign(session,v)}},
 tabs:{query:async()=>[{id:99,url,active:true},{id:100,url:'https://www.dns-shop.ru/my/orders',active:true}],create:async()=>{calls.created++;throw Error('Must reuse the exact open card')},remove:async()=>{calls.removed++}},
 scripting:{executeScript:async request=>{calls.scripts++;assert.equal(request.target.tabId,99);assert.equal(request.func.name,'readProduct');return [{result:{status:'ok',url,title:'Logitech G435',text:'Цена 4499 ₽. Наличие в выбранном городе, характеристики товара.'}}]}}};
const ctx=vm.createContext({chrome,URL,AbortSignal,setTimeout,console});vm.runInContext(source,ctx);
(async()=>{
 const result=await vm.runInContext('readJob({url:'+JSON.stringify(url)+'})',ctx);
 assert.equal(result.reader_source,'existing_tab');assert.equal(result.reader_version,'1.9.1');assert.match(result.text,/4499/);
 assert.equal(calls.created,0);assert.equal(calls.removed,0);assert.equal(calls.scripts,1);assert.equal(session.owned,undefined);
 ctx.location={href:url};
 ctx.document={title:'',body:{innerText:''},querySelector:()=>null,querySelectorAll:s=>s==='script[src]'?[{getAttribute:()=>'/__qrator/qauth.js'}]:[]};
 const challenge=vm.runInContext('readProduct()',ctx);
 assert.equal(challenge.status,'blocked');assert.equal(challenge.error_code,'browser_challenge');assert.equal(challenge.text,'');
 ctx.document.body.innerText='Описание Logitech G435, цена 4499 ₽. '.repeat(150);
 assert.equal(vm.runInContext('readProduct()',ctx).status,'ok');
 console.log('PASS exact DNS public tab read without navigation/ownership/closing; empty Qrator challenge recognized; genuine long product is not misclassified');
})().catch(e=>{console.error(e);process.exitCode=1});
