import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as csv from '../src/domain/csv.ts';
import {evidenceTags,itemCoverage} from '../src/domain/presentation.ts';
import {passwordRules} from '../src/domain/password.ts';
const enc=t=>new TextEncoder().encode(t);
const MB=10*1024*1024;
test('File inspection detects schema by content, counts rows and keeps leading zeros untouched',()=>{
 const items='﻿'+[...csv.ITEM_COLUMNS].reverse().join(';')+'\r\n'+Array.from({length:200},()=>'27.32;"Кабель; 2,5";007').join('\r\n');
 const info=csv.inspectCSVBytes(enc(items),MB);assert.equal(info.kind,'items');assert.equal(info.rows,200);
 assert.equal(csv.inspectCSVBytes(enc(csv.NOTICE_COLUMNS.join(',')+'\n'+csv.NOTICE_COLUMNS.map(()=>'0').join(',')),MB).kind,'notices');
});
test('File inspection explains encoding, Excel, size, empty and unknown schema with a fix',()=>{
 const problem=bytes=>{try{csv.inspectCSVBytes(bytes,MB);}catch(e){assert.ok(e instanceof csv.CSVFileError);assert.ok(e.problem.fix.length>10);return e.problem;}assert.fail('no error');};
 assert.match(problem(new Uint8Array([0x6c,0x6f,0x74,0x3b,0xcf,0xee])).title,/UTF-8/);
 assert.match(problem(new Uint8Array([0x50,0x4b,3,4,0,0])).detail,/Excel/);
 assert.match(problem(new Uint8Array(0)).title,/пуст/);
 assert.match(problem(new Uint8Array(MB+1).fill(65)).title,/больше/);
 assert.match(problem(enc('lot_id;product_name;okpd\n1;a;b')).detail,/okpd2_code/);
 assert.match(problem(enc('lot_id;name;okpd\n1;a;b')).detail,/файл позиций/);
 assert.match(problem(enc('lot_id;subject;publish_date\n1;a;b')).detail,/файл закупок/);
 assert.match(problem(enc(csv.ITEM_COLUMNS.join(';')+'\n')).title,/только заголовки/);
});
const rec=(evidence,extra={})=>({company:{id:'inn:1',sources:[],role:{role:'unknown',verified:false}},rank:1,score:.99,evidence,...extra});
test('Evidence tags follow stored evidence only and never claim reliability',()=>{
 const tags=evidenceTags(rec([{itemId:'1',kind:'history',technicalStatus:'unknown'},{itemId:'2',kind:'none'}])).map(t=>t.label);
 assert.deepEqual(tags,['Есть опыт похожих закупок','Нужно уточнить характеристики']);
 const conflict=evidenceTags(rec([{itemId:'1',kind:'catalog',technicalStatus:'conflict'},{itemId:'2',kind:'catalog',technicalStatus:'match'}]));
 assert.ok(conflict.some(t=>t.tone==='warning'&&/Противоречия.*1/.test(t.label)));assert.ok(conflict.some(t=>/совпадения характеристик: 1/.test(t.label)));
 const a=evidenceTags(rec([{itemId:'1',kind:'history'}])),b=evidenceTags(rec([{itemId:'1',kind:'history'}],{rank:500,score:.0001}));assert.deepEqual(a,b);
 for(const t of [...tags,...conflict.map(t=>t.label)])assert.ok(!/надёжн|безопас|гарант|%/i.test(t));
 assert.ok(conflict.every(t=>t.tone!=='success'));
});
test('Coverage counts items with evidence without reordering',()=>{const c=itemCoverage(rec([{itemId:'1',kind:'history'},{itemId:'2',kind:'none'},{itemId:'3',kind:'catalog',technicalStatus:'conflict'}]),200);assert.deepEqual(c,{total:200,withEvidence:2,history:1,catalog:1,matched:0,conflicts:1});});
test('Password rules mirror server length and numeric validators before submit',()=>{
 assert.equal(passwordRules('short')[0].met,false);assert.equal(passwordRules('123456789012345')[1].met,false);
 assert.equal(passwordRules('ivan.petrov-secret-123','ivan.petrov@example.ru')[2].met,false);
 assert.ok(passwordRules('a-long-unique-pass-phrase','x@y.ru','Анна').slice(0,3).every(r=>r.met));
});
test('UI source has no browser alert/confirm dialogs and no raw stack traces',()=>{
 const scan=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?scan(new URL(e.name+'/',dir)):/\.tsx?$/.test(e.name)?[new URL(e.name,dir)]:[]);
 for(const file of scan(new URL('../src/',import.meta.url))){const text=fs.readFileSync(file,'utf8');assert.ok(!/\b(window\.)?(alert|confirm|prompt)\(/.test(text),file.pathname);assert.ok(!/\b(error|err|e|cause)\.stack\b/.test(text),file.pathname);}
});
test('Glued quoted header is repaired only when data rows prove the schema; data lines unchanged',()=>{
 const cols=[...csv.NOTICE_COLUMNS];const head=cols.map(c=>`"${c}"`).join(';').replace('"reqnum";"procedure_name"','"reqnum;procedure_name"');
 const rows=['2026-01-23;1;0042;10.00;;Имя;Предмет;1;7800000000;780001001;ЭМ','2026-01-24;2;0043;;;Имя 2;Предмет 2;0;7800000001;780001001;ЭМ'];
 const text='﻿'+head+'\r\n'+rows.join('\r\n');
 let problem;try{csv.inspectCSVBytes(enc(text),MB);}catch(e){problem=e.problem;}
 assert.match(problem.title,/склеены/);assert.ok(problem.repairedText);
 assert.equal(csv.inspectCSVBytes(enc(problem.repairedText),MB).kind,'notices');
 assert.deepEqual(problem.repairedText.split('\r\n').slice(1),rows);
 assert.equal(csv.repairGluedHeader('﻿'+head+'\r\n'+rows[0].split(';').slice(0,10).join(';')),null);
});
import {assessCandidate} from '../src/domain/assessment.ts';
const comp=(extra={})=>({id:'inn:1',inn:'1',sources:[],history:[],role:{role:'unknown',verified:false},...extra});
const prof=(fields)=>({fields:Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v,status:'verified',sourceIds:['s']}])),sources:[]});
test('Assessment: missing data lowers score, evidence and verified facts raise it, rank/score ignored, max 10',()=>{
 const items=[{id:'1',name:'a',okpd2:'33.13.12.000'},{id:'2',name:'b',okpd2:'33.13.12.000'}];
 const empty=assessCandidate({company:comp(),evidence:[],rank:1,score:9},items,new Date('2026-10-02'));
 const rich=assessCandidate({company:comp({currentProfile:{...prof({name:'ООО А',ogrn:'1',region:'СПб',kpp:'1',website:'https://a.ru',contacts:['a@a.ru']}),historyStats:{lotCount:120,winnerLotCount:50}},historySummary:{lotCount:120,lastSeen:'2026-06-01',topCategories:[{code:'33.13.12.000',lotCount:40}]}}),evidence:[{itemId:'1',kind:'history',technicalStatus:'match'},{itemId:'2',kind:'history',technicalStatus:'match'}],rank:9,score:.001},items,new Date('2026-10-02'));
 assert.ok(empty.score<2,String(empty.score));assert.ok(rich.score>8.5&&rich.score<=10,String(rich.score));
 assert.equal(empty.level.label,'Почти нет сведений');assert.ok(empty.gaps.length>=4);
 assert.equal(rich.factors.reduce((n,f)=>n+f.max,0),10);
 const same=assessCandidate({...{company:comp(),evidence:[]},rank:500,score:0},items,new Date('2026-10-02'));assert.equal(same.score,empty.score);
 for(const t of [...rich.strengths,...rich.gaps,rich.level.label])assert.ok(!/надёжн|вероятност|гарант/i.test(t),t);
});
