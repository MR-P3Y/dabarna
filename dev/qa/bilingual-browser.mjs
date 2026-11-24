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
 if(name==='app.js'||name==='app.en.js'){
  body=body.toString().replace('boot().catch((err) => {','Promise.resolve().catch((err) => {').replace('  let authOk = false;','  hideSplash(); return;\n  let authOk = false;');
  body+='\nwindow.qa={state,boot,refreshNotifications,inboxUi,showAdminWinnerPopup,closeAdminWinnerModal,openWinnerModal,closeWinnerModal,openNotificationCenter,closeNotificationCenter,renderNotificationCenter,refreshGames,drawGames,refreshCards,stopCardsPolling,loadEventCues,handleMiniSocketMessage,drawWallet,renderAdminOpsDashboard};';
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
let failTracking=false;
let unsafeTracking=true;
const trackingRow={kind:"deposit",id:125,code:"DAV-DEP-000125",title:"واریز بانکی",status:"APPROVED",status_label:"تأیید شده",amount:20000,created_at:"2026-11-20T10:00:00Z"};
page.on('pageerror',error=>errors.push(String(error)));
await page.route('**/*',async route=>{
 const url=new URL(route.request().url());
 if(url.origin!==origin) return route.abort();
 if(!url.pathname.includes('mini-api'))return route.continue();
 if(route.request().method()!=='GET')writes.push(url.pathname);
 let body={};let status=200;
 if(url.pathname.includes('/tracking/search')){
   if(failTracking)status=503;
   const offset=Number(url.searchParams.get('offset')||0);
   body={items:offset?[{...trackingRow,id:126,code:"DAV-DEP-000126"}]:[trackingRow,{...trackingRow,kind:"game",id:12,title:"بازی",code:"G-261121-012",amount:null}],total:21,offset,limit:20,fetched_at:"2026-11-21T12:00:00Z"};
 } else if(url.pathname.includes('/tracking/deposit/')){
   body={...trackingRow,fields:[{label:"دلیل بررسی",value:unsafeTracking?'<img src=x onerror="window.trackingXss=true">':"رسید بررسی شد و اعتبار در کیف پول ثبت شد."}],
     links:[],timeline:[{label:"ثبت درخواست",at:trackingRow.created_at}],audit:{items:[],total:0,offset:0,limit:20},fetched_at:"2026-11-21T12:00:00Z"};
 } else if(personal && url.pathname.endsWith('/me/active-games')){
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
 await page.goto(origin+'/mini/en.html');await page.waitForFunction(()=>window.qa);
 await page.evaluate(async()=>{qa.state.currentUserId=8;qa.state.token='OFFLINE_TEST';qa.state.tokenExp=9999999999;await qa.boot();});
 await page.evaluate(rows=>qa.drawGames(rows),games);
 assert.equal(await page.locator('html').getAttribute('dir'),'ltr');
 assert.equal(await page.locator('#languageSelect').inputValue(),'en');
 assert.match(await page.locator('#gamesList').innerText(),/Line/);
 assert.match(await page.locator('#gamesList').innerText(),/Full card/);
 for(const theme of ['light','dark']){
  await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
  for(const width of [320,390,1440]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no horizontal overflow');
   await page.locator('.player-preferences summary').click();
   assert.equal(await page.locator('#languageSelect').isVisible(),true);
   await page.screenshot({path:path.join(output,`english-${theme}-${width}.png`)});
   await page.locator('.player-preferences summary').click();
  }
 }
 await page.locator('#trackingBtn').click();
 await page.locator('#trackingForm').evaluate(e=>e.requestSubmit());
 await page.waitForSelector('.tracking-result');
 assert.match(await page.locator('#trackingBody').innerText(),/Bank deposit/);
 assert.match(await page.locator('#trackingBody').innerText(),/DAV-DEP-000125/);
 await page.keyboard.press('Escape');
 await page.locator('.player-preferences summary').click();
 page.once('dialog',d=>d.dismiss());
 await page.selectOption('#languageSelect','fa');
 assert.match(page.url(),/en.html/);
 assert.equal(await page.locator('#languageSelect').inputValue(),'en');
 page.once('dialog',d=>d.accept());
 await page.selectOption('#languageSelect','fa');
 await page.waitForURL('**/index.html');
 assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
 assert.equal(await page.evaluate(()=>localStorage.getItem('davarna_ui_language')),'fa');
 await page.waitForFunction(()=>window.qa);await page.evaluate(()=>qa.boot());await page.locator('.player-preferences summary').click();
 page.once('dialog',d=>d.accept());await page.selectOption('#languageSelect','en');
 await page.waitForURL('**/en.html');
 await page.goto(origin+'/mini/');await page.waitForURL('**/en.html');
 assert.equal(writes.length,0,'language changes never submit API mutations');
 assert.deepEqual(errors,[]);
 console.log('PASS: bilingual direction, games, tracking codes, 6 layouts, cancellation, persistence, zero API writes');
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
