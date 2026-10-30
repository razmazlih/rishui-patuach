import test from 'node:test';
import assert from 'node:assert/strict';
import {paddedLookup,emptyGroupState} from './lookup';
import type {Source} from './report';
const source=(props:Partial<Source>):Source=>({id:'test',name:'test',kind:'vehicles',updated_at:'2026-10-01',availability:'available',active_run_id:'1',official_url:null,coverage:{},state:'not_found',...props});
test('only explicit live seven digit input gets one lookup alias',()=>{
 assert.equal(paddedLookup('1234567','live'),'01234567');
 assert.equal(paddedLookup('0123456','live'),'00123456');
 assert.equal(paddedLookup('01234567','live'),null);
 assert.equal(paddedLookup('1234567','demo'),null);
 assert.equal(paddedLookup('123','live'),null);
});
test('a held source cannot make searched active sources appear globally blocked',()=>{
 const held=source({availability:'blocked',active_run_id:null,state:'quality_failed'});
 assert.equal(emptyGroupState([source({}),held]),'not_found');
 assert.equal(emptyGroupState([held]),'quality_failed');
 assert.equal(emptyGroupState([]),'not_loaded');
 assert.equal(emptyGroupState([source({availability:'unavailable',state:'unavailable'})]),'unavailable');
});
