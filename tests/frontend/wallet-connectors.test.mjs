import test from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPairSync, sign, verify} from 'node:crypto';
import {registry} from '../../custom_components/solbuddy_access/www/connectors.js';

for (const [name, property] of [['Phantom','phantom'], ['Solflare','solflare'], ['Trust Wallet','trustwallet']]) {
  test(`${name}: selected provider signs exact challenge, no transaction`, async () => {
    const scope = new EventTarget();
    const {privateKey,publicKey} = generateKeyPairSync('ed25519');
    const provider = {publicKey:{toString:()=> 'approved-wallet'}, async connect(){}, async signMessage(bytes) {
      return {signature:new Uint8Array(sign(null,bytes,privateKey))};
    }};
    scope[property] = property === 'solflare' ? provider : {solana:provider};
    const list = registry(scope)();
    assert.equal(list.length,1); assert.equal(list[0].name,name);
    const connected = await list[0].connect();
    assert.equal(connected.address,'approved-wallet');
    const signature = await connected.sign('SOLBUDDY non-transaction challenge');
    assert.equal(verify(null,Buffer.from('SOLBUDDY non-transaction challenge'),publicKey,signature),true);
    provider.publicKey = {toString:()=> 'changed-wallet'};
    await assert.rejects(connected.sign('new challenge'),/changed/);
  });
}

for (const name of ['Phantom','Solflare','Trust Wallet']) {
  test(`${name}: Wallet Standard discovery and signed-message validation`, async () => {
    const scope = new EventTarget();
    let altered = false;
    const account = {address:'approved-wallet',chains:['solana:mainnet'],features:['solana:signMessage']};
    const wallet = {name,features:{'standard:connect':{connect:async()=>({accounts:[account]})}, 'solana:signMessage':{signMessage:async({message})=> [{signedMessage:altered ? new Uint8Array(1) : message,signature:new Uint8Array(64)}]}}};
    scope.addEventListener('wallet-standard:app-ready', event => event.detail.register(wallet));
    const get = registry(scope); const found = get(); assert.equal(found.length,1);
    const connected = await found[0].connect(); await connected.sign('challenge');
    altered = true; await assert.rejects(connected.sign('challenge'),/unexpected/);
    account.chains = ['solana:devnet']; await assert.rejects(found[0].connect(),/mainnet/);
  });
}

test('multiple injected extensions stay distinct and unsupported wallets do not fall back to transactions',()=>{
  const scope = new EventTarget();
  const provider = {connect:async()=>{}, signMessage:async()=>new Uint8Array(64)};
  scope.phantom={solana:provider}; scope.solflare=provider; scope.trustwallet={solana:provider};
  assert.deepEqual(registry(scope)().map(w=>w.name),['Phantom','Solflare','Trust Wallet']);
  scope.phantom.solana={connect:async()=>{},signTransaction:()=>assert.fail('transaction requested')};
  assert.deepEqual(registry(scope)().map(w=>w.name),['Solflare','Trust Wallet']);
});
