import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { chromium }=require(process.env.QA_PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.QA_BASE_URL || 'http://127.0.0.1:18761';
const browser = await chromium.launch({executablePath:process.env.QA_CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const errors=[];
const page=await browser.newPage({viewport:{width:390,height:844}});
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',async route=>{
 const url=new URL(route.request().url());
 if(url.hostname!=='127.0.0.1') return route.abort();
 if(url.pathname.endsWith('/app.js')){
  let source=fs.readFileSync('backend/app/static/mini/app.js','utf8');
  source=source.replace('boot().catch((err) => {','Promise.resolve().catch((err) => {');
  source += '\nwindow.qa = {state,drawGames,showSuperAdminPanelV13,hideSplash};';
  return route.fulfill({contentType:'application/javascript',body:source});
 }
 if(url.pathname.includes('mini-api'))return route.fulfill({contentType:'application/json',body:'{}'});
 return route.continue();
});
await page.goto(root+'/mini/');
await page.waitForFunction(()=>window.qa);
await page.evaluate(()=>{
 qa.hideSplash();
 qa.state.gamesCache=[
 {id:91,status:'LOBBY',game_level:'LOW',game_rule:'LINE',card_layout_version:2,execution_source:'SYSTEM',card_price:5000,prize_pool:9000,draw_mode:'AUTO',countdown_enabled:true,countdown_seconds:30,scheduled_start_at:new Date(Date.now()+20000).toISOString()},
 {id:92,status:'RUNNING',game_level:'HIGH',game_rule:'FULL_CARD',card_layout_version:2,execution_source:'SYSTEM',card_price:10000,prize_pool:18000,called_numbers:[1,20,40],draw_mode:'AUTO'},
 {id:93,status:'ENDED',game_rule:'LEGACY',card_layout_version:1,card_price:1000,prize_pool:1800}
 ];
 qa.drawGames(qa.state.gamesCache);
});
fs.mkdirSync('dev/audit/integration-20261111/screenshots',{recursive:true});
await page.waitForTimeout(600);
await page.screenshot({path:'dev/audit/integration-20261111/screenshots/games-mobile.png',fullPage:true});
assert.ok(await page.locator('#gamesList').innerText());
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'mobile horizontal overflow');
await page.setViewportSize({width:1440,height:1000});
await page.evaluate(()=>{
 qa.state.admin.canManageSuperSettings=true;
 document.getElementById('view-games').classList.remove('active');
 document.getElementById('view-admin').classList.add('active');
 document.getElementById('superAdminSection').classList.remove('hidden');
 qa.showSuperAdminPanelV13('superPanelPayments');
});
assert.equal(await page.locator('#superPanelPayments').getAttribute('hidden'),null);
assert.equal(await page.locator('#superTabPayments').getAttribute('aria-selected'),'true');
await page.screenshot({path:'dev/audit/integration-20261111/screenshots/superadmin-desktop.png',fullPage:true});
console.log(JSON.stringify({errors,mobileOverflow:false,superadminPanel:'Payments',http:await page.request.get(root+'/health/db').then(r=>r.status())}));
await browser.close();
assert.deepEqual(errors,[]);
