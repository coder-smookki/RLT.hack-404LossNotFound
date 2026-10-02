import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as csv from '../src/domain/csv.ts';
import * as fmt from '../src/domain/format.ts';
import * as recommendations from '../src/domain/recommendations.ts';
import * as pagination from '../src/domain/pagination.ts';
test('CSV parser preserves raw dimensions, leading zeroes, quotes and duplicate lines',()=>{const rows=csv.parseCSV('lot_id;product_name;okpd2_code\r\n001;"  Кабель 2,5 мм²; \"\"А\"\"  ";27.32\r\n001;"  Кабель 2,5 мм²; \"\"А\"\"  ";27.32');assert.equal(rows.length,3);assert.equal(rows[1].cells[0],'001');assert.equal(rows[1].cells[1],'  Кабель 2,5 мм²; "А"  ');assert.deepEqual(rows[1].cells,rows[2].cells);});
test('CSV malformed quoting gives actionable line',()=>{assert.throws(()=>csv.parseCSV('lot_id;product_name\n1;"open'),/Не закрыта кавычка/);});
test('Safe external links reject script protocols and embedded credentials',()=>{for(const url of ['javascript:alert(1)','data:text/html,hello','https://u:p@example.org'])assert.equal(fmt.safeURL(url),null);assert.equal(fmt.safeURL('https://example.org/a'),'https://example.org/a');});
test('Unknown dates and amounts never render NaN',()=>{assert.equal(fmt.date(null),'Не указана');assert.equal(fmt.money(null),'Не указана');assert.equal(fmt.date('bad-date'),'Дата требует проверки');});
test('Pagination bounds stale or malformed URL pages',()=>{const rows=Array.from({length:24},(_,i)=>i);assert.equal(pagination.paginate(rows,'999').page,pagination.paginate(rows,'999').pages);assert.equal(pagination.paginate(rows,'-2').page,1);});
test('Production bundle contains no mocks, demos or scenario headers',()=>{const files=fs.readdirSync(new URL('../dist/assets',import.meta.url)).filter(x=>x.endsWith('.js'));const source=files.map(x=>fs.readFileSync(new URL(`../dist/assets/${x}`,import.meta.url),'utf8')).join('');for(const marker of ['q-demo','demo-a','X-Demo-Session','X-UI-Scenario','mockAPI','__scenarios'])assert.ok(!source.includes(marker),marker);});
test('Runtime icons use SVG, not decorative glyphs',()=>{const scan=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?scan(new URL(e.name+'/',dir)):e.name.endsWith('.tsx')?[new URL(e.name,dir)]:[]);for(const file of scan(new URL('../src/',import.meta.url)))assert.ok(!/[↗→←↑↓✓✕⚠🔎📊]/u.test(fs.readFileSync(file,'utf8')),file.pathname);});

test('Both retrieval channels participate in selection without duplicate identities',()=>{const a={company:{id:'inn:1'},evidence:[]},b={company:{id:'inn:2'},evidence:[]};assert.deepEqual(recommendations.allRecommendations({recommendations:[a],externalCandidates:[a,b]}).map(r=>r.company.id),['inn:1','inn:2']);});
test('Catalog presence never implies exact product match and scores are not probabilities',()=>{assert.equal(recommendations.itemStatus({kind:'catalog'}),'unknown');assert.equal(recommendations.evidenceLabel({kind:'catalog',technicalStatus:'conflict'}),'Есть противоречие');assert.equal(recommendations.rankingScore(null),'Не указан');assert.ok(!recommendations.rankingScore(0.75).includes('%'));});

test('Unified CSV upload detects schema instead of filename and preserves all 200 rows',()=>{
 const notices='\uFEFF'+[...csv.NOTICE_COLUMNS].reverse().map(c=>'"'+c+'"').join(';')+'\r\n';
 assert.equal(csv.detectCSVKind(notices),'notices');assert.equal(csv.detectCSVKind(csv.ITEM_COLUMNS.join(',')+'\n1,Товар,27.1'),'items');
 const items='\uFEFF'+csv.ITEM_COLUMNS.join(';')+'\r\n'+Array.from({length:200},()=> '001;"  Услуга; код 2  ";33.13.12.000').join('\r\n');
 assert.equal(csv.detectCSVKind(items),'items');assert.equal(csv.parseCSV(items).length,201);assert.equal(csv.parseCSV(items)[200].cells[1],'  Услуга; код 2  ');
 assert.throws(()=>csv.detectCSVKind('lot_id;name\n1;Test'),/Не удалось определить/);
 assert.throws(()=>csv.detectCSVKind('lot_id;product_name;okpd2_code;okpd2_code'),/Не удалось определить/);
 assert.throws(()=>csv.detectCSVKind(''),/Файл пуст/);
});
