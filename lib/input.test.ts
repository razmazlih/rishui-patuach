import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizePlate,dataMode,sourceState} from './input';
test('plate normalization retains leading zeros and rejects non digits',()=>{assert.equal(normalizePlate('01-234 567'),'01234567');assert.equal(normalizePlate('1234567'),'1234567');for(const v of ['123','1'.repeat(33),'1234567x','١٢٣٤٥٦٧'])assert.equal(normalizePlate(v),null)});
test('mode never falls back',()=>{assert.equal(dataMode('live'),'live');assert.throws(()=>dataMode('other'))});
test('absence does not establish safety',()=>{assert.equal(sourceState({availability:'available',active_run_id:null,coverage:{},updated_at:new Date()},false),'not_loaded');assert.equal(sourceState({availability:'unavailable',active_run_id:1,coverage:{},updated_at:new Date()},false),'unavailable')});
test('fresh ingestion cannot make old source data fresh',()=>{assert.equal(sourceState({availability:'available',active_run_id:1,coverage:{as_of:'2000-01',stale_after_days:90},updated_at:new Date()},true),'stale')});
test('coverage absence is explicit',()=>{assert.equal(sourceState({availability:'available',active_run_id:1,coverage:{covered:false},updated_at:new Date()},false),'not_covered')});
