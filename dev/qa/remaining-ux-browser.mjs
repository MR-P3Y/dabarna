// Offline browser acceptance: actual production JS/HTML/CSS, mocked auth and GET APIs.
// PLAYWRIGHT_MODULE=file:///.../playwright/index.mjs CHROME_PATH=... node this-file
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../backend/app/static/mini');
const output=process.env.SCREENSHOT_DIR || path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../audit/remaining-20261111/screenshots');
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
 const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/mini\/?/,'') || 'index.html';
 const full=path.resolve(base,name);
 if(!full.startsWith(base+path.sep)||!fs.existsSync(full)){res.writeHead(404).end();return;}
 const ext=path.extname(full); res.setHeader('Content-Type',({'.js':'application/javascript','.mjs':'application/javascript','.html':'text/html','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2'})[ext]||'application/octet-stream');
 let body=fs.readFileSync(full);
 if(name==='app.js'){
  body=body.toString().replace('boot().catch((err) => {','Promise.resolve().catch((err) => {').replace('  let authOk = false;','  hideSplash(); return;\n  let authOk = false;');
  body+='\nwindow.qa={state,boot,refreshNotifications,inboxUi,showAdminWinnerPopup,closeAdminWinnerModal,openWinnerModal,closeWinnerModal,openNotificationCenter,closeNotificationCenter,renderNotificationCenter,refreshGames,drawGames,refreshCards,stopCardsPolling,loadEventCues,handleMiniSocketMessage};';
 }
 res.end(body);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const errors=[],writes=[];
let failNotifications=false, failGames=false, failReceipts=false, notificationCalls=0, receiptCalls=0;
const games=[
 {id:91,status:'LOBBY',game_level:'LOW',game_rule:'LINE',card_layout_version:2,card_price:5000,created_at:'2026-11-11T10:00:00Z',scheduled_start_at:'2026-11-11T11:00:00Z'},
 {id:92,status:'RUNNING',game_level:'HIGH',game_rule:'FULL_CARD',card_layout_version:2,card_price:10000,created_at:'2026-11-11T09:00:00Z'},
 {id:93,status:'ENDED',game_level:'LOW',game_rule:'LEGACY',card_layout_version:1,card_price:2000,created_at:'2026-11-10T09:00:00Z'},
];
const notifications=[{id:'deposit:1',kind:'deposit',title:'واریز در انتظار بررسی',body:'درخواست آزمایشی · ۲۰٬۰۰۰ تومان',severity:'pending',created_at:'2026-11-11T12:00:00Z',receipt_kind:'bank_deposit',receipt_id:1,route:{view:'wallet',action:'open_receipt'}},
 {id:'prize:1',kind:'win',title:'جایزه ثبت شد',body:'<img src=x onerror="window.xss=true">',created_at:'2026-11-11T11:00:00Z',severity:'success',receipt_kind:'prize',receipt_id:2,route:{view:'cards',action:'open_winning_card',target_id:92}}];
const page=await browser.newPage({viewport:{width:390,height:844}});
const grid=[1,0,20,0,40,0,60,0,80,2,0,21,0,41,0,61,0,81,3,0,22,0,42,0,62,0,82];
const personalDraws=[50,3,12];
let personal=false, ended=false, disconnected=false, personalEvent=1000;
page.on('pageerror',error=>errors.push(String(error)));
await page.route('**/*',async route=>{
 const url=new URL(route.request().url());
 if(url.origin!==origin) return route.abort();
 if(!url.pathname.includes('mini-api'))return route.continue();
 if(route.request().method()!=='GET')writes.push(url.pathname);
 let body={};let status=200;
 if(personal && url.pathname.endsWith('/me/active-games')){
   body={items:[
     {game_id:92,status:'RUNNING',card_count:2,last_number:personalDraws.at(-1)},
     {game_id:91,status:'LOBBY',card_count:1,last_number:null},
   ]};
 } else if(personal && url.pathname.endsWith('/snapshot')){
   const id=Number(url.pathname.split('/').at(-2));
   const game={...games.find(g=>g.id===id)};
   if(id===92 && ended)game.status='ENDED';
   const called=id===92 ? personalDraws : [];
   body={game,state:{status:game.status,game_rule:game.game_rule,card_layout_version:game.card_layout_version,
     called_numbers:called,last_number:called.at(-1)??null},last_event_id:personalEvent,recent_events:[],
     my_cards:(id===92?[701,702]:id===91?[703]:[]).map((card_id,i)=>({card_id,display_serial:i+1,
       fingerprint:'mock-'+card_id,numbers:i?grid.map(n=>n?n+1:0):grid}))};
   if(id===92 && disconnected)status=503;
 } else if(url.pathname.endsWith('/notifications')){notificationCalls++;body={items:notifications};if(failNotifications)status=503;}
 else if(url.pathname.endsWith('/games')){body={items:games};if(failGames)status=403;}
 else if(url.pathname.includes('/receipts/')){receiptCalls++;if(failReceipts)status=503;body={title:'رسید آزمایشی',kind:'prize',status:'DONE',amount:70,direction:'CREDIT',items:[]};}
 else if(url.pathname.includes('/snapshot'))body={game:games[1],state:{game_rule:'FULL_CARD',card_layout_version:2,status:'ENDED',called_numbers:[],row_winner_card_ids:[101,102]},events:[]};
 else if(url.pathname.includes('/admin/games/')&&url.pathname.includes('/cards/'))body={card_id:101,numbers:[1,0,20,0,40,0,60,0,80,2,0,21,0,41,0,61,0,81,3,0,22,0,42,0,62,0,82],user:{user_id:8,display_name:'بازیکن آزمایشی'}};
 else if(url.pathname.endsWith('/me/cards'))body={items:[]};
 await new Promise(resolve=>setTimeout(resolve,30));
 return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try {
 await page.goto(origin+'/mini/');await page.waitForFunction(()=>window.qa);
 await page.evaluate(async()=>{qa.state.currentUserId=8;qa.state.token='OFFLINE_TEST';qa.state.tokenExp=9999999999;qa.state.soundEnabled=false;await qa.boot();});
 await page.evaluate(rows=>qa.drawGames(rows),games);
 await page.locator('[data-game-filter="RUNNING"]').click();
 assert.equal(await page.locator('#gamesList article:visible').count(),1);
 assert.equal(await page.locator('#gamesList article:visible').getAttribute('data-status'),'RUNNING');
 await page.evaluate(rows=>qa.drawGames(rows.filter(g=>g.status!=='RUNNING')),games);
 assert.equal(await page.locator('#gameFilterEmpty').isVisible(),true);
 await page.evaluate(rows=>qa.drawGames(rows),games);
 assert.equal(await page.locator('[data-game-filter="RUNNING"]').getAttribute('aria-pressed'),'true');
 await page.locator('[data-game-filter="ALL"]').click();
 await page.locator('.player-preferences summary').click();
 assert.equal(await page.locator('#themeBtn').isVisible(),true);
 await page.locator('#themeBtn').click();
 await page.locator('.player-preferences summary').click();
 assert.equal(await page.locator('#themeBtn').isVisible(),false);
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 assert.equal(await page.locator('#gamesList article:visible').count(),3);
 await page.locator('#notificationsBtn').click();
 await page.waitForFunction(()=>qa.inboxUi.syncedAt&&!qa.inboxUi.loading);
 assert.equal(await page.locator('.inbox-card').count(),5);
 const filterBounds=await page.locator('#notificationFilters').boundingBox();
 assert.ok(filterBounds.height >= 44, 'inbox filters retain a full touch target');
 assert.equal(await page.evaluate(()=>Boolean(window.xss)),false);
 assert.equal(await page.locator('#notificationList img').count(),0);
 const focusable=page.locator('#notificationCenter [role="dialog"] button:visible:not(:disabled)');
 await focusable.last().focus();await page.keyboard.press('Tab');
 assert.equal(await focusable.first().evaluate(el=>el===document.activeElement),true,'Tab wraps within modal');
 await page.keyboard.press('Shift+Tab');
 assert.equal(await focusable.last().evaluate(el=>el===document.activeElement),true,'reverse Tab wraps within modal');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:path.join(output,'inbox-mobile-dark.png'),fullPage:true});
 await page.locator('[data-filter="game"]').click();assert.equal(await page.locator('.inbox-card').count(),3);
 await page.locator('[data-filter="payment"]').click();assert.equal(await page.locator('.inbox-card').count(),1);
 failReceipts=true;
 await page.locator('[data-inbox-action="receipt"]').click();await page.waitForFunction(()=>document.querySelector('#receiptModalBody').textContent.includes('دریافت نشد'));
 assert.equal(await page.evaluate(()=>qa.state.notificationReadIds.has('deposit:1')),false,'failed receipt must stay unread');
 await page.keyboard.press('Escape');assert.equal(await page.locator('#receiptModal').getAttribute('aria-hidden'),'true');
 assert.equal(await page.locator('#notificationCenter').getAttribute('aria-hidden'),'false','nested Escape preserves inbox');
 failReceipts=false;
 await page.locator('[data-inbox-action="receipt"]').click();await page.waitForFunction(()=>qa.state.notificationReadIds.has('deposit:1'));
 await page.keyboard.press('Escape');
 assert.equal(await page.evaluate(()=>document.activeElement.dataset.inboxAction),'receipt','nested dialog restores focus');
 await page.waitForFunction(()=>!qa.inboxUi.request);
 const count=notificationCalls;await page.evaluate(()=>Promise.all([qa.refreshNotifications(),qa.refreshNotifications(),qa.refreshNotifications()]));
 assert.equal(notificationCalls-count,1,'refresh requests must coalesce');
 failNotifications=true;await page.evaluate(()=>qa.refreshNotifications());
 assert.equal(await page.locator('#notificationSyncStatus').getAttribute('data-state'),'error');
 assert.equal(await page.locator('.inbox-card').count(),1,'failure retains snapshot');
 failNotifications=false;
 failGames=true; notifications.push({id:'deposit:new',kind:'deposit',title:'واریز تازه',body:'۲۰ تومان',created_at:'2026-11-11T13:00:00Z'});
 await page.evaluate(()=>qa.refreshNotifications());
 assert.equal(await page.locator('.inbox-card').count(),2,'game access failure must not hide fresh financial notifications');
 assert.equal(await page.evaluate(()=>qa.inboxUi.partial),true);
 notifications.pop();failGames=false;
 await page.locator('#notificationRefreshBtn').click();await page.waitForFunction(()=>!qa.inboxUi.loading&&!qa.inboxUi.error);
 await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.id),'notificationsBtn');
 assert.equal(await page.evaluate(()=>qa.inboxUi.timer),null,'close releases refresh timer');
 await page.waitForFunction(()=>document.querySelector('#miniToast').classList.contains('hidden'));
 const event={id:400,kind:'PRIZE_ROW',game_id:92,payload:{game_rule:'FULL_CARD',card_layout_version:2,winner_user_ids:[8,8,9],winner_card_ids:[101,102,103],amounts_by_card:[30,40,50],amount_total:120}};
 await page.evaluate(event=>qa.openWinnerModal(event),event);
 assert.match(await page.locator('#winnerModalKind').innerText(),/پرکردنی/);
 assert.equal(await page.locator('#winnerCardDetails .winner-card-share').count(),2);
 assert.match(await page.locator('#winnerModalAmount').innerText(),/۷۰/);
 await page.waitForTimeout(250);
 await page.screenshot({path:path.join(output,'winner-mobile-dark.png'),fullPage:true});
 await page.evaluate(event=>qa.openWinnerModal({...event,id:401,payload:{...event.payload,amounts_by_card:[]}}),event);
 await page.keyboard.press('Escape');assert.match(await page.locator('#winnerModalAmount').innerText(),/قابل تأیید نیست/);
 await page.keyboard.press('Escape');
 await page.evaluate(event=>{qa.state.admin.enabled=true;qa.showAdminWinnerPopup(event);},event);
 assert.equal(await page.locator('.admin-winner-row').count(),3);
 assert.match(await page.locator('.admin-winner-summary').innerText(),/پرکردنی/);
 await page.waitForTimeout(250);
 await page.screenshot({path:path.join(output,'admin-winner-mobile.png'),fullPage:true});
 await page.locator('.admin-winner-row [data-admin-winner-action="open-card"]').first().click();
 await page.waitForFunction(()=>document.querySelector('#adminWinnerCardPanel .mini-card-grid'));
 assert.equal(await page.locator('#adminWinnerCardPanel .mini-card-grid.v2').count(),1);
 await page.setViewportSize({width:1440,height:1000});
 await page.evaluate(()=>document.documentElement.dataset.theme='light');
 await page.screenshot({path:path.join(output,'admin-winner-desktop-light.png'),fullPage:true});
 await page.keyboard.press('Escape');
 await page.evaluate(event=>qa.showAdminWinnerPopup(event),event);
 assert.equal(await page.locator('#adminWinnerModal').getAttribute('aria-hidden'),'true','seen event must not reopen');
 for (const [id,rule,layout,kind,label] of [[410,'LINE',2,'PRIZE_COL','۳ عدد'],[411,'LINE',2,'PRIZE_ROW','۵ عدد'],[412,'LEGACY',1,'PRIZE_COL','۴عددی'],[413,'LEGACY',1,'PRIZE_ROW','۵عددی']]) {
   await page.evaluate(({event,id,rule,layout,kind})=>qa.openWinnerModal({...event,id,kind,payload:{...event.payload,game_rule:rule,card_layout_version:layout}}),{event,id,rule,layout,kind});
   assert.ok((await page.locator('#winnerModalKind').innerText()).includes(label));
   assert.match(await page.locator('#winnerModalAmount').innerText(),/۷۰/);
   await page.keyboard.press('Escape');
 }
 await page.evaluate(event=>qa.openWinnerModal({...event,id:414,payload:{...event.payload,winner_user_ids:[18,18,19]}}),event);
 assert.equal(await page.locator('#winnerModal').getAttribute('aria-hidden'),'true','other user prize must not open personal popup');
 await page.evaluate(()=>{qa.state.currentUserId=9;qa.openNotificationCenter();});await page.waitForFunction(()=>!qa.inboxUi.loading);
 assert.equal(await page.evaluate(()=>qa.state.notificationReadIds.has('deposit:1')),false,'read state scoped to account');
 await page.locator('[data-filter="all"]').click();
 await page.screenshot({path:path.join(output,'inbox-desktop-light.png'),fullPage:true});
 await page.keyboard.press('Escape');
 personal=true;
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(async()=>{
   qa.state.currentUserId=8;
   qa.state.admin.enabled=false;
   window.testVibrations=[];
   Object.defineProperty(navigator,'vibrate',{configurable:true,value:n=>{window.testVibrations.push(n);return true;}});
   await qa.refreshGames();
 });
 assert.equal(await page.locator('#returnGameSelect option').count(),2);
 assert.match(await page.locator('#returnGameStatus').innerText(),/۱۲/);
 await page.locator('#returnGameSelect').selectOption('91');
 await page.evaluate(()=>qa.refreshGames());
 assert.equal(await page.locator('#returnGameSelect').inputValue(),'91');
 assert.match(await page.locator('#returnGameStatus').innerText(),/هنوز عددی/);
 await page.locator('#returnGameCards').click();
 await page.locator('.active-game-block[data-game-id="91"]').waitFor();
 assert.equal(await page.locator('[data-focus-game="91"]').count(),0);
 await page.locator('.nav-btn[data-view="games"]').click();
 await page.locator('#returnGameSelect').selectOption('92');
 await page.locator('#returnGamePanel').screenshot({path:path.join(output,'return-game.png')});
 await page.locator('.player-preferences summary').click();
 await page.locator('#numberCue').uncheck();
 await page.locator('#startCue').uncheck();
 await page.locator('.player-preferences').screenshot({path:path.join(output,'event-preferences.png')});
 assert.deepEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('davarna_event_cues:8'))),{start:false,number:false});
 await page.evaluate(()=>{qa.state.currentUserId=9;qa.loadEventCues();});
 assert.equal(await page.locator('#numberCue').isChecked(),true);
 await page.evaluate(()=>{qa.state.currentUserId=8;qa.loadEventCues();});
 assert.equal(await page.locator('#startCue').isChecked(),false);
 await page.locator('.player-preferences summary').click();
 await page.locator('#returnGameCards').click();
 await page.locator('[data-focus-game="92"]').click();
 await page.evaluate(()=>qa.stopCardsPolling());
 const focus=page.locator('#cardFocus');
 assert.equal(await focus.isVisible(),true);
 assert.equal(await page.locator('#focusCardSelect option').count(),2);
 await page.locator('#focusCardSelect').selectOption('702');
 assert.equal(await page.locator('#focusGrid .num-chip').count(),27);
 assert.equal(await page.locator('#focusGrid .empty-cell').count(),12);
 const initialHaptics=await page.evaluate(()=>window.testVibrations.length);
 personalDraws.push(22);personalEvent++;
 await page.evaluate(()=>qa.refreshCards({silent:true}));
 assert.equal(await page.locator('#focusCardSelect').inputValue(),'702');
 assert.equal(await page.locator('#focusLastNumber').innerText(),'۲۲');
 assert.match(await page.locator('#focusMatches').innerText(),/۲ از ۱۵/);
 assert.equal(await page.evaluate(()=>window.testVibrations.length),initialHaptics);
 for(const width of [320,390]){
   await page.setViewportSize({width,height:844});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 await focus.screenshot({path:path.join(output,'full-card-focus.png')});
 disconnected=true;
 await page.evaluate(()=>qa.refreshCards({silent:true}));
 assert.equal(await page.locator('#focusReadout').isVisible(),false);
 assert.match(await page.locator('#focusState').innerText(),/ارتباط/);
 disconnected=false;
 await page.evaluate(()=>qa.refreshCards({silent:true}));
 assert.equal(await page.locator('#focusReadout').isVisible(),true);
 await page.locator('.player-preferences summary').click();
 await page.locator('#numberCue').check();
 if(await page.locator('#countdownVibrationBtn').getAttribute('aria-pressed')==='false')await page.locator('#countdownVibrationBtn').click();
 await page.locator('.player-preferences summary').click();
 const before=await page.evaluate(()=>window.testVibrations.length);
 personalDraws.push(4);personalEvent++;
 await page.evaluate(async()=>{
   const url='/mini-api/games/92/snapshot';
   const snapshot=await (await fetch(url)).json();
   const emit=s=>qa.handleMiniSocketMessage({data:JSON.stringify({type:'live_snapshot',game_id:92,snapshot:s})});
   emit(snapshot);
   emit({...snapshot,last_event_id:snapshot.last_event_id-1,state:{...snapshot.state,called_numbers:[],last_number:null}});
   await qa.refreshCards({silent:true});
 });
 assert.equal(await page.locator('#focusLastNumber').innerText(),'۴');
 assert.equal(await page.evaluate(()=>window.testVibrations.length),before+1,'one vibration on a new draw');
 ended=true;personalEvent++;
 await page.evaluate(()=>qa.refreshCards({silent:true}));
 assert.match(await page.locator('#focusState').innerText(),/پایان/);
 await page.locator('#exitCardFocus').click();
 assert.equal(await focus.isVisible(),false);
 assert.equal(await page.locator('#cardsPanel').isVisible(),true);
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
 console.log(JSON.stringify({result:'PASS',screenshots:8,pageErrors:errors,mutationRequests:writes,notificationCalls,receiptCalls}));
} finally {await browser.close();server.close();}
