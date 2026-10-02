import copy
import hashlib
import json
from datetime import timedelta
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from .models import SourceRefreshJob, SourceEvidenceBlob, LiveSupplierProfile, User, Query
from .source_jobs import enqueue_inns, claim, heartbeat, finish, run_one
from .company_profiles import current_profiles, offline_profiles
from .test_company_profiles import catalog_record, INN
from .test_jobs import snapshot
from .services import parse_import, save_import
from .tests import PASSWORD, pair, send

class SourceQueueTests(TransactionTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'profiles.json'
        row=catalog_record();row['fields']['website']={'value':'https://example.org','status':'verified','sourceIds':['official:1']}
        self.path.write_text(json.dumps({'schemaVersion':'supplier-profile.v1','version':'test-source-v1','generatedAt':'2026-10-02','profiles':[row]}))
        self.override=override_settings(COMPANY_PROFILE_CATALOG=self.path);self.override.enable()
    def tearDown(self):self.override.disable();self.tmp.cleanup()
    def result(self):
        body=b'<html>Verified company</html>';digest=hashlib.sha256(body).hexdigest();at=timezone.now().isoformat()
        profile=offline_profiles([INN])[INN]
        profile['sources'].append({'id':'live:test','url':'https://example.org/company','contentHash':digest,'identityVerified':True,'identityInn':INN,'fetchedAt':at,'scope':'fresh_official_page'})
        profile['fields']['contacts']={'value':[{'kind':'email','value':'office@example.org','sourceIds':['live:test']}],'status':'verified','sourceIds':['live:test'],'observedAt':at}
        return {'status':'complete','profile':profile,'pages':[{'body':body,'contentHash':digest,'url':'https://example.org/company','fetchedAt':at}],'message':'Проверено'}
    def test_queue_is_network_free_deduplicated_and_cooldown_bounded(self):
        with patch('api.source_fetch.refresh_profile',side_effect=AssertionError('queue must not fetch')):
            enqueue_inns([INN]);enqueue_inns([INN],force=True)
        self.assertEqual(SourceRefreshJob.objects.count(),1)
        job=claim();finish(job.pk,job.lease_token,self.result())
        self.assertEqual(SourceEvidenceBlob.objects.count(),1)
        self.assertEqual(LiveSupplierProfile.objects.count(),1)
        enqueue_inns([INN],force=True);self.assertIsNone(claim())
        self.assertEqual(current_profiles([INN])[INN]['fields']['contacts']['value'][0]['value'],'office@example.org')
    def test_no_official_site_is_honest_needs_source_without_work(self):
        rows=enqueue_inns(['500100732259'])
        self.assertEqual(rows[0]['status'],'needs_source');self.assertIsNone(claim())
        self.assertFalse(SourceEvidenceBlob.objects.exists())
    def test_expired_worker_cannot_commit_evidence_or_profile(self):
        enqueue_inns([INN]);old=claim()
        SourceRefreshJob.objects.filter(pk=old.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        new=claim();self.assertNotEqual(old.lease_token,new.lease_token)
        self.assertFalse(heartbeat(old.pk,old.lease_token))
        self.assertFalse(finish(old.pk,old.lease_token,self.result()));self.assertFalse(SourceEvidenceBlob.objects.exists())
        self.assertTrue(finish(new.pk,new.lease_token,self.result()))
    def test_invalid_hash_rolls_back_and_unconfirmed_preserves_verified_profile(self):
        enqueue_inns([INN]);job=claim();result=self.result();broken=copy.deepcopy(result);broken['pages'][0]['contentHash']='0'*64
        with self.assertRaises(ValueError):finish(job.pk,job.lease_token,broken)
        self.assertFalse(SourceEvidenceBlob.objects.exists());self.assertFalse(LiveSupplierProfile.objects.exists())
        finish(job.pk,job.lease_token,result);saved=LiveSupplierProfile.objects.get(pk=INN).profile
        SourceRefreshJob.objects.filter(pk=job.pk).update(checked_at=timezone.now()-timedelta(days=2))
        enqueue_inns([INN]);job=claim();finish(job.pk,job.lease_token,{'status':'unconfirmed','profile':None,'pages':[],'message':'ИНН не подтверждён'})
        self.assertEqual(LiveSupplierProfile.objects.get(pk=INN).profile,saved)
    def test_storage_cap_prevents_partial_profile_commit(self):
        enqueue_inns([INN]);job=claim()
        with patch('api.source_jobs.MAX_STORED_BYTES',0):finish(job.pk,job.lease_token,self.result())
        self.assertFalse(SourceEvidenceBlob.objects.exists());self.assertFalse(LiveSupplierProfile.objects.exists())
        self.assertEqual(SourceRefreshJob.objects.get(pk=job.pk).status,'queued')
    def test_source_endpoint_scope_and_immutable_query(self):
        user=User.objects.create_user('sources@example.test',PASSWORD,name='Источники')
        other=User.objects.create_user('sources-other@example.test',PASSWORD,name='Другой')
        data,_=save_import(user,parse_import(pair()));q=Query.objects.get(pk=data['queryIds'][0]);q.result=snapshot(q);q.completed_at=timezone.now();q.save();original=copy.deepcopy(q.result)
        self.client.force_login(other)
        self.assertEqual(self.client.get('/api/v1/source-jobs?queryId='+str(q.pk)).status_code,404)
        self.assertEqual(send(self.client,'source-jobs',{'queryId':str(q.pk)}).status_code,404)
        self.client.force_login(user)
        self.assertEqual(send(self.client,'source-jobs',{'queryId':str(q.pk),'url':'http://localhost'}).status_code,422)
        self.assertEqual(send(self.client,'source-jobs',{'queryId':str(q.pk)}).status_code,202)
        self.assertEqual(self.client.get('/api/v1/source-jobs?queryId='+str(q.pk)).status_code,200)
        q.refresh_from_db();self.assertEqual(q.result,original)
    def test_worker_calls_bounded_fetch_and_commits_result(self):
        enqueue_inns([INN])
        with patch('api.source_fetch.refresh_profile',return_value=self.result()) as fetch:
            self.assertTrue(run_one());self.assertEqual(fetch.call_args.args[0]['inn'],INN)
        self.assertEqual(SourceRefreshJob.objects.get(inn=INN).status,'complete')
