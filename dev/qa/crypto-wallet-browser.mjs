// Offline browser acceptance: actual production JS/HTML/CSS, mocked auth and GET APIs.
// PLAYWRIGHT_MODULE=file:///.../playwright/index.mjs CHROME_PATH=... node this-file
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../backend/app/static/mini');
const output=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../audit/crypto-current-20261112/screenshots');
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
 const name=decodeURIComponent(new URL(req.url,'http://localhost').pathname).replace(/^\/mini\/?/,'') || 'index.html';
 const full=path.resolve(base,name);
 if(!full.startsWith(base+path.sep)||!fs.existsSync(full)){res.writeHead(404).end();return;}
 const ext=path.extname(full); res.setHeader('Content-Type',({'.js':'application/javascript','.mjs':'application/javascript','.html':'text/html','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2'})[ext]||'application/octet-stream');
 let body=fs.readFileSync(full);
 if(name==='app.js'){
  body=body.toString().replace('boot().catch((err) => {','Promise.resolve().catch((err) => {').replace('  let authOk = false;','  hideSplash(); return;\n  let authOk = false;');
  body+='\nwindow.qa={state,boot,refreshNotifications,inboxUi,showAdminWinnerPopup,closeAdminWinnerModal,openWinnerModal,closeWinnerModal,openNotificationCenter,closeNotificationCenter,renderNotificationCenter,refreshGames,refreshSuperCryptoSettings};';
 }
 res.end(body);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
const errors=[],writes=[];
const oldAddress='0:'+'a'.repeat(64),newAddress='0:'+'b'.repeat(64);
let pending=[{network:'TON',address:newAddress,created_at:'fixture-1',expected_version:1,expected_current_address:oldAddress}],failReadiness=true;
const page=await browser.newPage({viewport:{width:390,height:844}});
page.on('pageerror',error=>errors.push(String(error)));
page.on('dialog',dialog=>dialog.accept());
await page.route('**/*',async route=>{
 const req=route.request(),url=new URL(req.url());
 if(url.origin!==origin)return route.abort();
 if(!url.pathname.includes('mini-api'))return route.continue();
 let body={},status=200;
 if(req.method()!=='GET'){
  const data=req.postDataJSON();writes.push({path:url.pathname,data});
  if(url.pathname.endsWith('/crypto-address-proposals/cancel'))pending=[];
  else if(url.pathname.endsWith('/crypto-address-proposals')){pending=[{network:'TON',address:data.address,created_at:'fixture-2',expected_version:1,expected_current_address:oldAddress}];status=201;}
  else throw new Error('Unexpected mutation: '+url.pathname);
 }else if(url.pathname.endsWith('/crypto-settings'))body={master_enabled:true,runtime_enabled:false,effective_enabled:false,configured:true,address_management_enabled:true,production_rotation_enabled:true,networks:[{network:'TON',asset:'TON',address:oldAddress,destination_version:1}]};
 else if(url.pathname.endsWith('/crypto-address-proposals'))body={items:pending,production_activation_supported:true};
 else if(url.pathname.endsWith('/crypto-address-readiness')){status=failReadiness?503:200;body=failReadiness?{detail:'شبکه آزمایشی در دسترس نیست'}:{historical_invoices:1};}
 return route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try{
 await page.goto(origin+'/mini/');await page.waitForFunction(()=>window.qa);
 await page.evaluate(async()=>{qa.state.currentUserId=8;qa.state.token='OFFLINE_TEST';qa.state.tokenExp=9999999999;await qa.boot();qa.state.admin.enabled=true;qa.state.admin.canManageSuperSettings=true;await qa.refreshSuperCryptoSettings();
   const surface=document.querySelector('#superCryptoWalletSection');document.body.append(surface);surface.open=true;surface.style.cssText='position:fixed;inset:0;overflow:auto;background:var(--bg);z-index:9999;padding:16px';});
 const apply=page.getByRole('button',{name:'فعال‌سازی واقعی آدرس جدید',exact:true});
 await apply.click();await page.waitForFunction(()=>document.querySelector('#superCryptoProposalHint').textContent.includes('شبکه'));
 assert.equal(await apply.isDisabled(),false,'failed readiness must restore button');
 assert.deepEqual(writes,[],'readiness failure must not activate');
 failReadiness=false;await apply.click();await page.waitForFunction(()=>document.querySelector('#superCryptoProposalHint').textContent.includes('مسدود'));
 assert.deepEqual(writes,[],'history blocks activation');
 await page.getByRole('button',{name:'لغو همین درخواست',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#superCryptoProposalsList').textContent.includes('درخواستی'));
 assert.deepEqual(writes[0].data,{network:'TON',expected_address:newAddress,expected_created_at:'fixture-1',confirmation:'CANCEL_PENDING_CRYPTO_ADDRESS'});
 await page.getByRole('button',{name:'✏️ تغییر آدرس',exact:true}).click();
 await page.locator('#superCryptoProposedAddress').fill(newAddress);
 await page.locator('#superCryptoProposalSubmitBtn').click();
 await page.waitForFunction(()=>document.querySelector('#superCryptoProposalsList').textContent.includes('در انتظار'));
 assert.equal(writes.length,2);assert.equal(writes[1].data.expected_current_address,oldAddress);assert.equal(writes[1].data.address,newAddress);
 await page.screenshot({path:path.join(output,'owner-crypto-mobile.png')});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({result:'PASS',mockedMutations:writes.length,realNetworkRequests:0,pageErrors:errors}));
}finally{await browser.close();server.close();}
