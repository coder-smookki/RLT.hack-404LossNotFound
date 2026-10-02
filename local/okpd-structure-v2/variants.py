"""Bounded history-only structural interventions; no outcome labels at inference.

All candidate features remain the exact frozen P1 producer's 34 features. New
scores are separate policy scores, never disguised as the old model's features.
"""
from __future__ import annotations
import collections
import datetime
import importlib.util
import json
import math
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'retrieval-router' / 'engine.py'
spec = importlib.util.spec_from_file_location('okpd_original_engine', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
AUXILIARY = ROOT / 'history_aux.sqlite'
VARIANTS = ('baseline', 'item_quota', 'lot_neighbor_quota', 'code_support')
STOP = frozenset('поставк поставка закупк закупка услуг услуги работ работы товар товары оказан оказание выполнен выполнение тип вид проч прочие прочий общ общий назначен назначения для по на из и в с к не р росс российск гост шт штук договор контракт'.split())


def _state(engine):
    """Attach immutable local auxiliary state once, without rebuilding indices."""
    if not hasattr(engine, '_okpd_structure_v2'):
        con = base.readonly(AUXILIARY)
        meta = dict(con.execute('SELECT key,value FROM metadata'))
        if meta['history_cutoff'] != base.CUTOFF or meta['preprocessing'] != base.PREPROCESS:
            raise ValueError('Auxiliary data differ from frozen P1 history contract')
        codes = json.loads((ROOT / 'code_support.json').read_text())
        engine._okpd_structure_v2 = {'con': con, 'codes': codes}
    return engine._okpd_structure_v2


def confidence(engine, q):
    """How much the input text supports common text under its historical code.

    This is a lexical diagnostic, not code correctness, semantic equivalence or
    a probability. Unseen codes have no support, but the code channel keeps .25.
    """
    data = _state(engine)['codes']
    values = []
    for item in q['items']:
        code = item['okpd2_code'].strip()
        if not code:
            continue
        tokens = set(base.representation(item['product_name'])[1]) - STOP
        weights = {t: engine.idf(t) for t in tokens}
        den = sum(weights.values())
        info = data.get(code)
        common = set(info['terms']) if info else set()
        support = sum(w for t, w in weights.items() if t in common) / den if den else 0.
        reliability = min(1., (info['unique_lots'] if info else 0) / 50.)
        values.append(support * reliability)
    support = sum(values) / len(values) if values else 0.
    return .25 + .75 * support, support


def item_channel(engine, q):
    """Round-robin at most 12 distinct positions, each capped at 160 companies.

    Positions are selected by input-only lexical information, deterministic
    ties. No code or observed supplier outcome is used to choose positions.
    """
    texts = sorted(set(base.canonical(i['product_name']) for i in q['items']))
    if len(texts) <= 1:
        return [], {'item_channels': len(texts), 'item_channels_capped': False}
    texts.sort(key=lambda s: (-sum(engine.idf(t) for t in set(base.representation(s)[1]) - STOP), s))
    kept = texts[:12]
    hits = [engine.lex('spec_fts', 'profiles', base.representation(t)[1], 160) for t in kept]
    order, seen = [], set()
    for level in range(max((len(h) for h in hits), default=0)):
        for h in hits:
            if level < len(h) and h[level][0] not in seen:
                order.append(h[level][0]); seen.add(h[level][0])
    return order, {'item_channels': len(kept), 'input_distinct_items': len(texts), 'item_channels_capped': len(texts) > 12}


def neighbor_channel(engine, q):
    """40 lexical historical LOT neighbors -> unique observed participants.

    Product and subject are separate FTS fields. Repeated TRU do not multiply
    supplier counts. Same-lot matches are excluded even for historical callers.
    """
    con = _state(engine)['con']
    tokens = set(t for item in q['items'] for t in base.representation(item['product_name'])[1])
    tokens.update(base.representation(q['subject'])[1])
    terms = sorted(tokens - STOP, key=lambda t: (-engine.idf(t), t))[:16]
    if not terms:
        return [], {}, {'neighbor_lots': 0}
    match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
    rows = list(con.execute('''SELECT m.lot_id,m.inns,lot_fts.rank score
        FROM lot_fts JOIN lot_meta m ON m.id=lot_fts.rowid
        WHERE lot_fts MATCH ? AND lot_fts.rank MATCH 'bm25(1.0,0.35)' AND m.lot_id<>?
        ORDER BY lot_fts.rank LIMIT 80''', (match, str(q['lot_id']))))
    # Native rank ordering lets FTS perform top-K retrieval. Only the returned
    # 80-hit shortlist is deterministically tie-sorted, not the entire corpus.
    rows = sorted(rows,key=lambda r:(r[2],r[0]))[:40]
    scores = collections.Counter()
    top_score = max((-r[2] for r in rows), default=0.)
    for rank, (lot, raw_inns, bm25) in enumerate(rows, 1):
        inns = json.loads(raw_inns)
        if len(inns) != len(set(inns)):
            raise ValueError('Duplicate historical participants')
        amount = (-bm25 / top_score if top_score > 0 else 0.) / (10 + rank) / math.sqrt(max(1, len(inns)))
        for inn in inns:
            if inn in engine.companies:
                scores[inn] += amount
    order = sorted(scores, key=lambda inn: (-scores[inn], inn))
    maximum = max(scores.values(), default=0.)
    normalized = {inn: value / maximum for inn, value in scores.items()} if maximum else {}
    return order, normalized, {'neighbor_lots': len(rows), 'neighbor_lot_ids': [r[0] for r in rows[:5]]}


def quota_pool(reference, auxiliary, budget):
    """Exactly 20% reservation, then baseline fills, then auxiliary if needed."""
    result, seen = [], set()
    for sequence in [auxiliary[:int(.2 * budget)], reference, auxiliary]:
        for inn in sequence:
            if inn not in seen:
                result.append(inn); seen.add(inn)
            if len(result) == budget:
                return result
    return result


def _run(engine, q, budget, names):
    """Compute shared retrieval once and evaluate all predeclared interventions."""
    if not isinstance(budget, int) or budget not in (500, 1500):
        raise ValueError('Only frozen budgets500/1500 are supported')
    if not isinstance(q.get('lot_id'), str):
        raise ValueError('Literal lot ID required')
    published = datetime.date.fromisoformat(q['publish_date'])
    if published <= datetime.date.fromisoformat(base.CUTOFF):
        raise ValueError('Frozen2024 history can only evaluate later queries')
    start = time.perf_counter()
    ch = engine.channels(q, 1500, True)
    reference, ranks, _ = engine.pool(ch, budget, False)
    base_ms = (time.perf_counter() - start) * 1000
    output = {}
    for name in names:
        begin = time.perf_counter()
        pool, extra, score_map = reference, {}, {}
        code_weight = 1.
        if name == 'item_quota':
            aux, extra = item_channel(engine, q)
            pool = quota_pool(reference, aux, budget)
        elif name == 'lot_neighbor_quota':
            aux, score_map, extra = neighbor_channel(engine, q)
            pool = quota_pool(reference, aux, budget)
        elif name == 'code_support':
            code_weight, support = confidence(engine, q)
            rrf = collections.Counter()
            for channel, values in ch['channels'].items():
                for rank, (inn, _) in enumerate(values, 1):
                    rrf[inn] += (code_weight if channel == 'category' else 1.) * 61 / (60 + rank)
            pool = sorted(rrf, key=lambda inn: (-rrf[inn], inn))[:budget]
            extra = {'code_weight': code_weight, 'code_text_support': support, 'semantics': 'lexical history support, not raw-code correctness'}
        candidates = engine.features(ch, pool, ranks)
        if len(pool) != len(set(pool)) or any(inn not in engine.companies for inn in pool):
            raise ValueError('Candidate identity invariant violated')
        weighted = sorted(candidates, key=lambda c: (-c['weighted_score'], c['supplier_inn']))
        def policy(c):
            f = c['features']; value = c['weighted_score']
            if name == 'item_quota' and ch['diagnostics']['item_count'] > 1:
                return .85 * value + .15 * (.5 * f['item_coverage_min'] + .5 * f['item_coverage_half_fraction'])
            if name == 'lot_neighbor_quota':
                return .85 * value + .15 * score_map.get(c['supplier_inn'], 0.)
            if name == 'code_support':
                return value - .2 * (1 - code_weight) * f['O'] - (.2 / 3) * (1 - code_weight) * f['category_rr']
            return value
        candidates_with_scores = [{**c, 'structural_score': policy(c)} for c in candidates]
        ranking = sorted(candidates_with_scores, key=lambda c: (-c['structural_score'], c['supplier_inn']))
        output[name] = {'pool': pool, 'candidates': candidates_with_scores,
            'ranking': [c['supplier_inn'] for c in ranking],
            'weighted_ranking': [c['supplier_inn'] for c in weighted],
            'diagnostics': {**ch['diagnostics'], **extra, 'name': name, 'budget': budget,
                'baseline_retrieval_ms': base_ms, 'incremental_feature_ms': (time.perf_counter()-begin)*1000,
                'producer': 'okpd_structure_v2', 'history_cutoff': base.CUTOFF,
                'coverage_semantics': 'historical text association, not confirmed product capability'}}
    return output


def run_variants(engine, q, budget=1500):
    return _run(engine, q, budget, VARIANTS)


def run_variant(engine, q, name, budget=1500):
    if name not in VARIANTS:
        raise ValueError('Unregistered variant')
    return _run(engine, q, budget, (name,))[name]
