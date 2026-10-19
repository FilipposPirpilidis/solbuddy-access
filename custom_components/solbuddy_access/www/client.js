import {registry} from './connectors.js';
const $ = id => document.getElementById(id);
const base = '/api/solbuddy_access/v1/';
const discover = registry();
let wallets = [], session = null, connected = null, allowed = [];
const https = location.protocol === 'https:';
const errors = {eligibility_stale:'Price or balance observation is stale. No new session was issued.',eligibility_unavailable:'Fresh pricing or balance is unavailable. Try again later.',insufficient_sbud:'This wallet holds less than US$2 of SBUD.',invalid_wallet_proof:'Wallet proof expired or does not match the approved wallet.',unauthorized:'Invitation, transfer code, or session is invalid or expired.'};
function status(text) {$('status').textContent=text;}
function forget() {session=null;connected=null;$('controls').hidden=true;$('invitation').value='';$('transferCode').value='';$('issuedTransfer').value='';$('transferOutput').hidden=true;}
async function call(path, auth=null, data={}, seq=null, method='POST') {
  const headers = {'Content-Type':'application/json'};
  if(auth) headers.Authorization=auth;
  if(seq!==null) headers['X-Solbuddy-Sequence']=String(seq);
  let response;
  try {response=await fetch(base+path,{method,headers,body:method==='GET'?undefined:JSON.stringify(data),cache:'no-store',credentials:'omit',redirect:'error'});}
  catch {forget();throw new Error('Connection failed. Do not repeat uncertain device commands.');}
  const result=await response.json();
  if(!response.ok) {if(session) forget();throw new Error(errors[result.error]||`Request denied (${response.status}): ${result.error||''}`);}
  return result;
}
function setSession(value) {session={token:value.session_token,next:value.next_sequence};$('controls').hidden=false;$('expiry').textContent='Session expires: '+value.expires_at;}
async function sessionCall(path,data={},method='POST') {
  if(!session) throw new Error('Sign in or import a session first.');
  return call(path,'SolbuddySession '+session.token,data,session.next++,method);
}
function b64(bytes) {return btoa(String.fromCharCode(...bytes));}
function refresh() {
  wallets=discover();$('wallet').replaceChildren(new Option('Select wallet',''));
  wallets.forEach((w,i)=>$('wallet').add(new Option(w.name,String(i))));
  if(!wallets.length) status('No supported wallet found. Use an HTTPS browser tab with Phantom, Solflare or Trust.');
}
function buttons() {
  const policy=allowed.find(p=>p.entity_id===$('entity').value);
  for(const action of ['turn_on','turn_off']) $(action).disabled=!policy?.actions.includes(action);
  $('renew').hidden=!https;
}
async function permissions() {
  const result=await sessionCall('permissions',{},'GET');allowed=result.policies;
  $('entity').replaceChildren(...allowed.map(p=>new Option(p.entity_id,p.entity_id)));
  $('result').textContent=allowed.map(p=>p.entity_id+': '+p.actions.map(a=>a.replaceAll('_',' ')).join(', ')).join('\n');buttons();
}
const actions={refresh,permissions,
  async login() {
    if(!https) throw new Error('Open HTTPS to sign with your wallet.');
    if($('wallet').value==='') throw new Error('Select a wallet.');
    const invitation=$('invitation').value.trim();
    connected=await wallets[Number($('wallet').value)].connect();
    const challenge=await call('wallet/challenge','SolbuddyInvite '+invitation);
    if(connected.address!==challenge.wallet_address) throw new Error('Selected account does not match the owner-approved wallet.');
    setSession(await call('wallet/verify','SolbuddyInvite '+invitation,{signature:b64(await connected.sign(challenge.message))}));
    $('invitation').value='';await permissions();status('Signed in. Your approved controls are available.');
  },
  async renew() {
    if(!https) throw new Error('Renew on HTTPS.');
    const challenge=await sessionCall('wallet/renew-challenge');
    if(!connected) {
      refresh();
      throw new Error('Select your wallet, then click Sign and renew again.');
    }
    if(connected.address!==challenge.wallet_address) throw new Error('Wrong wallet.');
    setSession(await sessionCall('wallet/renew',{signature:b64(await connected.sign(challenge.message))}));status('Renewed after fresh eligibility checks.');
  },
  async transfer() {
    const result=await sessionCall('session/transfer');$('issuedTransfer').value=result.transfer_code;$('transferOutput').hidden=false;
    status('Paste this one-time code into the guest page at the other HA address within two minutes. Do not put it in a URL.');
  },
  async claim() {
    setSession(await call('session/claim','SolbuddyTransfer '+$('transferCode').value.trim()));$('transferCode').value='';await permissions();status('Session moved here. Its original expiry is unchanged.');
  },
  logout(){forget();$('result').textContent='';status('Session forgotten here. Owner revocation invalidates it server-side.');}
};
for(const action of ['turn_on','turn_off']) actions[action]=async()=>{await sessionCall('execute',{entity_id:$('entity').value,action,parameters:{}});status('Command dispatched.');};
for(const [id,action] of Object.entries(actions)) $(id).addEventListener('click',async()=>{
  document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try {await action();} catch(e){status(e.message||'Operation failed.');}
  finally {document.querySelectorAll('button').forEach(b=>b.disabled=false);buttons();}
});
$('entity').addEventListener('change',buttons);
$('wallet').addEventListener('change',async()=>{if(session && $('wallet').value!==''){try{connected=await wallets[Number($('wallet').value)].connect();}catch(e){status(e.message);}}});
window.addEventListener('pagehide',forget);
try {
  const info=await call('wallet/info',null,{},null,'GET');
  if(!info.guest_enabled || !info.wallet_enabled) status('Guest wallet access is disabled. Ask the owner to enable it in SOLBUDDY settings.');
  else {
    $('loginSection').hidden=!https;$('claimSection').hidden=false;
    $('connection').textContent=https?'Connect your approved wallet below.':'Wallet signing requires HTTPS. Open the signing page, sign in there, then move the session back here.';
    if(info.https_origin) {$('signing').href=info.https_origin+'/api/solbuddy_access/v1/wallet/ui';$('signing').hidden=https;}
    else if(!https) status('The owner must open the SOLBUDDY panel through HTTPS once to discover the signing address.');
    if(https) refresh();
  }
}catch(e){status(e.message);}
