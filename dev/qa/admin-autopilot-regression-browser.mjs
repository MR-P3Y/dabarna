// Real assets, local HTTP only, mocked APIs. No Telegram or production traffic.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../backend/app/static/mini');
const output=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../audit/admin-editor-20261114/screenshots');
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
 const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/mini\/?/,'') || 'index.html';
 const full=path.resolve(base,name);
 if(!full.startsWith(base+path.sep)||!fs.existsSync(full)){res.writeHead(404).end();return;}
 res.setHeader('Content-Type',({'.js':'application/javascript','.mjs':'application/javascript','.html':'text/html','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.jpg':'image/jpeg'})[path.extname(full)]||'application/octet-stream');
 let body=fs.readFileSync(full);
 if(name==='app.js') {
  body=body.toString().replace('boot().catch((err) => {','Promise.resolve().catch((err) => {').replace('  let authOk = false;','  hideSplash(); return;\n  let authOk = false;');
  body+='\nwindow.qa={state,boot,refreshAdminAutopilotConfig,saveAdminAutopilotLevel,renderAutopilotReadiness,setSystemClocks(items){systemGameClockRows=items;systemGameClockRuntimeReady=true;systemGameDrawWorkerReady=true;renderSystemGameClocks();},refreshAutomationTimeline,renderAdminAutopilotConfig,renderAdminAutoDraw,tickAutomationTimeline,age(){automationReceivedAt-=16000;},setClocks(items){automationItems=items;automationReceivedAt=Date.now();gameStartCountdownServerOffsetMs=0;renderAutomationTimeline();}};';
 }
 res.end(body);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[],writes=[];let calls=0,failConfig=false,holdGet=null,holdPut=null;
let config={can_edit_commission:true,items:['LINE','FULL_CARD'].map((game_rule,i)=>({level:['LOW','HIGH'][i],game_rule,card_price:5000,countdown_seconds:45,draw_interval_seconds:i?2:8,repeat_interval_seconds:120,cooldown_seconds:30,announce_before_seconds:300,commission_rate:.1,enabled:true}))};
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',async route=>{
 const url=new URL(route.request().url());
 if(url.origin!==origin)return route.abort();
 if(!url.pathname.includes('mini-api'))return route.continue();
 if(route.request().method()!=='GET')writes.push(url.pathname);
 calls++;
 if(url.pathname.endsWith('/autopilot/config')){
  const snapshot=structuredClone(config);
  if(holdGet){const gate=holdGet;holdGet=null;gate.arrived();await gate.wait;}
  return route.fulfill({status:failConfig?503:200,contentType:'application/json',body:JSON.stringify(failConfig?{detail:'Offline fixture'}:snapshot)});
 }
 if(route.request().method()==='PUT' && url.pathname.includes('/autopilot/config/')){
  const payload=route.request().postDataJSON(),level=url.pathname.split('/').at(-1);
  if(holdPut){const gate=holdPut;holdPut=null;gate.arrived();await gate.wait;}
  Object.assign(config.items.find(item=>item.level===level),payload);
  return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true})});
 }
 const data={automation:[{level:'LOW',game_id:91,phase:'WAITING_PLAYERS'}],server_time_utc:new Date().toISOString()};
 return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
function gate(){let arrived,release;const ready=new Promise(r=>arrived=r),wait=new Promise(r=>release=r);return {arrived,release,ready,wait};}
try {
 await page.goto(origin+'/mini/');await page.waitForFunction(()=>window.qa);
 await page.evaluate(async()=>{
  await qa.boot();qa.state.token='OFFLINE_TEST';qa.state.tokenExp=9999999999;qa.state.authReady=true;qa.state.admin.enabled=true;
  document.querySelectorAll('.view').forEach(e=>e.classList.remove('active'));document.querySelector('#view-admin').classList.add('active');
  await qa.refreshAdminAutopilotConfig();
  let p=document.querySelector('#adminAutopilotList');while(p&&p!==document.body){p.hidden=false;p.classList.remove('hidden');p.style.display='block';if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}
  const low=document.querySelector('[data-autopilot-level="LOW"]');low.open=true;low.querySelector('.autopilot-advanced').open=true;
 });
 const low=page.locator('[data-autopilot-level="LOW"]'),high=page.locator('[data-autopilot-level="HIGH"]');
 config.items[0].countdown_seconds=50;
 await page.evaluate(()=>qa.refreshAdminAutopilotConfig());
 assert.equal(await low.evaluate(e=>e.open),true,'changed server snapshot must not close the category');
 assert.equal(await low.locator('.autopilot-advanced').evaluate(e=>e.open),true,'nested settings stay open');
 assert.equal(await page.locator('#autopilotCountdown_LOW').inputValue(),'50','clean data still refreshes');
 await high.evaluate(e=>e.open=true);
 await page.locator('#autopilotCountdown_HIGH').fill('60');
 await page.evaluate(()=>{window.originalInput=document.activeElement;window.originalInput.setSelectionRange(1,1);});
 config.items[1].countdown_seconds=55;
 await page.evaluate(()=>qa.refreshAdminAutopilotConfig({force:true}));
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'60');
 assert.equal(await page.evaluate(()=>document.activeElement===window.originalInput),true,'polling retains the actual input and focus');
 assert.equal(await page.evaluate(()=>document.activeElement.selectionStart),1,'caret stays in place');
 failConfig=true;await page.evaluate(()=>qa.refreshAdminAutopilotConfig());
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'60');
 assert.match(await page.locator('#adminAutopilotSyncStatus').innerText(),/حفظ شدند/);
 failConfig=false;
 const delayedGet=gate();holdGet=delayedGet;
 await page.evaluate(()=>{window.pendingRefresh=qa.refreshAdminAutopilotConfig();});await delayedGet.ready;
 await page.locator('#autopilotCountdown_LOW').fill('70');
 const delayedPut=gate();holdPut=delayedPut;
 await page.evaluate(()=>{window.pendingSave=qa.saveAdminAutopilotLevel('LOW',true);});await delayedPut.ready;
 await page.locator('#autopilotCountdown_LOW').fill('75');
 delayedPut.release();
 await page.waitForFunction(()=>document.querySelector('[data-autopilot-level="LOW"]').dataset.saving==='0');
 delayedGet.release();
 await page.evaluate(()=>Promise.all([window.pendingRefresh,window.pendingSave]));
 assert.equal(config.items[0].countdown_seconds,70,'only submitted values are sent');
 assert.equal(await page.locator('#autopilotCountdown_LOW').inputValue(),'75','editing during save is retained');
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'60','saving one level never clears another draft');
 assert.equal(await low.getAttribute('data-dirty'),'1');
 assert.equal(await high.getAttribute('data-dirty'),'1');
 assert.match(await page.locator('#adminAutopilotHint_LOW').innerText(),/هنوز ذخیره نشده/);
 await page.evaluate(()=>qa.saveAdminAutopilotLevel('LOW',true));
 assert.equal(config.items[0].countdown_seconds,75);
 assert.equal(await low.getAttribute('data-dirty'),'0');
 assert.equal(await high.getAttribute('data-dirty'),'1');
 await page.locator('#adminAutopilotRefreshBtn').click();
 await page.waitForFunction(()=>!document.querySelector('#adminAutopilotRefreshBtn').disabled);
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'60','manual refresh also retains drafts');
 config.can_edit_commission=false;
 await page.evaluate(()=>qa.refreshAdminAutopilotConfig());
 assert.equal(await page.locator('#autopilotCommission_HIGH').isDisabled(),true,'dirty form does not preserve revoked privilege');
 assert.equal(await high.locator('[data-autopilot-save]').getAttribute('data-can-edit-commission'),'0');
 await page.evaluate(()=>{
  qa.renderAutopilotReadiness({levels:['LOW','MEDIUM','HIGH'].map((level,i)=>({level,existing_system_game:i<2,active_game_id:i<2?91+i:null,active_game_status:'LOBBY',ready_to_generate:true,checks:{runtime_enabled:true,auto_draw_worker:true}}))});
  qa.setSystemClocks([{id:91,game_level:'LOW',status:'LOBBY',card_price:5000,scheduled_start_at:null},{id:92,game_level:'MEDIUM',status:'RUNNING',draw_mode:'AUTO',draw_interval_seconds:8,card_price:3000}]);
  document.documentElement.dataset.theme='light';
 });
 await page.setViewportSize({width:1280,height:1000});
 const panel=page.locator('.system-game-clock-panel');
 const colors=await panel.evaluate(el=>({background:getComputedStyle(el).backgroundImage,card:getComputedStyle(el.querySelector('.system-clock-card')).backgroundColor,ink:getComputedStyle(el.querySelector('.system-clock-digits')).color,meta:getComputedStyle(el.querySelector('.meta')).color}));
 assert.equal(colors.card,'rgb(255, 255, 255)');assert.equal(colors.ink,'rgb(23, 48, 71)');assert.equal(colors.meta,'rgb(71, 94, 118)');
 await panel.screenshot({path:path.join(output,'system-clocks-light-desktop.png')});
 await page.setViewportSize({width:390,height:844});
 await panel.screenshot({path:path.join(output,'system-clocks-light-mobile.png')});
 await page.locator('#adminAutopilotList').screenshot({path:path.join(output,'editor-light-mobile.png')});
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 await panel.screenshot({path:path.join(output,'system-clocks-dark-mobile.png')});
 assert.notEqual(await panel.locator('.system-clock-card').first().evaluate(el=>getComputedStyle(el).backgroundColor),colors.card);
 assert.equal(writes.length,2,'only two explicit mocked saves; refresh never writes');assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({result:'PASS',mockApiCalls:calls,mockedWrites:writes.length,realNetworkRequests:0,javascriptErrors:errors.length,scenarios:['open and nested details','clean refresh','focus and caret','unsaved drafts','failed refresh','late GET after save','edits during save','per-level save','manual refresh','permission revocation','light and dark mobile/desktop']},null,2));
 console.log('PASS: theme, stable details/focus/caret/drafts, failure recovery, stale GET, concurrent edits, per-level save and revoked permission; two mocked saves, zero external traffic');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
