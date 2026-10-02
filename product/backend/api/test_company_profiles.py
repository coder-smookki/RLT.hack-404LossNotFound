import copy
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.test import TransactionTestCase, TestCase, override_settings
from pypdf import PdfReader
from .company_profiles import current_profiles, validate_profile, attach_company_profiles
from .models import User, Query
from .services import save_import, parse_import, query_json, companies_for, prepare_export, export_bytes
from .jobs import enqueue, claim_job, finish
from .test_jobs import snapshot
from .tests import PASSWORD, pair
from .presentation import recommendation

INN='7707083893'

def catalog_record(name='Подтвержденная компания', inn=INN):
    return {'inn':inn,'fields':{'name':{'value':name,'status':'verified','sourceIds':['official:1']},
            'ogrn':{'value':'1027700132195','status':'verified','sourceIds':['official:1']}},
            'sources':[{'id':'official:1','url':'https://example.org/company','identityInn':inn,
                        'identityVerified':True,'contentHash':'a'*64,'scope':'registry_identity',
                        'title':'Проверенный источник','excerpt':'ИНН '+inn,'contentDate':'2026-09-27'}]}

def write_catalog(path, name='Подтвержденная компания', version='test-v1'):
    Path(path).write_text(json.dumps({'schemaVersion':'supplier-profile.v1','version':version,
        'generatedAt':'2026-10-02T11:00:00Z','profiles':[catalog_record(name)]},ensure_ascii=False))

class ProfileBoundaryTests(TestCase):
    def test_verified_field_requires_matching_identity_and_hash(self):
        for mutation in [lambda r:r['sources'][0].update(identityInn='500100732259'),
                         lambda r:r['sources'][0].update(contentHash=None),
                         lambda r:r['fields']['name'].update(sourceIds=['missing'])]:
            raw=catalog_record();mutation(raw)
            value=validate_profile(raw,'v1','b'*64,'2026-10-02')
            self.assertEqual(value['fields']['name']['status'],'unverified')
            company={'inn':INN,'name':'ИНН '+INN}
            with patch('api.company_profiles.current_profiles',return_value={INN:value}):
                attach_company_profiles([company])
            self.assertEqual(company['displayName'],'ИНН '+INN)

    def test_unknown_identity_and_unsafe_website_never_filled(self):
        raw=catalog_record();raw['fields']['website']={'value':'javascript:alert(1)','status':'verified','sourceIds':['official:1']}
        value=validate_profile(raw,'v1','b'*64,'2026-10-02')
        self.assertEqual(value['fields']['website']['status'],'unknown')
        self.assertEqual(value['legalStatus']['status'],'unknown')
        self.assertEqual(value['fields']['contacts']['status'],'unknown')

    def test_catalog_failure_invalidates_verified_current_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'profiles.json';write_catalog(path)
            with override_settings(COMPANY_PROFILE_CATALOG=path):
                self.assertEqual(current_profiles([INN])[INN]['fields']['name']['status'],'verified')
                path.write_text('{broken')
                value=current_profiles([INN])[INN]
                self.assertEqual(value['fields']['name']['status'],'unknown')
                self.assertEqual(value['catalogStatus'],'invalid')

    def test_business_explanation_uses_actual_signals_and_keeps_score(self):
        candidate={'supplier_inn':INN,'scoring':{'score':0.015},'reasons':{'text_association':0.8,'okpd2_association':0.2,'technical_token_overlap':1.0,'neighbor_lot_evidence':0.03}}
        value=recommendation(candidate,0)
        self.assertEqual(value['score'],0.015)
        self.assertEqual({x['code'] for x in value['explanationCriteria']},{'similar_items','related_category','shared_designations','similar_procurements'})
        self.assertNotIn('nnPU',value['reason']);self.assertNotIn('%',value['explanationSummary'])
        self.assertNotIn('related_category',{x['code'] for x in recommendation({'supplier_inn':INN,'reasons':{'okpd2_association':0}},0)['explanationCriteria']})

class ProfileSnapshotTests(TransactionTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'profiles.json';write_catalog(self.path)
        self.override=override_settings(COMPANY_PROFILE_CATALOG=self.path);self.override.enable()
        self.user=User.objects.create_user('profile@example.test',PASSWORD,name='Профиль')
        self.other=User.objects.create_user('profile-other@example.test',PASSWORD,name='Другой')
        data,_=save_import(self.user,parse_import(pair()));self.q=Query.objects.get(pk=data['queryIds'][0])
    def tearDown(self):
        self.override.disable();self.tmp.cleanup()
    def complete(self):
        enqueue(self.user,[self.q]);job=claim_job();raw=snapshot(self.q)
        finish(job.pk,job.lease_token,result=raw);self.q.refresh_from_db()
        return raw
    def test_current_profile_refresh_does_not_mutate_calculation_or_rank(self):
        raw=self.complete();frozen=copy.deepcopy(self.q.company_profiles)
        write_catalog(self.path,'Обновлённое имя','test-v2')
        output=query_json(self.q);company=output['recommendations'][0]['company']
        self.assertEqual(company['profileAtCalculation']['fields']['name']['value'],'Подтвержденная компания')
        self.assertEqual(company['currentProfile']['fields']['name']['value'],'Обновлённое имя')
        self.assertEqual(company['displayName'],'Обновлённое имя')
        self.assertEqual(output['recommendations'][0]['score'],0.014)
        self.q.refresh_from_db();self.assertEqual(self.q.result,raw);self.assertEqual(self.q.company_profiles,frozen)
        self.assertEqual(companies_for(self.other),[])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/api/v1/companies/inn:'+INN+'?queryId='+str(self.q.pk)).status_code,404)
    def test_old_query_gets_current_profile_without_fake_calculation_snapshot(self):
        self.q.result=snapshot(self.q);self.q.save(update_fields=['result'])
        company=query_json(self.q)['recommendations'][0]['company']
        self.assertIsNone(company['profileAtCalculation'])
        self.assertEqual(company['displayName'],'Подтвержденная компания')
        self.q.refresh_from_db();self.assertEqual(self.q.company_profiles,{})
    def test_business_pdf_csv_snapshot_is_offline_deterministic_and_hides_scores(self):
        self.complete()
        payload={'queryId':str(self.q.pk),'resultVersion':self.q.result_version,'format':'pdf'}
        record,_=prepare_export(self.user,payload)
        first=export_bytes(record)[0]
        text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(first)).pages)
        self.assertIn('Подтвержденная компания',text);self.assertNotIn('0.014',text);self.assertNotIn('nnPU',text);self.assertNotIn('historical_rank',text)
        write_catalog(self.path,'Следующее имя','test-v3')
        with patch('socket.create_connection',side_effect=AssertionError('offline')):
            self.assertEqual(first,export_bytes(record)[0])
        record['format']='csv';csv=export_bytes(record)[0].decode('utf-8-sig')
        self.assertIn('Почему в списке',csv);self.assertNotIn('0.014',csv);self.assertNotIn('pu_logit',csv)
        record['format']='json';self.assertIn(b'0.014',export_bytes(record)[0])

class HistoryAndTaxTests(TestCase):
    def test_legal_status_requires_primary_tax_evidence(self):
        raw=catalog_record()
        raw['fields']['legalStatus']={'value':'Действующая организация','status':'verified','sourceIds':['official:1']}
        self.assertEqual(validate_profile(raw,'v1','b'*64,None)['legalStatus']['status'],'unknown')
        raw['sources'][0].update(url='https://pb.nalog.ru/search.html',scope='official_tax_registry_identity')
        self.assertEqual(validate_profile(raw,'v1','b'*64,None)['legalStatus']['value'],'Действующая организация')

    def test_live_site_name_does_not_override_primary_tax_name(self):
        from .models import LiveSupplierProfile
        from django.utils import timezone
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'profiles.json';raw=catalog_record('Имя ФНС')
            raw['sources'][0].update(url='https://pb.nalog.ru/search.html',scope='official_tax_registry_identity')
            path.write_text(json.dumps({'schemaVersion':'supplier-profile.v1','version':'tax-v2','profiles':[raw]}))
            live=catalog_record('Имя сайта');live['sources'][0]['id']='live:test';live['fields']['name']['sourceIds']=['live:test'];live['fields']['ogrn']['sourceIds']=['live:test']
            profile=validate_profile(live,'live-v1','b'*64,'2026-10-02')
            LiveSupplierProfile.objects.create(inn=INN,profile=profile,checked_at=timezone.now())
            with override_settings(COMPANY_PROFILE_CATALOG=path):
                self.assertEqual(current_profiles([INN])[INN]['fields']['name']['value'],'Имя ФНС')

    def test_history_reads_only_requested_inns_and_never_invents_execution(self):
        import sqlite3
        from .company_history import history_for,diligence
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'history.sqlite'
            con=sqlite3.connect(path);con.execute('CREATE TABLE supplier_history(inn TEXT PRIMARY KEY,payload TEXT)');con.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            payload={'inn':INN,'lotCount':14,'firstSeen':'2024-01-01','lastSeen':'2025-12-31','examples':[{'lotId':'1','subject':'Бумага'}],'scope':'Наблюдаемые участники'}
            con.execute('INSERT INTO supplier_history VALUES (?,?)',(INN,json.dumps(payload)));con.execute('INSERT INTO metadata VALUES (?,?)',('version','history-v1'));con.commit();con.close()
            with override_settings(COMPANY_HISTORY_CATALOG=path):
                self.assertEqual(history_for(['500100732259']),{})
                h=history_for([INN])[INN];self.assertEqual(h['lotCount'],14)
            checks={v['id']:v for v in diligence(None,h)['checks']}
            self.assertEqual(checks['participation']['status'],'observed')
            self.assertEqual(checks['execution']['status'],'unknown');self.assertEqual(checks['rnp']['status'],'unknown')
