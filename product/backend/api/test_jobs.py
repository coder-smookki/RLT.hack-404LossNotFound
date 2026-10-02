"""Queue state, ownership, provenance and concurrent replay invariants."""
import copy
from datetime import timedelta
import hashlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from django.test import TransactionTestCase, Client
from django.db import close_old_connections
from django.utils import timezone
from .models import User, Query, InferenceJob, ExportRecord
from .tests import PASSWORD, pair, send
from .services import parse_import, save_import, query_json
from .jobs import enqueue, claim_job, heartbeat, finish, infer, RuntimeFailure, csv_bytes, ACCEPTED_SELECTION_SHA256
from rlt_lab.data import NOTICE_COLUMNS, ITEM_COLUMNS


def snapshot(q):
    return {'version': 'enriched-csv-v4', 'ranker': 'neighbor35', 'history_cutoff': '2025-01-01',
        'input_sha256': {'notices': hashlib.sha256(csv_bytes(NOTICE_COLUMNS,[q.raw_notice])).hexdigest(),
                         'items': hashlib.sha256(csv_bytes(ITEM_COLUMNS,q.raw_items)).hexdigest()},
        'query_count': 1, 'external_catalog': {'version':'external-evidence-v5', 'recency_window_policy':'advisory'},
        'score_semantics': 'not probabilities', 'lots':[{'lot_id':q.raw_notice['lot_id'], 'notice':q.raw_notice, 'raw_items':q.raw_items,
        'method':'neighbor35_nnpu_fusion', 'feature_version':'p1_neighbor_lot_evidence_v3_35', 'model_selection_sha256':ACCEPTED_SELECTION_SHA256,
        'recommendations':[{'supplier_inn':'7707083893', 'scoring':{'score':0.014},'evidence':[], 'historical_item_evidence':[], 'external_item_evidence':[]}],
        'new_supplier_candidates':[{'supplier_inn':'500100732259','company_name':'Проверка экспорта', 'evidence_retrieval_score':3.0,
        'new_to_full_history':True,'cold_start':True,'item_evidence':[]}]}]}

class QueueTests(TransactionTestCase):
    def setUp(self):
        self.user=User.objects.create_user('queue@example.test',PASSWORD,name='Очередь')
        self.other=User.objects.create_user('other@example.test',PASSWORD,name='Другой')
        data,_=save_import(self.user,parse_import(pair()))
        self.query=Query.objects.get(pk=data['queryIds'][0])
        self.ca=Client(enforce_csrf_checks=True);self.ca.force_login(self.user)
        self.cb=Client(enforce_csrf_checks=True);self.cb.force_login(self.other)

    def test_duplicate_start_and_immutable_completion(self):
        enqueue(self.user,[self.query]);enqueue(self.user,[self.query])
        self.assertEqual(InferenceJob.objects.count(),1)
        job=claim_job(); self.assertEqual(job.status,'running')
        result=snapshot(self.query)
        self.assertTrue(finish(job.pk,job.lease_token,result=result))
        self.query.refresh_from_db();self.assertEqual(self.query.result,result)
        self.assertEqual(query_json(self.query)['status'],'complete')
        enqueue(self.user,[self.query]);self.assertEqual(InferenceJob.objects.count(),1);self.assertIsNone(claim_job())
        self.assertFalse(finish(job.pk,job.lease_token,result={}))
        self.query.refresh_from_db();self.assertEqual(self.query.result,result)

    def test_lease_recovery_fences_old_worker(self):
        enqueue(self.user,[self.query]); first=claim_job()
        InferenceJob.objects.filter(pk=first.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        second=claim_job();self.assertEqual(first.pk,second.pk);self.assertNotEqual(first.lease_token,second.lease_token)
        self.assertFalse(heartbeat(first.pk,first.lease_token))
        self.assertFalse(finish(first.pk,first.lease_token,result=snapshot(self.query)))
        self.assertTrue(finish(second.pk,second.lease_token,result=snapshot(self.query)))

    def test_retryable_failure_and_terminal_failure(self):
        enqueue(self.user,[self.query]);job=claim_job()
        finish(job.pk,job.lease_token,failure=RuntimeFailure('ENGINE_BUSY','Занято'))
        job.refresh_from_db();self.assertEqual(job.status,'queued');self.assertIsNone(claim_job())
        InferenceJob.objects.filter(pk=job.pk).update(available_at=timezone.now()-timedelta(seconds=1))
        job=claim_job();finish(job.pk,job.lease_token,failure=RuntimeFailure('BAD_INPUT','Ошибка',False))
        job.refresh_from_db();self.assertEqual(job.status,'failed')
        self.assertFalse(self.query.result)
        enqueue(self.user,[self.query]);job.refresh_from_db();self.assertEqual(job.status,'queued')

    def test_runtime_input_hash_ranker_and_identity_boundary(self):
        result=snapshot(self.query)
        with patch('api.jobs.runtime_request',return_value=result):
            self.assertEqual(infer(self.query),result)
        for mutate in [lambda r:r.update(ranker='original34'), lambda r:r['input_sha256'].update(items='0'*64),
                       lambda r:r['lots'][0].update(lot_id='different'), lambda r:r['lots'][0].update(raw_items=[]),
                       lambda r:r['lots'][0].update(method='random'), lambda r:r['lots'][0].update(model_selection_sha256='0'*64)]:
            broken=copy.deepcopy(result);mutate(broken)
            with patch('api.jobs.runtime_request',return_value=broken):
                with self.assertRaises(RuntimeFailure) as ctx:infer(self.query)
                self.assertEqual(ctx.exception.code,'ENGINE_PROVENANCE_MISMATCH')

    def test_completed_results_companies_statistics_and_export_are_owned(self):
        enqueue(self.user,[self.query]);job=claim_job();finish(job.pk,job.lease_token,result=snapshot(self.query))
        response=self.ca.get('/api/v1/queries/'+str(self.query.pk));self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(len(data['recommendations']),1);self.assertEqual(len(data['externalCandidates']),1)
        self.assertEqual(data['recommendations'][0]['scoreKind'],'historical_rank')
        self.assertEqual(data['externalCandidates'][0]['score'],3.0)
        self.assertEqual(data['recommendations'][0]['company']['role']['role'],'unknown')
        compact=self.ca.get('/api/v1/queries').json()[0]
        self.assertTrue(compact['isSummary']);self.assertIsNone(compact['runtimeResult'])
        self.assertNotIn('rawEvidence',compact['recommendations'][0]);self.assertEqual(compact['rawItems'],[])
        self.assertEqual(data['rawItems'],self.query.raw_items)
        for path in ['queries/'+str(self.query.pk), 'companies/inn:7707083893?queryId='+str(self.query.pk)]:
            self.assertEqual(self.cb.get('/api/v1/'+path).status_code,404)
        self.assertEqual(self.cb.get('/api/v1/companies').json(),[])
        self.assertEqual(self.ca.get('/api/v1/analytics').json()['inn'],2)
        self.assertEqual(self.cb.get('/api/v1/analytics').json()['inn'],0)
        payload={'queryId':str(self.query.pk),'resultVersion':data['resultVersion'],'format':'csv','companyIds':['inn:500100732259']}
        exported=send(self.ca,'exports',payload,key='result-export-key')
        self.assertEqual(exported.status_code,200,exported.content)
        self.assertIn(b'500100732259',exported.content);self.assertNotIn(b'7707083893',exported.content)
        self.assertEqual(exported.content,send(self.ca,'exports',payload,key='result-export-key').content)
        payload['format']='json'
        first=send(self.ca,'exports',payload,key='result-json-replay')
        self.assertEqual(first.content,send(self.ca,'exports',payload,key='result-json-replay').content)
        payload['companyIds']=['inn:0000000000'];self.assertEqual(send(self.ca,'exports',payload,key='bad-selection-key').status_code,422)
        payload['companyIds']=[];payload['resultVersion']='input-v1'
        self.assertEqual(send(self.ca,'exports',payload,key='old-version-key').status_code,409)
        self.assertEqual(ExportRecord.objects.count(),2)

    def test_concurrent_start_and_claim_only_one_active_job(self):
        def start(_):
            close_old_connections()
            try:
                user=User.objects.get(pk=self.user.pk);q=Query.objects.get(pk=self.query.pk)
                return str(enqueue(user,[q])[0].pk)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(start,range(2)))
        self.assertEqual(InferenceJob.objects.count(),1)
        def claim(_):
            close_old_connections()
            try:
                job=claim_job();return str(job.pk) if job else None
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(claim,range(2)))
        self.assertEqual(sum(x is not None for x in values),1)

    def test_manual_input_cannot_bypass_two_csv_requirement(self):
        q=Query.objects.create(owner=self.user,procurement={'items':[]})
        response=send(self.ca,'queries/'+str(q.pk)+'/start')
        self.assertEqual(response.status_code,422);self.assertEqual(response.json()['error']['code'],'CSV_INPUT_REQUIRED')

    def test_no_external_evidence_does_not_hide_historical_conflict(self):
        from .presentation import recommendation
        candidate={'supplier_inn':'7707083893','scoring':{'score':0.1},'evidence':[],
            'external_item_evidence':[{'item_index':0,'matches':[],'coverage':'no_matching_external_evidence'}],
            'historical_item_evidence':[{'item_index':0,'historical_fragments':[{'lot_id':'12',
              'technical_comparison':{'status':'conflict','attributes':[{'status':'conflict','query_attribute':{'raw':'5 л'}}]}}]}]}
        value=recommendation(candidate,0)
        self.assertEqual(len(value['evidence']),1)
        self.assertEqual(value['evidence'][0]['kind'],'history')
        self.assertEqual(value['evidence'][0]['technicalStatus'],'conflict')
        self.assertIn('5 л',value['evidence'][0]['reason'])
