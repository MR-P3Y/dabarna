// Real assets, local HTTP only, mocked APIs. No Telegram or production traffic.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../backend/app/static/mini');
const output=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../audit/autopilot-pacing-20261113/screenshots');
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
 const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/mini\/?/,'') || 'index.html';
 const full=path.resolve(base,name);
 if(!full.startsWith(base+path.sep)||!fs.existsSync(full)){res.writeHead(404).end();return;}
 res.setHeader('Content-Type',({'.js':'application/javascript','.mjs':'application/javascript','.html':'text/html','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.jpg':'image/jpeg'})[path.extname(full)]||'application/octet-stream');
 let body=fs.readFileSync(full);
 if(name==='app.js') {
  body=body.toString().replace('boot().catch((err) => {','Promise.resolve().catch((err) => {').replace('  let authOk = false;','  hideSplash(); return;\n  let authOk = false;');
  body+='\nwindow.qa={state,boot,refreshAutomationTimeline,renderAdminAutopilotConfig,renderAdminAutoDraw,tickAutomationTimeline,age(){automationReceivedAt-=16000;},setClocks(items){automationItems=items;automationReceivedAt=Date.now();gameStartCountdownServerOffsetMs=0;renderAutomationTimeline();}};';
 }
 res.end(body);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const page=await browser.newPage({viewport:{width:390,height:844}});
const errors=[],writes=[];let calls=0;
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',async route=>{
 const url=new URL(route.request().url());
 if(url.origin!==origin)return route.abort();
 if(!url.pathname.includes('mini-api'))return route.continue();
 if(route.request().method()!=='GET')writes.push(url.pathname);
 calls++;
 const data={automation:[{level:'LOW',game_id:91,phase:'WAITING_PLAYERS'}],server_time_utc:new Date().toISOString()};
 return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
try {
 await page.goto(origin+'/mini/');await page.waitForFunction(()=>window.qa);
 await page.evaluate(async()=>{await qa.boot();qa.state.token='OFFLINE_TEST';qa.state.tokenExp=9999999999;qa.state.authReady=true;qa.state.soundEnabled=false;
  document.querySelectorAll('.view').forEach(e=>e.classList.remove('active'));document.querySelector('#view-games').classList.add('active');
  qa.setClocks(['START','NEXT_NUMBER','NEXT_GAME'].map((phase,i)=>({phase,level:['LOW','MEDIUM','HIGH'][i],deadline_utc:new Date(Date.now()+[45000,4000,120000][i]).toISOString(),duration_seconds:[45,4,120][i]})));
 });
 assert.equal(await page.locator('.automation-phase').count(),3);
 assert.match(await page.locator('#automationTimeline').innerText(),/عدد بعدی/);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:path.join(output,'timers-mobile.png'),fullPage:true});
 await page.setViewportSize({width:1440,height:960});
 await page.screenshot({path:path.join(output,'timers-desktop.png'),fullPage:true});
 await page.evaluate(()=>qa.setClocks([{level:'LOW',phase:'START',deadline_utc:new Date(Date.now()-1000).toISOString(),duration_seconds:30}]));
 assert.match(await page.locator('.automation-label').innerText(),/در انتظار تأیید سرور/);
 await page.evaluate(()=>{qa.age();qa.tickAutomationTimeline();});
 assert.match(await page.locator('.automation-label').innerText(),/اطلاعات تازه در دسترس نیست/);
 assert.equal(await page.locator('.automation-digits').innerText(),'—');
 await page.evaluate(()=>{qa.state.gamesCache=[{id:91,status:'LOBBY',execution_source:'SYSTEM',countdown_enabled:true}];});
 const before=calls;
 await page.evaluate(()=>Promise.all([qa.refreshAutomationTimeline(),qa.refreshAutomationTimeline()]));
 assert.equal(calls-before,1,'polling must coalesce');
 assert.equal(await page.evaluate(()=>qa.state.gamesCache[0].countdown_enabled),false,'fresh readiness cancels old countdown');
 await page.evaluate(()=>{
  document.querySelector('#view-games').classList.remove('active');document.querySelector('#view-admin').classList.add('active');
  qa.renderAdminAutopilotConfig({items:['LINE','FULL_CARD'].map((game_rule,i)=>({level:['LOW','HIGH'][i],game_rule,card_price:5000,countdown_seconds:45,draw_interval_seconds:i?2:8,enabled:true}))});
  document.querySelectorAll('.autopilot-level-card').forEach(e=>e.open=true);
 });
 // Bypass only the authenticated navigation shell, keeping actual controls and actions.
 await page.locator('#adminAutopilotList').evaluate(el=>{let p=el;while(p&&p!==document.body){p.hidden=false;p.classList.remove('hidden');p.style.display='block';if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}});
 assert.deepEqual(await page.locator('#autopilotDrawInterval_HIGH option').evaluateAll(xs=>xs.map(x=>+x.value)),[2,3,4,5,8,10,15]);
 assert.deepEqual(await page.locator('#autopilotDrawInterval_LOW option').evaluateAll(xs=>xs.map(x=>+x.value)),[5,8,10,15]);
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'45');
 await page.locator('#autopilotCountdown_HIGH').fill('60');
 assert.equal(await page.locator('#autopilotCountdown_HIGH').inputValue(),'60');
 // Show the actual management control in isolation from navigation/auth fixtures.
 await page.locator('#adminAutopilotList').evaluate(el=>{let p=el;while(p&&p!==document.body){p.hidden=false;p.classList.remove('hidden');p.style.display='block';if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}});
 await page.setViewportSize({width:390,height:844});
 await page.locator('#adminAutopilotList').screenshot({path:path.join(output,'admin-pacing-mobile.png')});
 assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({result:'PASS',mockGetCalls:calls,writeRequests:writes.length,javascriptErrors:errors.length,productionRequests:0},null,2));
 console.log('PASS: actual browser assets, mobile/desktop clocks, server pending, stale data, coalesced polling, countdown revocation, admin countdown and rule-specific speeds; zero writes');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
