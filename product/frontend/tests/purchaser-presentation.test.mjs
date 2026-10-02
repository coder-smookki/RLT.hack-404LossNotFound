import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {companyName,companyLabel,recommendationBasis,verifiedContacts,contactHref} from '../src/domain/presentation.ts';
const company=()=>({id:'inn:001',inn:'001',name:'ИНН 001',history:[],sources:[],role:{role:'unknown',verified:false}});
test('Company names use only verified current facts and never repeat bare INN as title',()=>{
 const c=company();assert.equal(companyName(c),'Название пока не найдено');assert.equal(companyLabel(c),'Контрагент с ИНН 001');
 c.currentProfile={fields:{name:{value:'ООО Проверенное',status:'unverified'}}};assert.equal(companyName(c),'Название пока не найдено');
 c.currentProfile.fields.name.status='verified';assert.equal(companyName(c),'ООО Проверенное');
 c.currentProfile.fields.name.status='conflict';assert.equal(companyName(c),'Название пока не найдено');
});
test('Evidence labels never infer confidence from score or rank; license is not product catalog',()=>{
 const c=company();c.sources=[{title:'Росздравнадзор: запись лицензии'}];
 const r={company:c,evidence:[],score:.99,rank:1};assert.equal(recommendationBasis(r).title,'Есть сведения о лицензии');
 const base=recommendationBasis(r);r.rank=500;r.score=.0001;assert.deepEqual(recommendationBasis(r),base);
 r.evidence=[{kind:'history',technicalStatus:'conflict'}];assert.equal(recommendationBasis(r).title,'Есть противоречия по позициям');
 r.evidence=[{kind:'history',technicalStatus:'unknown'}];assert.equal(recommendationBasis(r).title,'Есть опыт похожих закупок');assert.match(recommendationBasis(r).caution,/Нужно уточнить/);
});
test('Main UI does not render raw ranking scores or internal model identifiers',()=>{
 for(const name of ['Results','Company','Compare','Sources','Export','Help']){
  const source=fs.readFileSync(new URL(`../src/pages/${name}.tsx`,import.meta.url),'utf8');
  for(const token of ['rankingScore','modelVersion','catalogVersion','nnPU','RRF','FTS5','Балл ранжирования','Балл:'])assert.ok(!source.includes(token),`${name}: ${token}`);
 }
});
test('Only source-backed business contacts are exposed and unsafe contact links stay plain text',()=>{
 const c=company();c.currentProfile={fields:{contacts:{status:'unverified',sourceIds:['s1'],value:[{kind:'email',value:'sales@example.test'}]}}};
 assert.deepEqual(verifiedContacts(c),[]);c.currentProfile.fields.contacts.status='verified';
 assert.deepEqual(verifiedContacts(c),[{kind:'email',value:'sales@example.test',sourceIds:['s1']}]);
 assert.equal(contactHref(verifiedContacts(c)[0]),'mailto:sales@example.test');
 assert.equal(contactHref({kind:'email',value:'sales@example.test?bcc=other@example.test'}),undefined);
 assert.equal(contactHref({kind:'email',value:'sales@example.test\nBcc:other@example.test'}),undefined);
 assert.equal(contactHref({kind:'phone',value:'+7 (812) 123-45-67'}),'tel:+78121234567');
 assert.equal(contactHref({kind:'phone',value:'javascript:alert(1)'}),undefined);
 c.currentProfile.fields.contacts.value=['sales@example.test'];assert.deepEqual(verifiedContacts(c),[{kind:'email',value:'sales@example.test',sourceIds:['s1']}]);
});
