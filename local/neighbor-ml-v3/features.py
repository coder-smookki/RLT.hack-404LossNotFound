"""One new frozen history-only feature; original P1 producer remains unchanged."""
from __future__ import annotations
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
OLD = PROJECT / 'local/pu-ranker/pilot_v1'
STRUCT = PROJECT / 'local/okpd-structure-v2'
FEATURE = 'neighbor_lot_evidence'
VERSION = 'p1_neighbor_lot_evidence_v3_35'
KEYS = ('lot_id','publish_date','subject','customer_inn','source','items','rare','unseen_code','unseen_exact_code','unseen_branch4')

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write_json(path,value):
    path=Path(path); tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    tmp.replace(path)

def load_variants():
    spec=importlib.util.spec_from_file_location('neighbor_v3_frozen_variants',STRUCT/'variants.py')
    v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v);return v

def validate_history(v):
    lock=json.loads((STRUCT/'protocol.lock.json').read_text())
    for key,path in [('baseline_engine',v.BASE),('auxiliary',v.AUXILIARY),('code_support',STRUCT/'code_support.json')]:
        if sha(path)!=lock['input_sha256'][key]:raise ValueError('Frozen history hash changed: '+key)
    if sha(STRUCT/'variants.py')!=lock['code_sha256']['variants.py']:raise ValueError('Neighbor channel changed')
    engine=v.base.Engine(); con=v._state(engine)['con']
    lo,hi,n,unique=con.execute('SELECT min(publish_date),max(publish_date),count(*),count(distinct lot_id) FROM lot_meta').fetchone()
    if lo<'2024-01-01' or hi>'2024-12-31' or n!=unique or not n:raise ValueError('Auxiliary must contain unique 2024 lot documents only')
    if engine.con.execute('SELECT max(publish_date) FROM history_notices').fetchone()[0]>'2024-12-31':raise ValueError('Ancestor includes future history')
    return engine,{'first_date':lo,'last_date':hi,'unique_lots':n,'read_only':True,'baseline_engine_sha256':sha(v.BASE),'variants_sha256':sha(STRUCT/'variants.py'),'auxiliary_sha256':sha(v.AUXILIARY),'code_support_sha256':sha(STRUCT/'code_support.json')}

def inference_query(q):
    result={k:q[k] for k in KEYS if k in q}
    if not isinstance(result.get('lot_id'),str) or result['lot_id']!=result['lot_id'].strip() or not result['lot_id']:raise ValueError('Literal lot ID required')
    if datetime.date.fromisoformat(result['publish_date'])<=datetime.date(2024,12,31):raise ValueError('Query precedes frozen cutoff')
    for item in result['items']:
        if not isinstance(item['product_name'],str) or not isinstance(item['okpd2_code'],str):raise ValueError('Raw product/code strings required')
    return result

def feature_values(v,engine,q,ids):
    clean=inference_query(q)
    _,scores,diag=v.neighbor_channel(engine,clean)
    values=np.array([scores.get(str(inn),0.) for inn in ids],dtype=np.float32)
    if not np.isfinite(values).all() or (values<0).any() or (values>1).any():raise ValueError('Normalized neighbor feature outside [0,1]')
    return values,diag

def raw_queries():
    result={}; skipped=0
    with (PROJECT/'local/retrieval-router/queries.jsonl').open() as stream:
        for line in stream:
            if '"split": "test"' in line or '"split":"test"' in line:
                skipped+=1;continue
            q=json.loads(line)
            if q['split'] not in ('train','validation'):raise ValueError('Unexpected split')
            if q['lot_id'] in result:raise ValueError('Duplicate query lot')
            result[q['lot_id']]=inference_query(q)
    if len(result)!=820:raise ValueError('Full 600/220 cohort required')
    return result,skipped
