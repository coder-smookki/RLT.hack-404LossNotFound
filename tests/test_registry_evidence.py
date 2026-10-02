from datetime import date
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from rlt_lab.registry_evidence import load_registry_batch

ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/'local/colleague-enrichment-2026-10-02/registry_companies.json'
SHA='7b8a333faca3ec8e193d05e76afb47e4e1cf7e48740f04c9cb699601453ba3a5'
TOKENIZE=lambda text:re.findall(r'\w+',text.casefold())

@unittest.skipUnless(BATCH.exists(),'Local authoritative snapshot is not present')
class RegistryEvidenceTests(unittest.TestCase):
    def test_actual_batch_preserves_license_limits_and_company_counts(self):
        profiles,meta=load_registry_batch(BATCH,SHA,TOKENIZE,date(2026,10,2))
        self.assertEqual(len(profiles),500)
        self.assertEqual(len({p['inn'] for p in profiles}),500)
        self.assertEqual(meta['companies_already_in_previous_external_catalog'],1)
        self.assertEqual(meta['source_counts'],{'medical_service':250,'pharma':250})
        self.assertTrue(all(p['verified_registry'] and not p['verified_page'] for p in profiles))
        self.assertTrue(all(p['freshness']['source_published_at'] is None for p in profiles))
        self.assertTrue(all(p['registry_evidence']['validated_okpd']==[] for p in profiles))
        self.assertTrue(all(p['claim_type']=='licensed_category_capability' for p in profiles))
        self.assertEqual(meta['independent_msp_confirmations'],0)

    def test_missing_or_modified_batch_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'batch hash'):
            load_registry_batch(BATCH,'0'*64,TOKENIZE,date(2026,10,2))

    def test_future_observation_is_quarantined_but_age_alone_is_not(self):
        profiles,meta=load_registry_batch(BATCH,SHA,TOKENIZE,date(2026,10,1))
        self.assertEqual(meta['quarantined_registry_profiles'],500)
        self.assertTrue(all(not p['quality']['eligible_for_search'] for p in profiles))
        profiles,meta=load_registry_batch(BATCH,SHA,TOKENIZE,date(2030,10,2))
        self.assertEqual(meta['quarantined_registry_profiles'],0)
        self.assertEqual(meta['license_event_within_36_months'],0)
        self.assertTrue(all(p['freshness']['content_recency']=='license_event_before_window' for p in profiles))

    def fixture(self, directory):
        batch=json.loads(BATCH.read_text())
        batch['companies']=[next(c for c in batch['companies'] if c['source_kind']=='medical_service')]
        c=batch['companies'][0]
        target=directory/c['source_payload_path'];target.parent.mkdir(parents=True)
        shutil.copyfile(BATCH.parent/c['source_payload_path'],target)
        return batch,target

    def load_fixture(self,directory,batch):
        path=directory/'batch.json';path.write_text(json.dumps(batch,ensure_ascii=False))
        return load_registry_batch(path,hashlib.sha256(path.read_bytes()).hexdigest(),TOKENIZE,date(2026,10,2))

    def test_payload_corruption_fails_even_when_json_hash_matches(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);batch,payload=self.fixture(directory)
            payload.write_bytes(payload.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'ZIP hash'): self.load_fixture(directory,batch)

    def test_forged_scope_and_adverse_status_fail_closed(self):
        for kind in ('scope','status','traversal','xml'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                directory=Path(d);batch,_=self.fixture(directory);c=batch['companies'][0]
                if kind=='scope': c['scope']='Гарантирована поставка любой модели'
                elif kind=='status': c['record']['status_fields']['termination']='прекращена'
                elif kind=='traversal': c['source_payload_path']='../outside.zip'
                elif kind=='xml': c['record']['raw_xml_reserialized']+='changed'
                with self.assertRaises((ValueError,FileNotFoundError)): self.load_fixture(directory,batch)
