import test from 'node:test';
import assert from 'node:assert/strict';
import {formatReportedPeriod} from './presentation';
import {technicalLabel,technicalCategory} from './source-labels';
test('reported quarter is displayed as a quarter with no fabricated day',()=>{
 assert.equal(formatReportedPeriod('2024-Q2'),'רבעון 2, 2024');
 assert.equal(formatReportedPeriod('2024-05'),'2024-05');
 assert.equal(formatReportedPeriod(null),'לא נמסר');
});
test('technical source fields remain clearly attributed and categorized',()=>{
 assert.equal(technicalCategory('CO2_WLTP'),'פליטות ונתוני סביבה');
 assert.equal(technicalCategory('abs_ind'),'בטיחות ואבזור');
 assert.equal(technicalLabel('unknown_code'),'נתון מקור: unknown_code');
});
