"""Two source CSVs -> accepted historical ranking plus current external leads."""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlt_lab.input import read_procurements
from rlt_lab.evidence_matching import compare_evidence
from rlt_lab.external_evidence import ExternalCatalog

S9_INDEX_SHA256 = "08d9d6fbc53d902e45f19223f05ce399b83caf320bc31e659cedad2365d745b6"
FRESH_COMPANIES_SHA256 = "4860d9c9a8359078ade05745a9f57fb726fba888c325984b5f6e97da221bcc19"
ACTIVITY_PATCH_SHA256 = "2cf9316762de3642c3a4b6df914de272d9b9a360bda29b4a490236d69cf95947"
EXPANSION_SHA256 = "10e405323753d9efb85741aefd62b2092f5f28acf5812d6e4e3a40a4784f4d31"
REGISTRY_SHA256 = "7b8a333faca3ec8e193d05e76afb47e4e1cf7e48740f04c9cb699601453ba3a5"


def frozen_adapter():
    spec = importlib.util.spec_from_file_location("rlt_existing_frozen_adapter", ROOT / "scripts/recommend_frozen_p1.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter


def historical_item_evidence(module, raw_items, history, raw_history):
    result = []
    for index, item in enumerate(raw_items):
        terms = set(module.representation(item["product_name"])[1])
        examples = []
        for lot in history:
            fragments = []
            for fragment in lot["items"]:
                text = fragment["history_text_projection"]
                overlap = len(terms & set(module.representation(text)[1])) / max(1, len(terms))
                if overlap:
                    fragments.append((overlap, fragment))
            fragments.sort(key=lambda x: (-x[0], x[1]["source_item_row_id"]))
            for overlap, fragment in fragments[:1]:
                source = raw_history.execute(
                    "SELECT product_name FROM items WHERE row_id=? AND lot_id=?",
                    (fragment["source_item_row_id"], lot["lot_id"])).fetchone()
                raw = source[0] if source else None
                if raw is not None and module.canonical(raw) != fragment["history_text_projection"]:
                    raise ValueError("Original history row differs from frozen text projection")
                technical = compare_evidence(item["product_name"], raw) if raw is not None else {
                    "status": "unknown", "reason": "raw_case_sensitive_text_unavailable"}
                examples.append({"lot_id": lot["lot_id"], "source_item_row_id": fragment["source_item_row_id"],
                                 "text_token_overlap": overlap, "history_text_projection": fragment["history_text_projection"],
                                 "raw_history_text": raw, "technical_comparison": technical})
        result.append({"item_index": index, "raw_item": item, "historical_fragments": examples,
                       "coverage": "unjudged"})
    return result


class EnrichedRuntime:
    """One reusable runtime. Construct, call and close on the same thread."""

    def __init__(self, external_catalog=None):
        started = time.perf_counter()
        self.adapter = frozen_adapter()
        self.module, self.engine, self.scorer = self.adapter.load_runtime()
        self.raw_history = None
        try:
            self.raw_history = sqlite3.connect((ROOT / "local/history.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
            self.raw_history.execute("PRAGMA query_only=ON")
            self.adapter.load_neighbor35_scorer()
            path = external_catalog or ROOT / "local/release-s9-audit/release/runtime_release/artifacts/runtime_index.sqlite"
            self.catalog = ExternalCatalog(path, lambda text: self.module.representation(text)[1],
                                           expected_sha256=S9_INDEX_SHA256,
                                           as_of=datetime.now(ZoneInfo("Europe/Moscow")).date(),
                                           fresh_companies_path=ROOT / "local/enrichment-36m/companies.json",
                                           fresh_companies_sha256=FRESH_COMPANIES_SHA256,
                                           activity_patch_path=ROOT / "local/enrichment-36m-dated-v2/reviewed_activity_patch.json",
                                           activity_patch_sha256=ACTIVITY_PATCH_SHA256,
                                           reviewed_batches=((ROOT / "local/registry-enrichment-expansion/companies.json", EXPANSION_SHA256),),
                                           registry_batches=((ROOT / "local/colleague-enrichment-2026-10-02/registry_companies.json", REGISTRY_SHA256),))
            self.full_history_inns = {row[0] for row in self.raw_history.execute(
                "SELECT DISTINCT trim(supplier_inn) FROM suppliers")}
            for inn, profiles in self.catalog.by_inn.items():
                if any(bool(p["has_s9_historical"]) != (inn in self.full_history_inns) for p in profiles):
                    raise ValueError("External history-membership claim differs from full source history")
            self.frozen_inns = set(self.engine.companies)
            self.load_ms = (time.perf_counter() - started) * 1000
        except Exception:
            self.close()
            raise

    def recommend(self, notices_path, items_path, top_k=10, *, max_lots=100, max_items=10000):
        if not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")
        started = time.perf_counter()
        inputs = read_procurements(Path(notices_path), Path(items_path))
        if len(inputs) > max_lots or sum(len(lot["items"]) for lot in inputs) > max_items:
            raise ValueError(f"Batch exceeds local service limits: {max_lots} lots / {max_items} TRU rows")
        lots = []
        for inputs_lot in inputs:
            query = self.adapter.query_projection(self.module, self.engine, inputs_lot["notice"], inputs_lot["items"])
            result = self.adapter.recommend(self.module, self.engine, self.scorer, query, top_k, ranker="neighbor35")
            for candidate in result["recommendations"]:
                candidate["external_item_evidence"] = self.catalog.evidence_for(candidate["supplier_inn"], query["items"])
                candidate["historical_item_evidence"] = historical_item_evidence(
                    self.module, query["items"], candidate["evidence"], self.raw_history)
            result["notice"] = inputs_lot["notice"]
            shown_inns = {candidate["supplier_inn"] for candidate in result["recommendations"]}
            result["new_supplier_candidates"] = self.catalog.discover(
                query["items"], self.frozen_inns, limit=top_k, exclude_inns=shown_inns)
            for candidate in result["new_supplier_candidates"]:
                candidate["new_to_full_history"] = candidate["supplier_inn"] not in self.full_history_inns
            result["evaluation_mode"] = "current_external_overlay_not_historical_replay"
            lots.append(result)
        return {"version": "enriched-csv-v6", "ranker": "neighbor35", "history_cutoff": self.module.CUTOFF,
                "input_sha256": {"notices": self.adapter.digest(notices_path), "items": self.adapter.digest(items_path)},
                "query_count": len(lots), "external_catalog": self.catalog.metadata(), "lots": lots,
                "runtime_load_ms": self.load_ms, "whole_batch_ms": (time.perf_counter() - started) * 1000,
                "score_semantics": "Historical ranking scores and external retrieval scores are distinct, not suitability probabilities"}

    def close(self):
        if self.raw_history is not None:
            self.raw_history.close()
        self.engine.con.close()
        if hasattr(self.engine, "_okpd_structure_v2"):
            self.engine._okpd_structure_v2["con"].close()


def main():
    parser = argparse.ArgumentParser(description="Закупки + ТРУ -> nnPU35 и отдельные актуальные внешние основания")
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external-catalog", type=Path)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new path")
    runtime = EnrichedRuntime(args.external_catalog)
    try:
        output = runtime.recommend(args.notices, args.items, args.top_k)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output.resolve()), "query_count": output["query_count"],
                          "whole_batch_ms": output["whole_batch_ms"], "catalog": runtime.catalog.metadata()}, ensure_ascii=False))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
