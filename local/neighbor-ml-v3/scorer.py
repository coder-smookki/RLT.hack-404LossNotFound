"""Reusable exact35 inference and a separate, explicit original34 fallback."""
from __future__ import annotations
import importlib.util,json,time
from pathlib import Path
import numpy as np
from features import ROOT,PROJECT,STRUCT,FEATURE,VERSION,sha,load_variants,feature_values

spec=importlib.util.spec_from_file_location('neighbor_v3_numpy_nnpu',PROJECT/'local/pu-ranker/nnpu.py')
nnpu=importlib.util.module_from_spec(spec);spec.loader.exec_module(nnpu)
OLD_VERSION='p1_conservative_local_1_34'

def rank(scores,ids):return np.lexsort((ids,-scores))

def literal(value):
    if not isinstance(value,str) or not value or value!=value.strip():raise ValueError('Literal trimmed nonempty ID required')
    return value

def make_feature_row(engine,q,candidates):
    """Append evidence to an existing unchanged P1 pool, without reading labels."""
    original=json.loads((ROOT/'bundle/input_manifest.json').read_text())
    original_names=original['original_feature_names'];ids=[literal(c['supplier_inn']) for c in candidates]
    if len(ids)>1500 or len(set(ids))!=len(ids):raise ValueError('Invalid supplied original candidate pool')
    for c in candidates:
        if set(c['features'])!=set(original_names):raise ValueError('Only exact original34 features accepted by producer')
    v=load_variants()
    if sha(STRUCT/'variants.py')!=original['history']['variants_sha256']:raise ValueError('Frozen neighbor function changed')
    t=time.perf_counter();values,diag=feature_values(v,engine,q,ids)
    enriched=[{**c,'features':{**c['features'],FEATURE:float(value)}} for c,value in zip(candidates,values)]
    return {'lot_id':literal(q['lot_id']),'feature_version':VERSION,'history_cutoff':original['history_cutoff'],'preprocessing':original['preprocessing'],'candidates':enriched,'neighbor_diagnostics':diag,'neighbor_feature_ms':1000*(time.perf_counter()-t)}

class _NumericScorer:
    def _rows(self,row):
        if row.get('feature_version')!=self.version or row.get('preprocessing')!=self.manifest['preprocessing'] or row.get('history_cutoff')!=self.manifest['history_cutoff']:raise ValueError('Exact feature version/preprocessing/history required')
        lot=literal(row['lot_id']);cs=row['candidates']
        if not isinstance(cs,list) or len(cs)>1500:raise ValueError('List pool of at most1500 required')
        ids=[];x=[];base=[]
        for c in cs:
            ids.append(literal(c['supplier_inn']));f=c['features']
            if set(f)!=set(self.names):raise ValueError('Exact numeric feature names required')
            vals=[]
            for name in self.names:
                value=f[name]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value):raise ValueError('Finite explicit numeric scalar required')
                vals.append(value)
            score=.2*f['R']+.2*f['O']+.6*f['T']
            if not np.isfinite(c['weighted_score']) or abs(c['weighted_score']-score)>1e-6:raise ValueError('Original Weighted score changed')
            if FEATURE in f and not 0<=f[FEATURE]<=1:raise ValueError('Neighbor support outside[0,1]')
            x.append(vals);base.append(score)
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate supplier IDs')
        return lot,cs,np.asarray(ids),np.asarray(x,dtype=float).reshape(-1,len(self.names)),np.asarray(base)

    def score(self,row):
        lot,cs,ids,x,weighted=self._rows(row)
        if not len(cs):return {'lot_id':lot,'method':self.method,'feature_version':self.version,'model':self.model_name,'selection_sha256':self.selection_hash,'pool_preserved':True,'score_semantics':'Ordering historical evidence; not capability or probability','candidates':[]}
        x=np.clip((x-self.mean)/self.scale,-6,6);logits=self.model.predict(x)
        if not np.isfinite(logits).all():raise ValueError('Nonfinite prediction')
        wr=np.empty(len(cs),dtype=int);pr=np.empty(len(cs),dtype=int)
        wr[rank(weighted,ids)]=np.arange(1,len(cs)+1);pr[rank(logits,ids)]=np.arange(1,len(cs)+1)
        scores=.5/(60+wr)+.5/(60+pr)
        output=[{**cs[i],'scoring':{'rank':r,'score':float(scores[i]),'weighted_score':float(weighted[i]),'weighted_rank':int(wr[i]),'pu_logit':float(logits[i]),'pu_rank':int(pr[i])}} for r,i in enumerate(rank(scores,ids),1)]
        return {'lot_id':lot,'method':self.method,'feature_version':self.version,'model':self.model_name,'selection_sha256':self.selection_hash,'pool_preserved':True,'score_semantics':'Ordering historical evidence; not capability or probability','candidates':output}

    def _load_model(self,path,dim,hidden,prior,digest):
        if sha(path)!=digest:raise ValueError('Frozen model hash changed')
        model=nnpu.Model(dim,hidden=hidden,prior=prior)
        with np.load(path,allow_pickle=False) as saved:
            if set(saved.files)!=set(model.parameters):raise ValueError('Exact parameter schema required')
            for k in saved.files:
                if saved[k].dtype.hasobject or saved[k].shape!=model.parameters[k].shape or not np.isfinite(saved[k]).all():raise ValueError('Wrong finite numeric parameter dimension')
                model.parameters[k]=saved[k].copy()
        return model

class ReusableInferenceScorer(_NumericScorer):
    """35-column scorer. A failed validation gate requires explicit fallback."""
    def __init__(self,artifact_directory=None,model_name=None):
        self.directory=Path(artifact_directory or ROOT/'cuda-results');lock=json.loads((self.directory/'selection.lock.json').read_text());self.selection_hash=sha(self.directory/'selection.lock.json')
        for filename,key in [('input_manifest.json','input_manifest_sha256'),('normalization.npz','normalization_sha256'),('protocol.lock.json','protocol_sha256')]:
            if sha(self.directory/filename)!=lock[key]:raise ValueError('Artifact contract hash changed: '+filename)
        self.manifest=json.loads((self.directory/'input_manifest.json').read_text());self.names=self.manifest['features'];self.version=VERSION;self.method='neighbor35_nnpu_fusion'
        if len(self.names)!=35 or self.names[-1]!=FEATURE or lock['feature_version']!=VERSION or self.manifest['feature_version']!=VERSION:raise ValueError('Explicit new35 contract required')
        if model_name is None:
            if lock['decision']!='GO':raise ValueError('NO-GO: use separate OriginalFallbackAdapter or explicitly named research model')
            model_name=lock['selected']['model']
        choices={c['model']:c for c in lock['choices']}
        if model_name not in choices:raise ValueError('Only the two predeclared models are accepted')
        self.model_name=model_name;c=choices[model_name];self.model=self._load_model(self.directory/(model_name+'.npz'),35,c['hidden'],c['prior'],lock['model_sha256'][model_name])
        with np.load(self.directory/'normalization.npz',allow_pickle=False) as n:self.mean,self.scale=n['mean'].copy(),n['scale'].copy()
        if self.mean.shape!=(35,) or self.scale.shape!=(35,) or not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or (self.scale<=0).any():raise ValueError('Invalid35 normalization')

class OriginalFallbackAdapter(_NumericScorer):
    """Explicit original model on exact34 columns, never advertised as35."""
    def __init__(self,artifact_directory=None):
        self.directory=Path(artifact_directory or ROOT/'cuda-results');lock=json.loads((self.directory/'selection.lock.json').read_text());self.selection_hash=sha(self.directory/'selection.lock.json')
        if sha(self.directory/'input_manifest.json')!=lock['input_manifest_sha256']:raise ValueError('Manifest changed')
        self.manifest=json.loads((self.directory/'input_manifest.json').read_text());self.names=self.manifest['original_feature_names'];self.version=OLD_VERSION;self.method='original_locked34_fallback';self.model_name='original_locked34'
        self.model=self._load_model(self.directory/'original_locked34.npz',34,16,.02,lock['original_control_sha256'])
        bundle_manifest=json.loads((ROOT/'bundle/bundle_manifest.json').read_text())
        if sha(self.directory/'original_normalization34.npz')!=bundle_manifest['file_sha256']['original_normalization34.npz']:raise ValueError('Original scaler changed')
        with np.load(self.directory/'original_normalization34.npz',allow_pickle=False) as n:self.mean,self.scale=n['mean'].copy(),n['scale'].copy()

def score_row(row,artifact_directory=None,model_name=None):return ReusableInferenceScorer(artifact_directory,model_name).score(row)
