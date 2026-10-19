import {registry} from './connectors.js';
const $ = id => document.getElementById(id);
const base = '/api/solbuddy_access/v1/';
const discover = registry();
let wallets = [], session = null, connected = null;
const errors = {eligibility_stale:'The price or balance observation is stale. No new session was issued.', eligibility_unavailable:'Fresh balance or pricing is unavailable. Try again later.', insufficient_sbud:'This wallet holds less than US$2 of SBUD.', invalid_wallet_proof:'Wallet proof expired, was already used, or does not match the approved wallet.', wallet_proof_required:'A wallet signature is required.', wallet_access_disabled:'Wallet access is disabled.', unauthorized:'Invitation or session is invalid or expired.'};
function status(text) {$('status').textContent = text;}
function output(value) {$('result').textContent = JSON.stringify(value, null, 2);}
function forget() {session = null; connected = null; $('controls').hidden = true; $('invitation').value = '';}
async function call(path, auth, data = {}, seq = null, method = 'POST') {
  const headers = {'Content-Type':'application/json', 'Authorization':auth};
  if (seq !== null) headers['X-Solbuddy-Sequence'] = String(seq);
  let response;
  try {response = await fetch(base + path, {method, headers, body:method === 'GET' ? undefined : JSON.stringify(data), cache:'no-store', credentials:'omit', redirect:'error'});}
  catch {forget(); throw new Error('Connection failed. Do not repeat an uncertain device command; obtain a new invitation.');}
  const result = await response.json();
  if (!response.ok) {
    if (session) forget();
    throw new Error(errors[result.error] || `Request denied (${response.status}). ${result.error || ''}`);
  }
  return result;
}
function b64(bytes) {return btoa(String.fromCharCode(...bytes));}
function setSession(value) {session = {token:value.session_token, next:value.next_sequence}; $('controls').hidden = false; $('expiry').textContent = 'Session expires: ' + value.expires_at;}
async function sessionCall(path, data = {}, method = 'POST') {
  if (!session) throw new Error('Sign in first.');
  return call(path, 'SolbuddySession ' + session.token, data, session.next++, method);
}
function refresh() {
  wallets = discover(); $('wallet').replaceChildren(new Option('Select wallet', ''));
  wallets.forEach((wallet,i) => $('wallet').add(new Option(wallet.name, String(i))));
  if (!wallets.length) status('No supported Solana wallet found. Use an HTTPS top-level page with a supported extension or wallet browser.');
}
async function permissions() {
  const result = await sessionCall('permissions', {}, 'GET');
  $('entity').replaceChildren(); result.policies.forEach(policy => $('entity').add(new Option(policy.entity_id, policy.entity_id))); output(result);
}
const ownerCall = (operation, payload={}) => call('wallet/owner', 'Bearer ' + $('ownerToken').value, {operation,payload});
const actions = {
  refresh,
  async login() {
    if ($('wallet').value === '') throw new Error('Select a wallet.');
    const invitation = $('invitation').value.trim();
    connected = await wallets[Number($('wallet').value)].connect();
    const challenge = await call('wallet/challenge', 'SolbuddyInvite ' + invitation);
    if (connected.address !== challenge.wallet_address) throw new Error('Selected wallet does not match the owner-approved address.');
    const signature = b64(await connected.sign(challenge.message));
    setSession(await call('wallet/verify', 'SolbuddyInvite ' + invitation, {signature}));
    $('invitation').value = ''; await permissions(); status('Signed in. Only your approved controls are available.');
  },
  permissions,
  async renew() {
    if (!connected) throw new Error('Connect the approved wallet again.');
    const challenge = await sessionCall('wallet/renew-challenge');
    if (connected.address !== challenge.wallet_address) throw new Error('Wrong wallet.');
    const signature = b64(await connected.sign(challenge.message));
    setSession(await sessionCall('wallet/renew', {signature})); status('Session renewed with a fresh eligibility check.');
  },
  logout() {forget(); output({}); status('Session forgotten on this device. Owner revocation invalidates it server-side.');},
  clearOwner() {$('ownerToken').value = ''; $('issued').value = ''; $('grants').replaceChildren(); output({}); status('Owner credential cleared.');},
  async create() {
    const hours = Number($('hours').value); if (!Number.isInteger(hours) || hours < 1 || hours > 720) throw new Error('Choose 1–720 hours.');
    const address = $('approvedWallet').value.trim();
    if (!confirm('Approve this wallet for the selected light?\n\n' + address + '\n\n' + $('light').value)) return;
    const now = Date.now();
    const grant = await ownerCall('create', {guest_display_name:$('guestName').value.trim(), wallet_address:address, starts_at:new Date(now).toISOString(), expires_at:new Date(now+hours*3600000).toISOString(), policies:[{entity_id:$('light').value.trim(), actions:['turn_on','turn_off']}]});
    await actions.list(); $('grants').value = grant.grant_id; status('Wallet approved. Generate an invitation to sign in.');
  },
  async list() {
    const {grants} = await ownerCall('list'); $('grants').replaceChildren();
    grants.forEach(g => $('grants').add(new Option(`${g.guest_display_name} · ${g.status} · ${g.wallet_address}`, g.grant_id))); output(grants);
  },
  async issue() {
    const value = await call('invitations', 'Bearer ' + $('ownerToken').value, {grant_id:$('grants').value});
    $('issued').value = value.invitation; status('Transfer this invitation privately. Expires: ' + value.expires_at);
  },
  async revoke() {await ownerCall('revoke',{grant_id:$('grants').value}); $('issued').value=''; await actions.list(); status('Grant revoked.');}
};
for (const action of ['turn_on','turn_off']) actions[action] = async () => {output(await sessionCall('execute',{entity_id:$('entity').value,action,parameters:{}})); status('Request completed. A dispatch receipt does not prove physical device state.');};
for (const [id, action] of Object.entries(actions)) $(id).addEventListener('click', async () => {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  try {await action();} catch(error) {status(error.message || 'Operation failed.');}
  finally {document.querySelectorAll('button').forEach(b => b.disabled = false);}
});
const owner = location.pathname.endsWith('/owner-ui'); $('owner').hidden = !owner; $('guest').hidden = owner; $('heading').textContent = owner ? 'Approve guest wallets' : 'Connect your approved wallet';
window.addEventListener('pagehide', () => {forget(); $('ownerToken').value=''; $('issued').value='';});
if (!owner) refresh();
