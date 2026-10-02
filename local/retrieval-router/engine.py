"""Isolated P1 retrospective supplier retrieval experiment, never a capability claim."""
from __future__ import annotations
import argparse, collections, functools, hashlib, html, json, math, os, re, sqlite3, time, unicodedata
from pathlib import Path
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
import snowballstemmer

ROOT=Path(__file__).resolve().parent
DB=ROOT/'snapshot.sqlite'
PREPROCESS='p1_conservative_local_1'
CUTOFF='2024-12-31'
SEED='20261001-retrieval-router-v1'
STEM=snowballstemmer.stemmer('russian')
TOKEN=re.compile(r'[a-zа-яё0-9]+(?:[-_./+][a-zа-яё0-9]+)*',re.I)
PROTECTED=re.compile(r'(?:гост(?:\s+р)?|iso|din|ту)\s*[-№:]?\s*\d[\w./-]*|(?=[a-zа-яё0-9_./+-]*[a-zа-яё])(?=[a-zа-яё0-9_./+-]*\d)[a-zа-яё0-9]+(?:[-_./+][a-zа-яё0-9]+)*|\b(?:ph|igm|igg)\b|\d+(?:[.,]\d+)?\s*(?:мг|мл|мм|см|кг|квт|вт|gb|tb|mhz|ghz|мкм|м3|м2)\b',re.I)
FORMAT=re.compile(r'(?:[0-9]{10}|[0-9]{12})\Z')

def write_json(path,x):
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False));os.replace(tmp,path)
def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
@functools.lru_cache(maxsize=200000)
def stem_word(t): return STEM.stemWord(t) if re.fullmatch('[а-я]+',t) else t
@functools.lru_cache(maxsize=120000)
def canonical(raw):
    text=unicodedata.normalize('NFC',html.unescape(raw or ''))
    text=''.join(chr(ord(c)-0xfee0) if '\uff01'<=c<='\uff5e' else ' ' if c=='\u200b' else '' if c in '\ufeff\u2060\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' else c for c in text)
    text=text.translate(str.maketrans({'\u2010':'-','\u2011':'-','\u2012':'-','\u2013':'-','\u2014':'-','\u2018':"'",'\u2019':"'",'\u201c':'"','\u201d':'"'}))
    return ' '.join(text.split()).casefold().replace('ё','е')
@functools.lru_cache(maxsize=120000)
def representation(raw):
    text=canonical(raw)
    spans=[{'kind':'technical','value':m.group(),'start':m.start(),'end':m.end(),'exact_key':re.sub(r'\s+','',m.group())} for m in PROTECTED.finditer(text)]
    protected={(s['start'],s['end']) for s in spans}
    tokens=[]
    for m in TOKEN.finditer(text):
        is_protected=any(m.start()<b and m.end()>a for a,b in protected)
        tokens.append(m.group() if is_protected else stem_word(m.group()))
    return text,tuple(tokens),tuple(s['exact_key'] for s in spans)

def readonly(path):
    con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);con.execute('pragma cache_size=-40000');return con

def build(source:Path):
    if DB.exists():raise FileExistsError(DB)
    started=time.perf_counter(); con=sqlite3.connect(DB,uri=True);con.create_function('p1_canonical',1,canonical,deterministic=True);con.execute('pragma cache_size=-80000')
    con.execute('ATTACH DATABASE ? AS raw',(source.resolve().as_uri()+'?mode=ro',))
    con.executescript('''
    CREATE TABLE history_notices AS SELECT lot_id,publish_date,subject,customer_inn,is_eshop_or_aisgz AS source FROM raw.notices WHERE publish_date<='2024-12-31';
    CREATE UNIQUE INDEX hn_lot ON history_notices(lot_id);
    CREATE TABLE participation AS SELECT s.lot_id,trim(s.supplier_inn) inn,min(s.row_id) raw_min_row,count(*) raw_rows FROM raw.suppliers s JOIN history_notices n USING(lot_id) WHERE trim(s.supplier_inn)<>'' GROUP BY s.lot_id,trim(s.supplier_inn);
    CREATE UNIQUE INDEX hp_lot_inn ON participation(lot_id,inn);
    CREATE TABLE history_items AS SELECT i.lot_id,p1_canonical(i.product_name) retrieval_text,trim(i.okpd2_code) code,min(i.row_id) raw_min_row,count(*) raw_rows FROM raw.items i JOIN history_notices n USING(lot_id) GROUP BY i.lot_id,p1_canonical(i.product_name),trim(i.okpd2_code);
    CREATE INDEX hi_lot ON history_items(lot_id);
    CREATE TABLE profiles(id INTEGER PRIMARY KEY,inn TEXT,branch TEXT,text TEXT,codes TEXT,protected TEXT,formulations INTEGER,history_lots INTEGER);
    CREATE INDEX profiles_inn ON profiles(inn);
    CREATE VIRTUAL TABLE spec_fts USING fts5(text,content='profiles',content_rowid='id',tokenize='unicode61 remove_diacritics 0');
    CREATE TABLE company(id INTEGER PRIMARY KEY,inn TEXT UNIQUE,text TEXT,codes TEXT,protected TEXT,history_lots INTEGER);
    CREATE VIRTUAL TABLE company_fts USING fts5(text,content='company',content_rowid='id',tokenize='unicode61 remove_diacritics 0');
    CREATE TABLE subject_profile(id INTEGER PRIMARY KEY,inn TEXT UNIQUE,text TEXT);
    CREATE VIRTUAL TABLE subject_fts USING fts5(text,content='subject_profile',content_rowid='id',tokenize='unicode61 remove_diacritics 0');
    CREATE TABLE exact_token(token TEXT,inn TEXT,PRIMARY KEY(token,inn)) WITHOUT ROWID;
    CREATE TABLE category AS SELECT code,inn,count(DISTINCT h.lot_id) history_lots FROM (SELECT DISTINCT lot_id,code FROM history_items WHERE code<>'') h JOIN participation p USING(lot_id) GROUP BY code,inn;
    CREATE INDEX category_code ON category(code);
    CREATE TABLE branch_frequency AS SELECT substr(code,1,5) branch,count(DISTINCT lot_id) history_lots FROM history_items WHERE code<>'' GROUP BY substr(code,1,5);
    ''');con.commit();print('canonical ready',round(time.perf_counter()-started,2),flush=True)
    hist_counts={inn:n for inn,n in con.execute('SELECT inn,count(*) FROM participation GROUP BY inn')}
    profile_hist={(inn,branch):n for inn,branch,n in con.execute('SELECT p.inn,substr(i.code,1,5),count(DISTINCT p.lot_id) FROM participation p JOIN history_items i USING(lot_id) GROUP BY 1,2')}
    current=None;counts=collections.Counter();codes=set();prot=set();forms=0;company_inn=None;ct=collections.Counter();cc=set();cp=set();profile_id=company_id=0
    def flush_company():
        nonlocal company_id
        if company_inn is None:return
        company_id+=1
        text=' '.join(t for t,n in sorted(ct.items()) for _ in range(min(n,3)))
        con.execute('INSERT INTO company VALUES(?,?,?,?,?,?)',(company_id,company_inn,text,json.dumps(sorted(cc)),json.dumps(sorted(cp)),hist_counts[company_inn]))
        con.executemany('INSERT OR IGNORE INTO exact_token VALUES(?,?)',((t,company_inn) for t in cp))
    def flush_profile():
        nonlocal profile_id
        if current is None:return
        profile_id+=1; inn,branch=current
        text=' '.join(t for t,n in sorted(counts.items()) for _ in range(min(n,3)))
        con.execute('INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?)',(profile_id,inn,branch,text,json.dumps(sorted(codes)),json.dumps(sorted(prot)),forms,profile_hist[current]))
        ct.update(counts);cc.update(codes);cp.update(prot)
    rows=0
    for inn,branch,raw,code in con.execute('SELECT p.inn,substr(i.code,1,5),i.retrieval_text,i.code FROM participation p JOIN history_items i USING(lot_id) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4'):
        rows+=1; key=(inn,branch)
        if key!=current:
            flush_profile()
            if inn!=company_inn:flush_company();ct=collections.Counter();cc=set();cp=set();company_inn=inn
            current=key;counts=collections.Counter();codes=set();prot=set();forms=0
        _,tokens,pts=representation(raw);counts.update(set(tokens));prot.update(pts);codes.add(code) if code else None;forms+=1
        if rows%250000==0:print('projection',rows,'profiles',profile_id,round(time.perf_counter()-started,1),flush=True)
    flush_profile();flush_company();con.commit();print('profiles ready',profile_id,company_id,round(time.perf_counter()-started,1),flush=True)
    current=None;counts=collections.Counter();sid=0
    def flush_subject():
        nonlocal sid
        if current is None:return
        sid+=1; text=' '.join(t for t,n in sorted(counts.items()) for _ in range(min(n,3)));con.execute('INSERT INTO subject_profile VALUES(?,?,?)',(sid,current,text))
    for inn,subject in con.execute('SELECT p.inn,n.subject FROM participation p JOIN history_notices n USING(lot_id) GROUP BY p.inn,n.subject ORDER BY p.inn,n.subject'):
        if inn!=current:flush_subject();current=inn;counts=collections.Counter()
        counts.update(set(representation(subject)[1]))
    flush_subject()
    for f in ['spec_fts','company_fts','subject_fts']:
        con.execute(f"INSERT INTO {f}({f}) VALUES('rebuild')");con.execute(f"INSERT INTO {f}({f}) VALUES('optimize')")
    con.execute("CREATE VIRTUAL TABLE vocab USING fts5vocab(spec_fts,'row')");con.commit()
    meta={'preprocessing':PREPROCESS,'cutoff':CUTOFF,'source_database':str(source.resolve()),'raw_source_manifest':'local/sources-manifest.json','specialization_profiles':profile_id,'companies':company_id,'unique_profile_formulations':rows,'build_seconds':time.perf_counter()-started,'python_packages':{'snowballstemmer':'3.0.1','scikit-learn':'1.9.1'},'data_policy':'canonical (lot,trim INN) participation; every flag positive; profile text is history evidence only','normalization':'NFC + HTML entities + fullwidth ASCII only + limited punctuation + casefold/ё→е; no global NFKC/confusable folding; Russian ordinary word Snowball; protected tokens unstemmed','raw_provenance':'source DB immutable; source row_min/count in history projections; no rewritten raw CSV','known_limitation':'No outcome available_at; code syntax/semantic truth not manually judged; technical-span recognition is conservative and incomplete'}
    write_json(ROOT/'snapshot_manifest.json',meta);con.close();return meta


def choose_queries(source:Path):
    path=ROOT/'queries.jsonl'
    if path.exists():raise FileExistsError(path)
    history=readonly(DB);freq=dict(history.execute('SELECT branch,history_lots FROM branch_frequency'));known_codes={x[0] for x in history.execute('SELECT DISTINCT code FROM category')};groups={(cust,canonical(sub)) for cust,sub in history.execute('SELECT customer_inn,subject FROM history_notices')};history.close()
    con=readonly(source);con.row_factory=sqlite3.Row
    selected=[];seen=set();split_limits={'train':300,'validation':110,'test':113}
    for split,lo,hi in [('train','2025-01-01','2025-03-31'),('validation','2025-04-01','2025-06-30'),('test','2025-07-01','2025-12-31')]:
        rows=list(con.execute('SELECT n.lot_id,n.publish_date,n.subject,n.customer_inn,n.is_eshop_or_aisgz source FROM notices n WHERE n.publish_date BETWEEN ? AND ? AND EXISTS(SELECT 1 FROM suppliers s WHERE s.lot_id=n.lot_id AND trim(s.supplier_inn)<>\'\') ORDER BY lot_id',(lo,hi)))
        bysource=collections.defaultdict(list)
        for row in rows:bysource[row['source']].append(dict(row))
        for source_name,rs in sorted(bysource.items()):
            limit=split_limits[split]-(1 if split=='test' and source_name=='ЭМ' else 0)
            rs.sort(key=lambda r:hashlib.sha256((SEED+'|'+split+'|'+r['lot_id']).encode()).digest())
            n=0
            for r in rs:
                key=(r['customer_inn'],canonical(r['subject']))
                if key in seen:continue
                seen.add(key)
                lid=r['lot_id']; items=[{'raw_row_id':x[0],'product_name':x[1],'okpd2_code':x[2]} for x in con.execute('SELECT min(row_id),product_name,okpd2_code FROM items WHERE lot_id=? GROUP BY product_name,okpd2_code ORDER BY min(row_id)',(lid,))]
                truth=sorted({x[0].strip() for x in con.execute('SELECT supplier_inn FROM suppliers WHERE lot_id=?',(lid,)) if x[0].strip()})
                codes=sorted({i['okpd2_code'].strip() for i in items if i['okpd2_code'].strip()})
                r.update({'split':split,'items':items,'observed_inns':truth,'known_group':key in groups,'rare':not codes or min(freq.get(c[:5],0) for c in codes)<=100,'unseen_code':any(c not in known_codes for c in codes),'unseen_exact_code':any(c not in known_codes for c in codes),'unseen_branch4':any(freq.get(c[:5],0)==0 for c in codes)})
                selected.append(r);n+=1
                if n>=limit:break
    con.close()
    with path.open('w') as out:
        for r in selected:out.write(json.dumps(r,ensure_ascii=False)+'\n')
    meta={'seed':SEED,'cutoff':CUTOFF,'sampling':'lowest SHA in each source with customer+NFC normalized subject group disjoint across query periods','split':{'train':['2025-01-01','2025-03-31'],'validation':['2025-04-01','2025-06-30'],'test':['2025-07-01','2025-12-31']},'queries_by_split':dict(collections.Counter(x['split'] for x in selected)),'source_counts':{s:dict(collections.Counter(x['source'] for x in selected if x['split']==s)) for s in split_limits},'query_manifest_sha256':digest(selected),'test_status':'diagnostic historical replay; source outcomes not temporally verified'}
    write_json(ROOT/'query_manifest.json',meta);return meta

class Engine:
    def __init__(self):
        self.con=readonly(DB)
        self.N=self.con.execute('SELECT count(*) FROM profiles').fetchone()[0]
        self.df=dict(self.con.execute('SELECT term,doc FROM vocab'))
        self.freq=dict(self.con.execute('SELECT branch,history_lots FROM branch_frequency'))
        self.companies={}
        for inn,text,codes,protected,lots in self.con.execute('SELECT inn,text,codes,protected,history_lots FROM company'):
            cs=set(json.loads(codes)); self.companies[inn]={'tokens':set(text.split()),'codes':cs,'b6':{c[:8] for c in cs},'b4':{c[:5] for c in cs},'b2':{c[:2] for c in cs},'protected':set(json.loads(protected)),'lots':lots}
        self.cat=collections.defaultdict(dict);self.branch=collections.defaultdict(dict)
        for code,inn,lots in self.con.execute('SELECT code,inn,history_lots FROM category'):
            self.cat[code][inn]=lots;self.branch[code[:5]][inn]=max(lots,self.branch[code[:5]].get(inn,0))
        self.profile_inns=[inn for inn, in self.con.execute('SELECT inn FROM profiles ORDER BY id')]
        self.char=None;self.char_index=None
    def idf(self,t):return math.log1p((self.N-self.df.get(t,0)+.5)/(self.df.get(t,0)+.5))
    def fit_char(self):
        ts=[t for t, in self.con.execute('SELECT text FROM profiles ORDER BY id')]
        self.char=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),max_features=100000,min_df=2,dtype=np.float32,lowercase=False)
        self.char_index=self.char.fit_transform(ts).T.tocsr();del ts
        sparse.save_npz(ROOT/'char_index.npz',self.char_index)
        write_json(ROOT/'char_vocabulary.json',{t:int(i) for t,i in self.char.vocabulary_.items()});np.save(ROOT/'char_idf.npy',self.char.idf_,allow_pickle=False)
        print('char fitted',self.char_index.shape,self.char_index.nnz,flush=True)
    def load_char(self):
        self.char=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),vocabulary=json.loads((ROOT/'char_vocabulary.json').read_text()),dtype=np.float32,lowercase=False)
        self.char.idf_=np.load(ROOT/'char_idf.npy',allow_pickle=False);self.char_index=sparse.load_npz(ROOT/'char_index.npz').tocsr()
    def lex(self,fts,meta,tokens,limit):
        terms=sorted(set(tokens),key=lambda t:(-self.idf(t),t))[:32]
        if not terms:return []
        match=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
        rows=self.con.execute(f'SELECT m.inn,{fts}.rank FROM {fts} JOIN {meta} m ON m.id={fts}.rowid WHERE {fts} MATCH ? ORDER BY {fts}.rank LIMIT ?',(match,limit*5 if meta=='profiles' else limit))
        result=[];seen=set()
        for inn,score in rows:
            if inn not in seen:result.append((inn,-float(score)));seen.add(inn)
            if len(result)>=limit:break
        return result
    def channels(self,q,depth=1500,rich=True):
        texts=list(dict.fromkeys(canonical(i['product_name']) for i in q['items']))
        if not texts:texts=[canonical(q['subject'])]
        groups=[set(representation(t)[1]) for t in texts];tokens=set.union(*groups) if groups else set()
        codes=sorted({i['okpd2_code'].strip() for i in q['items'] if i['okpd2_code'].strip()})
        protected=set(t for text in texts for t in representation(text)[2])
        started=time.perf_counter()
        ch={'specialization':self.lex('spec_fts','profiles',tokens,depth),'company':self.lex('company_fts','company',tokens,depth)}
        cw=collections.Counter()
        for code in codes:
            for inn,n in self.cat.get(code,{}).items():cw[inn]+=math.log1p(n)/max(1,len(codes))
            for inn,n in self.branch.get(code[:5],{}).items():cw[inn]+=.25*math.log1p(n)/max(1,len(codes))
        ch['category']=sorted(cw.items(),key=lambda x:(-x[1],x[0]))[:depth]
        if rich:
            ch['subject']=self.lex('subject_fts','subject_profile',representation(q['subject'])[1],depth)
            ep=collections.Counter()
            for pt in protected:
                found=[x[0] for x in self.con.execute('SELECT inn FROM exact_token WHERE token=?',(pt,))]
                weight=math.log1p(len(self.companies)/max(1,len(found)))
                for inn in found:ep[inn]+=weight
            ch['protected']=sorted(ep.items(),key=lambda x:(-x[1],x[0]))[:depth]
            if self.char is not None:
                vector=self.char.transform([' '.join(sorted(tokens))]); scores=(vector @ self.char_index).toarray().ravel()
                order=np.argsort(-scores,kind='stable');out=[];seen=set()
                for i in order:
                    if scores[i]<=0:break
                    inn=self.profile_inns[i]
                    if inn not in seen:out.append((inn,float(scores[i])));seen.add(inn)
                    if len(out)>=depth:break
                ch['char']=out
        # Diagnostic only: disagreement between top specialization profiles and query codes.
        text_head={inn for inn,_ in ch['specialization'][:20]}; query_b2={c[:2] for c in codes}
        agree=sum(bool(self.companies[inn]['b2']&query_b2) for inn in text_head)/max(1,len(text_head))
        conflict=bool(query_b2 and text_head and agree<.25)
        d={'item_count':len(texts),'code_count':len(codes),'branch4_count':len({c[:5] for c in codes}),'query_terms':len(tokens),'protected_count':len(protected),'code_text_disagreement':conflict,'code_agreement_top20':agree,'identifier_rich':bool(protected),'text_poor':len(tokens)<3,'rare':q['rare'],'unseen_code':q['unseen_code'],'unseen_exact_code':q.get('unseen_exact_code',q['unseen_code']),'unseen_branch4':q.get('unseen_branch4',False),'source':q['source']}
        return {'channels':ch,'groups':groups,'codes':codes,'protected':protected,'subject_tokens':set(representation(q['subject'])[1]),'diagnostics':d,'retrieval_ms':1000*(time.perf_counter()-started)}
    def pool(self,ch,budget,adaptive=False):
        names=list(ch['channels']);weights={n:1. for n in names};route='default'
        d=ch['diagnostics']
        if adaptive and d['code_text_disagreement']:
            weights['category']=.15; route='text_code_disagreement'
        elif adaptive and d['identifier_rich']:
            weights.update({'protected':2.,'char':1.5,'category':.5});route='identifier_rich'
        elif adaptive and d['text_poor']:
            weights.update({'category':2.,'subject':1.5});route='text_poor'
        union=set();ranks={};rrf=collections.Counter()
        for name,values in ch['channels'].items():
            ranks[name]={inn:i+1 for i,(inn,_) in enumerate(values)}
            for inn,rank in ranks[name].items():rrf[inn]+=weights[name]*61/(60+rank);union.add(inn)
        pool=sorted(union,key=lambda inn:(-rrf[inn],inn))[:budget]
        return pool,ranks,route
    def features(self,ch,pool,ranks):
        groups=ch['groups'];codes=ch['codes'];prot=ch['protected'];d=ch['diagnostics'];sg=ch['subject_tokens']
        gt=[({t:self.idf(t) for t in group},sum(self.idf(t) for t in group)) for group in groups]
        sw={t:self.idf(t) for t in sg};sden=sum(sw.values())
        result=[]
        for inn in pool:
            c=self.companies[inn];terms=c['tokens'];cs=c['codes']
            cv=[sum(w for t,w in weights.items() if t in terms)/den if den else 0. for weights,den in gt]
            subject=sum(w for t,w in sw.items() if t in terms)/sden if sden else 0.
            T=(sum(cv)/max(1,len(cv))+.35*subject)/1.35
            def fraction(pred):return sum(pred(v) for v in codes)/max(1,len(codes))
            exact=fraction(lambda v:v in cs);b6=fraction(lambda v:v[:8] in c['b6']);b4=fraction(lambda v:v[:5] in c['b4']);b2=fraction(lambda v:v[:2] in c['b2'])
            O=sum(1. if code in cs else .55 if code[:5] in c['b4'] else .15 if code[:2] in c['b2'] else 0. for code in codes)/max(1,len(codes))
            rrs={name:61/(60+ranks[name][inn]) if inn in ranks[name] else 0. for name in ['specialization','company','category','subject','protected','char'] if name in ranks}
            # Ranker always retains same baseline retrieval signal; added channel terms are features only.
            R=sum(rrs.get(n,0) for n in ['specialization','company','category'])/3
            f={'R':R,'O':O,'T':T,'weighted_score':.2*R+.2*O+.6*T,'item_coverage_mean':sum(cv)/max(1,len(cv)),'item_coverage_min':min(cv) if cv else 0.,'item_coverage_half_fraction':sum(x>=.5 for x in cv)/max(1,len(cv)),'subject_coverage':subject,'exact_code_fraction':exact,'branch6_fraction':b6,'branch4_fraction':b4,'branch2_fraction':b2,'protected_overlap':len(prot&c['protected'])/max(1,len(prot)),'log_history_lots':math.log1p(c['lots']),'log_profile_tokens':math.log1p(len(terms)),'log_profile_codes':math.log1p(len(cs)),'query_log_items':math.log1p(d['item_count']),'query_log_codes':math.log1p(len(codes)),'query_log_terms':math.log1p(d['query_terms']),'query_protected_count':float(d['protected_count']),'query_conflict':float(d['code_text_disagreement']),'query_text_poor':float(d['text_poor']),'query_rare':float(d['rare']),'query_unseen_code':float(d['unseen_code']),'branch_rarity':sum(1/math.log2(2+self.freq.get(v[:5],0)) for v in codes)/max(1,len(codes)),'inn_format_valid':float(bool(FORMAT.fullmatch(inn))),'channel_hits':float(sum(inn in x for x in ranks.values())),'best_channel_rr':max(rrs.values(),default=0.),**{n+'_rr':rrs.get(n,0) for n in ['specialization','company','category','subject','protected','char']}}
            result.append({'supplier_inn':inn,'weighted_score':f['weighted_score'],'features':f,'channel_ranks':{n:r.get(inn) for n,r in ranks.items()}})
        return result

def evaluate(order,truth,known):
    t=set(truth);k=set(known);dcg=sum(1/math.log2(i+2) for i,v in enumerate(order[:10]) if v in t);ideal=sum(1/math.log2(i+2) for i in range(min(10,len(t))))
    r={'ndcg10':dcg/ideal if ideal else 0.,'mrr':next((1/(i+1) for i,v in enumerate(order) if v in t),0.),'pool_recall':len(set(order)&t)/max(1,len(t)),'known_pool_recall':len(set(order)&k)/max(1,len(k)),'observed_count':len(t),'known_count':len(k),'pool_hit_count':len(set(order)&t)}
    for n in [10,20,50,100,300,500,1000,1500]:r['recall'+str(n)]=len(set(order[:n])&t)/max(1,len(t))
    return r

def export_split(engine,split,budget=1500):
    output=ROOT/(split+'_pairs.jsonl');metric_path=ROOT/(split+'_metrics.jsonl')
    if split=='test' and not (ROOT/'selection.lock.json').exists():raise RuntimeError('Freeze validation choice in selection.lock.json before diagnostic test evaluation')
    if output.exists():raise FileExistsError(output)
    queries=[json.loads(x) for x in (ROOT/'queries.jsonl').read_text().splitlines() if json.loads(x)['split']==split]
    start=time.perf_counter()
    with output.open('w') as out,metric_path.open('w') as met:
        for i,q in enumerate(queries):
            t=time.perf_counter();ch=engine.channels(q,1500,True);pool,ranks,route=engine.pool(ch,budget,False);features=engine.features(ch,pool,ranks); elapsed=1000*(time.perf_counter()-t)
            row={'schema_version':1,'split':split,'lot_id':q['lot_id'],'publish_date':q['publish_date'],'source':q['source'],'preprocessing':PREPROCESS,'history_cutoff':CUTOFF,'known_group':q['known_group'],'observed_inns':q['observed_inns'],'known_observed_inns':sorted(set(q['observed_inns'])&engine.companies.keys()),'query_diagnostics':ch['diagnostics'],'diagnostics':ch['diagnostics'],'candidates':features,'retrieval_feature_ms':elapsed}
            row['reference_pools']={}
            for ref_budget in [500,1000,1500]:
                ref_ch={**ch,'channels':{n:v[:ref_budget] for n,v in ch['channels'].items()}}
                row['reference_pools']['rich_'+str(ref_budget)]=engine.pool(ref_ch,ref_budget,False)[0]
            shallow={**ch,'channels':{n:v[:500] for n,v in ch['channels'].items() if n in ['specialization','company','category']}}
            row['reference_pools']['depth_only_500']=engine.pool(shallow,500,False)[0]
            out.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n');out.flush()
            if split=='train':
                if i%50==0:print(split,i,len(queries),'seconds',round(time.perf_counter()-start,1),flush=True)
                continue
            variants={}
            # The baseline depth and new channel effects are separated explicitly.
            for rich in [False,True]:
                for b in [500,1000,1500]:
                    for adaptive in ([False,True] if rich and b==500 else [False]):
                        sub={**ch,'channels':{n:v[:b] for n,v in ch['channels'].items() if rich or n in ['specialization','company','category']}}
                        pp,rr,route=engine.pool(sub,b,adaptive);fs=engine.features(sub,pp,rr)
                        ranked=sorted(fs,key=lambda r:(-r['features']['weighted_score'],r['supplier_inn']));order=[v['supplier_inn'] for v in ranked]
                        label=('rich' if rich else 'depth_only')+'_'+str(b)+('_adaptive' if adaptive else '_static')
                        variants[label]={**evaluate(order,q['observed_inns'],row['known_observed_inns']),'route':route,'top10':order[:10],'pool_inns':sorted(pp)}
            met.write(json.dumps({'lot_id':q['lot_id'],'source':q['source'],'query_diagnostics':ch['diagnostics'],'known_group':q['known_group'],'variants':variants,'whole_export_ms':1000*(time.perf_counter()-t)},ensure_ascii=False)+'\n');met.flush()
            if i%50==0:print(split,i,len(queries),'seconds',round(time.perf_counter()-start,1),flush=True)
    meta={'split':split,'budget':budget,'rows':len(queries),'seconds':time.perf_counter()-start,'file':str(output),'file_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'query_manifest_sha256':json.loads((ROOT/'query_manifest.json').read_text())['query_manifest_sha256'],'features':list(features[0]['features']) if features else []}
    write_json(ROOT/(split+'_export_manifest.json'),meta);return meta

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['build','sample','char','export']);p.add_argument('--source',type=Path,default=ROOT.parent/'history.sqlite');p.add_argument('--split',choices=['train','validation','test'],default='train');args=p.parse_args()
    if args.action=='build':print(json.dumps(build(args.source),ensure_ascii=False))
    elif args.action=='sample':print(json.dumps(choose_queries(args.source),ensure_ascii=False))
    else:
        engine=Engine()
        if args.action=='char':engine.fit_char()
        else:engine.load_char();print(json.dumps(export_split(engine,args.split),ensure_ascii=False))
if __name__=='__main__':main()
