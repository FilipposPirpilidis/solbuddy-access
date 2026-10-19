import test from 'node:test';
import assert from 'node:assert/strict';
import {freshnessMessage} from '../../custom_components/solbuddy_access/www/freshness.js';
const observation=(status,age_seconds,max_age_seconds)=>({status,age_seconds,max_age_seconds});
test('shows price source age and unchanged rejection threshold',()=>{
  assert.match(freshnessMessage({error:'eligibility_stale',observations:{price:observation('stale',62160,300)}}),/Price observation is stale: 17h 16m old \(maximum 5m\)/);
});
test('shows balance age and both failures without hiding either',()=>{
  const text=freshnessMessage({error:'eligibility_stale',observations:{price:observation('stale',301,300),balance:observation('stale',92,60)}});
  assert.match(text,/Price observation is stale: 5m 1s/);
  assert.match(text,/Balance observation is stale: 1m 32s old \(maximum 1m\)/);
  assert.match(text,/No new session was issued/);
});
test('future timestamp is not mislabeled as an old observation',()=>{
  assert.match(freshnessMessage({error:'eligibility_stale',observations:{balance:observation('future',-2,60)}}),/Balance observation is 2s ahead of the server clock/);
});
test('invalid details and legacy responses use generic fallback',()=>{
  assert.equal(freshnessMessage({error:'eligibility_stale'}),null);
  assert.equal(freshnessMessage({error:'unauthorized',observations:{price:observation('stale',800,300)}}),null);
  for(const age of ['<img>',NaN,Infinity,true,300]) assert.equal(freshnessMessage({error:'eligibility_stale',observations:{price:observation('stale',age,300)}}),null);
});
