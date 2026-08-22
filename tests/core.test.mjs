import test from'node:test';
import assert from'node:assert/strict';
import{freshnessState,haversineMeters,formatDistanceImperial,sanitizeCallsign,shouldPublishPosition,LIVE_MAX_MS,DELAYED_MAX_MS}from'../core.mjs';

test('freshness transitions are explicit',()=>{
  const now=100000;
  assert.equal(freshnessState(now,now-LIVE_MAX_MS,true).key,'live');
  assert.equal(freshnessState(now,now-LIVE_MAX_MS-1,true).key,'delayed');
  assert.equal(freshnessState(now,now-DELAYED_MAX_MS-1,true).key,'stale');
  assert.equal(freshnessState(now,now-5000,false).key,'delayed');
});

test('distance formatting uses imperial units',()=>{
  assert.match(formatDistanceImperial(30),/ft$/);
  assert.match(formatDistanceImperial(1000),/mi$/);
});

test('callsigns are bounded and sanitized',()=>{
  assert.equal(sanitizeCallsign(' Rescue <1> '),'Rescue 1');
  assert.ok(sanitizeCallsign('A'.repeat(100)).length<=32);
});

test('movement can trigger faster publishing',()=>{
  const a={lat:34,lng:-119,speed_mps:0};
  const b={lat:34.0001,lng:-119,speed_mps:1};
  assert.ok(haversineMeters(a,b)>5);
  assert.equal(shouldPublishPosition(a,b,6000,1),true);
});
