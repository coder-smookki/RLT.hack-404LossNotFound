"""Local CSV -> frozen P1 pool -> accepted nnPU -> historical evidence.

This research adapter reuses the exact frozen producer and scorer. It never
rebuilds their indexes or treats historical participation as product coverage.
"""
from __future__ import annotations
import argparse
from functools import lru_cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from rlt_lab.input import read_procurements

# Verified source code used by the accepted numeric models. Check transitive
# local imports before executing them, not only their NPZ parameters afterwards.
RANKER_CODE_SHA256 = {
    "score_frozen.py": "5d08777ddfc5b65e0d0ce0e97a020a2912f084284e189d3d3ba41fc917aa534f",
    "runner.py": "498f830f6d01d6405609767d89925196fa069e63e3d7b92a09e4cda1b766385e",
    "nnpu.py": "7954b74503fcae0408f9a5665e9ccd607fa706b64348d2c0a437cfa977bfafa5",
}
NEIGHBOR35_SCORER_SHA256 = "e5248105fe3f853c52eb32412225b10dedb8551248ec457a0823b25aca9705f8"
NEIGHBOR35_REPAIR_SHA256 = "387b26eecd00ed887a602cfb77c9432e27e6c6446ce4c7a247160edbc447b88e"


def digest(path):
    h = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_ranker_code(repo=REPO):
    for name, expected in RANKER_CODE_SHA256.items():
        if digest(Path(repo) / "local/pu-ranker" / name) != expected:
            raise ValueError("Frozen numeric scorer dependency changed: " + name)


def load_runtime(repo=REPO):
    producer = Path(repo) / "local/retrieval-router"
    producer_manifest = json.loads((producer / "index_artifact_manifest.json").read_text())
    lock = json.loads((producer / "protocol.lock.json").read_text())
    if digest(producer / "engine.py") != lock["engine_sha256_before_evaluation"]:
        raise ValueError("Frozen retrieval producer changed")
    for name in ("snapshot.sqlite", "snapshot_manifest.json", "char_index.npz", "char_vocabulary.json", "char_idf.npy"):
        if digest(producer / name) != producer_manifest[name]["sha256"]:
            raise ValueError(f"Frozen retrieval artifact changed: {name}")
    engine_module = load_module("rlt_frozen_p1_producer", producer / "engine.py")
    engine = engine_module.Engine()
    try:
        engine.load_char()
        verify_ranker_code(repo)
        sys.path.insert(0, str(Path(repo) / "local/pu-ranker"))
        scorer = load_module("rlt_frozen_p1_scorer", Path(repo) / "local/pu-ranker/score_frozen.py")
        return engine_module, engine, scorer
    except BaseException:
        engine.con.close()
        raise


def query_projection(module, engine, notice, items):
    if notice["publish_date"] <= module.CUTOFF:
        raise ValueError("This frozen research snapshot requires a query after 2024-12-31")
    if engine.con.execute("SELECT 1 FROM history_notices WHERE lot_id=?", (notice["lot_id"],)).fetchone():
        raise ValueError("Input lot_id collides with a lot in the frozen history")
    codes = {item["okpd2_code"].strip() for item in items if item["okpd2_code"].strip()}
    return {"lot_id": notice["lot_id"], "publish_date": notice["publish_date"],
            "customer_inn": notice["customer_inn"], "subject": notice["subject"],
            "source": notice["is_eshop_or_aisgz"], "items": items,
            "rare": not codes or min(engine.freq.get(code[:5], 0) for code in codes) <= 100,
            "unseen_code": any(code not in engine.cat for code in codes),
            "unseen_exact_code": any(code not in engine.cat for code in codes),
            "unseen_branch4": any(code[:5] not in engine.freq for code in codes)}


def feature_row(module, engine, query):
    channels = engine.channels(query, depth=1500, rich=True)
    pool, ranks, _ = engine.pool(channels, budget=1500, adaptive=False)
    candidates = engine.features(channels, pool, ranks)
    return {"lot_id": query["lot_id"], "preprocessing": module.PREPROCESS,
            "history_cutoff": module.CUTOFF, "candidates": candidates}, channels["diagnostics"]


@lru_cache(maxsize=1)
def load_neighbor35_scorer():
    """Load the frozen35 model only after its independent reserve passed."""
    lab = REPO / "local/neighbor-ml-v3"
    reserve = REPO / "local/next-cycle-v3"
    accepted = json.loads((reserve / "reserve.results.json").read_text())
    if accepted["decision"] != "GO" or not all(accepted["acceptance_gates"].values()):
        raise ValueError("The35-feature model has not passed independent reserve gates")
    if digest(reserve / "reserve.evaluation.lock.json") != accepted["evaluation_lock_sha256"]:
        raise ValueError("Independent acceptance lock changed")
    evaluation = json.loads((reserve / "reserve.evaluation.lock.json").read_text())
    model_dir = lab / "cuda-results"
    if digest(model_dir / "selection.lock.json") != evaluation["selection_sha256"]:
        raise ValueError("Validation-selected model changed after independent reserve")
    selection = json.loads((model_dir / "selection.lock.json").read_text())
    if digest(lab / "protocol.lock.json") != selection["protocol_sha256"]:
        raise ValueError("Frozen35 code protocol changed")
    protocol = json.loads((lab / "protocol.lock.json").read_text())
    if digest(lab / "features.py") != protocol["code_sha256"]["features.py"]:
        raise ValueError("Frozen35 feature implementation changed")
    # Keep the pre-evaluation implementation as immutable evidence. The only
    # separately recorded inference repair adds provenance to an empty result.
    if digest(lab / "locked-code/scorer.py") != protocol["code_sha256"]["scorer.py"]:
        raise ValueError("Original frozen35 scorer snapshot changed")
    if digest(lab / "inference-repair.lock.json") != NEIGHBOR35_REPAIR_SHA256 or digest(lab / "scorer.py") != NEIGHBOR35_SCORER_SHA256:
        raise ValueError("Approved empty-result metadata repair changed")
    if digest(model_dir / "input_manifest.json") != selection["input_manifest_sha256"]:
        raise ValueError("Frozen35 feature contract changed")
    contract = json.loads((model_dir / "input_manifest.json").read_text())
    for name, key in (("variants.py", "variants_sha256"), ("history_aux.sqlite", "auxiliary_sha256")):
        if digest(REPO / "local/okpd-structure-v2" / name) != contract["history"][key]:
            raise ValueError("Frozen neighbour history changed: " + name)
    sys.path.insert(0, str(lab))
    verify_ranker_code()
    module = load_module("rlt_frozen_neighbor35_scorer", lab / "scorer.py")
    return module, module.ReusableInferenceScorer(model_dir)


def historical_evidence(module, engine, query, inn):
    # Bounded evidence display, not an exhaustive capability search.
    notices = engine.con.execute(
        "SELECT n.lot_id,n.publish_date,n.subject,n.source,p.raw_min_row,p.raw_rows "
        "FROM participation p JOIN history_notices n USING(lot_id) "
        "WHERE p.inn=? ORDER BY n.publish_date DESC,n.lot_id LIMIT 80", (inn,)).fetchall()
    query_terms = set(t for item in query["items"] for t in module.representation(item["product_name"])[1])
    if not query_terms:
        query_terms = set(module.representation(query["subject"])[1])
    examples = []
    for lot, date, subject, source, raw_row, count in notices:
        assert date <= module.CUTOFF and lot != query["lot_id"]
        items = [{"history_text_projection": text, "raw_okpd2_code": code,
                  "source_item_row_id": raw_item, "source_item_rows": n}
                 for text, code, raw_item, n in engine.con.execute(
                     "SELECT retrieval_text,code,raw_min_row,raw_rows FROM history_items WHERE lot_id=? ORDER BY raw_min_row", (lot,))]
        terms = set(t for item in items for t in module.representation(item["history_text_projection"])[1])
        overlap = len(terms & query_terms) / max(1, len(query_terms))
        examples.append({"lot_id": lot, "publish_date": date, "subject": subject, "source": source,
                         "source_supplier_row_id": raw_row, "source_supplier_rows": count,
                         "text_token_overlap": overlap, "items": items})
    examples.sort(key=lambda x: (-x["text_token_overlap"], x["lot_id"]))
    return examples[:2]


def recommend(module, engine, scorer, query, top_k=10, evidence=True, ranker="original34"):
    started = time.perf_counter()
    row, diagnostics = feature_row(module, engine, query)
    if ranker == "neighbor35":
        neighbor_module, neighbor_model = load_neighbor35_scorer()
        row = neighbor_module.make_feature_row(engine, query, row["candidates"])
        scored = neighbor_model.score(row)
        diagnostics = {**diagnostics, "neighbor_lot_evidence": row["neighbor_diagnostics"]}
    elif ranker == "original34":
        scored = scorer.score_row(row, REPO / "local/pu-ranker/pilot_v1")
    else:
        raise ValueError("Unknown ranker: " + str(ranker))
    recommendations = []
    for candidate in scored["candidates"][:top_k]:
        f = candidate["features"]
        recommendations.append({
            "supplier_inn": candidate["supplier_inn"], "scoring": candidate["scoring"],
            "reasons": {"text_association": f["T"], "okpd2_association": f["O"],
                        "retrieval_agreement": f["R"], "technical_token_overlap": f["protected_overlap"],
                        "minimum_item_text_association": f["item_coverage_min"],
                        **({"neighbor_lot_evidence": f["neighbor_lot_evidence"]} if ranker == "neighbor35" else {})},
            "evidence_scope": "Observed participant of historical lots containing similar TRU; this does not prove supply, availability or coverage of every item.",
            "company_role": {"status": "unverified", "value": None},
            "novelty": "known_in_provided_2024_history",
            "evidence": historical_evidence(module, engine, query, candidate["supplier_inn"]) if evidence else [],
        })
    return {"lot_id": query["lot_id"], "raw_items": query["items"],
            "status": "ranked_historical_candidates" if recommendations else "insufficient_historical_candidates",
            "query_diagnostics": diagnostics, "candidate_count": len(row["candidates"]),
            "feature_version": row.get("feature_version", "p1_conservative_local_1_34"),
            "method": scored["method"], "model_selection_sha256": scored["selection_sha256"],
            "recommendations": recommendations,
            "inference_ms": 1000 * (time.perf_counter() - started)}


def main():
    parser = argparse.ArgumentParser(description="Локальный research runner: CSV закупок/ТРУ -> frozen P1 + nnPU с историческими основаниями")
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--ranker", choices=("neighbor35", "original34"), default="neighbor35",
                        help="Принятый35-feature nnPU или явный предыдущий34-feature baseline")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("top-k must be between 1 and 100")
    if args.output.exists():
        parser.error("Output exists; choose a new path")
    queries = read_procurements(args.notices, args.items)
    start = time.perf_counter()
    module, engine, scorer = load_runtime()
    try:
        if args.ranker == "neighbor35":
            load_neighbor35_scorer()
        load_ms = 1000 * (time.perf_counter() - start)
        results = [recommend(module, engine, scorer, query_projection(module, engine, q["notice"], q["items"]), args.top_k, ranker=args.ranker) for q in queries]
    finally:
        engine.con.close()
        if hasattr(engine, "_okpd_structure_v2"):
            engine._okpd_structure_v2["con"].close()
    output = {"history_cutoff": module.CUTOFF, "preprocessing": module.PREPROCESS,
              "score_semantics": "Ranking score, not calibrated supplier suitability probability",
              "limitations": ["Historical participant associations are incomplete weak observations",
                              "Outcome availability dates unknown", "Company roles and current assortment unverified",
                              "No external-company enrichment in this frozen research runner"],
              "input_sha256": {"notices": digest(args.notices), "items": digest(args.items)},
              "ranker": args.ranker,
              "query_count": len(queries), "runtime_load_ms": load_ms,
              "whole_batch_ms": 1000 * (time.perf_counter() - start), "lots": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(output, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "query_count": len(queries),
                      "whole_batch_ms": output["whole_batch_ms"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
