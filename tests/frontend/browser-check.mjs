// Run with Playwright available through NODE_PATH; uses synthetic HA/provider responses.
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium} = createRequire(import.meta.url)('playwright');
const assets = new URL('../../custom_components/solbuddy_access/www/', import.meta.url);
const browser = await chromium.launch({headless:true,channel:process.env.CHROMIUM_CHANNEL || "chrome"});
let checks=0;
try {
  const page=await browser.newPage({viewport:{width:1100,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('owner-panel.js')) return route.fulfill({contentType:'application/javascript',body:await readFile(new URL('owner-panel.js',assets),'utf8')});
    return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'});
  });
  await page.goto('http://ha.test/solbuddy-access');
  await page.addScriptTag({url:'http://ha.test/owner-panel.js',type:'module'});
  await page.evaluate(()=>{
    window.enabled=false;window.calls=[];window.grants=[];
    const panel=document.createElement('solbuddy-owner-panel');document.body.append(panel);
    panel.hass={callApi:async(method,path,data)=>{
      window.calls.push({method,path,data});
      if(path.endsWith('invitations')) return {invitation:'synthetic-invitation',expires_at:'test expiry'};
      if(data.operation==='status') return {guest_enabled:window.enabled,wallet_enabled:window.enabled,https_origin:'https://fphomebuddy.uk',entities:[{entity_id:'light.test',name:'Test lamp'}]};
      if(data.operation==='list') return {grants:window.grants};
      if(data.operation==='create'){const grant={grant_id:'test-grant',guest_display_name:data.payload.guest_display_name,status:'active',expires_at:data.payload.expires_at};window.grants.push(grant);return grant;}
      if(data.operation==='revoke'){window.grants=[];return {};}
    }};
  });
  await page.getByText('Guest access: disabled. Wallet access: disabled.').waitFor();
  assert(await page.getByRole('button',{name:'Approve and create access'}).isDisabled());
  assert.equal(await page.locator('input[type=password]').count(),0);
  checks++;
  await page.evaluate(()=>window.enabled=true);
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await page.getByText('Guest access: enabled. Wallet access: enabled.').waitFor();
  await page.getByLabel('Guest name').fill('<img src=x onerror=alert(1)>');
  await page.getByLabel('Approved Solana wallet').fill('synthetic-wallet');
  await page.getByLabel('Turn off',{exact:true}).uncheck();
  await page.getByLabel('Duration in minutes').fill('5');
  page.on('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Approve and create access'}).click();
  await page.getByText('Access approved. Generate an invitation for the guest.').waitFor();
  const create=await page.evaluate(()=>window.calls.find(c=>c.data.operation==='create'));
  assert.deepEqual(create.data.payload.policies,[{entity_id:'light.test',actions:['turn_on']}]);
  assert.equal(new Date(create.data.payload.expires_at)-new Date(create.data.payload.starts_at),300000);
  assert.equal(await page.locator('img').count(),0);
  await page.getByRole('button',{name:'Generate invitation'}).click();
  assert.equal(await page.locator('#invitation').inputValue(),'synthetic-invitation');
  await page.getByRole('button',{name:'Revoke access'}).click();
  await page.getByText('Access revoked.').waitFor();
  assert.equal(await page.locator('#invitation').inputValue(),'');
  checks++;
  await page.screenshot({path:'/tmp/solbuddy-owner-panel.png',fullPage:true});
  const guest=await browser.newPage();guest.on('pageerror',e=>errors.push(e.message));
  const requests=[];
  await guest.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());requests.push({url:req.url(),body:req.postData()});
    const filename=url.pathname.split('/').pop();
    if(['client.js','connectors.js','freshness.js','wallet.css'].includes(filename)) return route.fulfill({contentType:filename.endsWith('.js')?'application/javascript':'text/css',body:await readFile(new URL(filename,assets),'utf8')});
    if(filename==='ui') return route.fulfill({contentType:'text/html',body:await readFile(new URL('wallet.html',assets),'utf8')});
    if(filename==='challenge') return route.fulfill({contentType:'application/json',body:JSON.stringify({wallet_address:'synthetic-wallet',message:'Synthetic signed challenge'})});
    if(filename==='verify') return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'eligibility_stale',preview:{wallet_verified:true,controls_enabled:false,grant_expires_at:'2030-01-01T12:00:00Z',policies:[{entity_id:'light.test',actions:['turn_on']}]},observations:{price:{status:'stale',age_seconds:62160,max_age_seconds:300},balance:{status:'fresh',age_seconds:5,max_age_seconds:60}}})});
    const response=filename==='info'?{guest_enabled:true,wallet_enabled:true,https_origin:'https://fphomebuddy.uk'}:filename==='claim'?{session_token:'synthetic-session',next_sequence:1,expires_at:'test expiry'}:filename==='permissions'?{policies:[{entity_id:'light.test',actions:['turn_on']}]}:{outcome:'dispatched'};
    return route.fulfill({contentType:'application/json',body:JSON.stringify(response)});
  });
  await guest.goto('http://homeassistant.local:8123/api/solbuddy_access/v1/wallet/ui');
  await guest.getByRole('link',{name:'Open HTTPS wallet sign-in'}).waitFor();
  assert.equal(await guest.getByRole('link',{name:'Open HTTPS wallet sign-in'}).getAttribute('href'),'https://fphomebuddy.uk/api/solbuddy_access/v1/wallet/ui');
  assert(await guest.getByRole('button',{name:'Connect and sign in'}).isHidden());
  await guest.getByLabel('One-time transfer code').fill('sbat_synthetic');
  await guest.getByRole('button',{name:'Use session here'}).click();
  await guest.getByText('Session moved here. Its original expiry is unchanged.').waitFor();
  assert(await guest.getByRole('button',{name:'Turn off',exact:true}).isDisabled());
  await guest.getByRole('button',{name:'Turn on',exact:true}).click();
  await guest.getByText('Command dispatched.').waitFor();
  assert(requests.every(r=>!r.url.includes('sbat_')&&!r.url.includes('synthetic-session')));
  assert.equal(await guest.evaluate(()=>localStorage.length+sessionStorage.length),0);
  assert.deepEqual(errors,[]);
  checks++;
  await guest.screenshot({path:'/tmp/solbuddy-guest-page.png',fullPage:true});
  await guest.addInitScript(()=>{window.phantom={solana:{publicKey:{toString:()=> 'synthetic-wallet'},connect:async()=>{},signMessage:async()=>({signature:new Uint8Array(64)})}};});
  await guest.goto('https://fphomebuddy.uk/api/solbuddy_access/v1/wallet/ui');
  await guest.getByLabel('Owner-issued invitation').fill('synthetic-invitation');
  await guest.locator('#wallet').selectOption({label:'Phantom'});
  await guest.getByRole('button',{name:'Connect and sign in'}).click();
  await guest.getByText('Price observation is stale: 17h 16m old (maximum 5m). No new session was issued. The $2 SBUD requirement is unchanged.').waitFor();
  assert(await guest.locator('#controls').isVisible());
  await guest.getByText('Grant expires: 2030-01-01T12:00:00Z').waitFor();
  assert.equal(await guest.locator('#entity').inputValue(),'light.test');
  assert.match(await guest.locator('#result').textContent(),/light.test: turn on/);
  assert.match(await guest.locator('#walletStatus').textContent(),/Wallet verified/);
  for(const id of ['turn_on','turn_off','renew','transfer','permissions']) assert(await guest.locator('#'+id).isDisabled());
  assert.deepEqual(errors,[]);checks++;
  console.log(`${checks} browser flows passed: disabled/native owner panel, create/invite/revoke, local session import and scoped controls, signed-login stale-price diagnostics.`);
} finally {await browser.close();}
