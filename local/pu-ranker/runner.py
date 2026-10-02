"""Frozen P1 candidate-pool pilot. Fit reads TRAIN+VALIDATION only; test is separate.

Uses the retrieval agent's JSONL contract. No winner/nonwinner labels, artificial
negative labels, identifiers as numerical features, or current enrichment.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
import platform
from pathlib import Path
import time
import numpy as np
from nnpu import Model, fit

PERIODS = {"train": ("2025-01-01", "2025-03-31"),
           "validation": ("2025-04-01", "2025-06-30"),
           "test": ("2025-07-01", "2025-12-31")}
KS = (10, 20, 50, 100, 300, 500, 1000, 1500)
PRIORS = (0.005, 0.02, 0.08)
HIDDEN = (0, 16)
ALPHAS = (0.0, 0.25, 0.5, 1.0)
SEED = 20261001


def write_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    os.replace(tmp, path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def guard(output):
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".running"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def literal(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a nonempty trimmed literal string")
    return value


def load(path, split, feature_names=None):
    export_manifest_path = Path(path).with_name(split + "_export_manifest.json")
    if not export_manifest_path.exists():
        raise ValueError("Input export is not frozen: missing split export manifest")
    export_manifest = json.loads(export_manifest_path.read_text())
    expected_sha = export_manifest["file_sha256"]
    actual_sha = sha(path)
    if actual_sha != expected_sha or export_manifest["split"] != split:
        raise ValueError("Export hash/split disagrees with frozen producer manifest")
    arrays, inn_lists, observation, sources, weights, baseline = [], [], [], [], [], []
    queries, seen = [], set()
    offset = 0
    preprocessing = None
    with Path(path).open() as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            if row.get("schema_version") != 1 or row.get("split") != split:
                raise ValueError(f"Row {line_number}: wrong schema/split")
            lot = literal(row["lot_id"], "lot_id")
            if lot in seen:
                raise ValueError(f"Duplicate query lot {lot}")
            seen.add(lot)
            published = row["publish_date"]
            date.fromisoformat(published)
            if not PERIODS[split][0] <= published <= PERIODS[split][1]:
                raise ValueError(f"Lot {lot}: date outside frozen period")
            if row["history_cutoff"] != "2024-12-31":
                raise ValueError("History cutoff differs from fixed common protocol")
            version = literal(row["preprocessing"], "preprocessing")
            preprocessing = version if preprocessing is None else preprocessing
            if version != preprocessing:
                raise ValueError("Mixed preprocessing versions")
            source = literal(row["source"], "source")
            truth = set(literal(x, "observed INN") for x in row["observed_inns"])
            known = set(row["known_observed_inns"])
            if not known <= truth or not truth:
                raise ValueError("Evaluation requires nonempty observed labels; known must be a subset")
            candidates = row["candidates"]
            ids, x, scores, seen_ids = [], [], [], set()
            for c in candidates:
                inn = literal(c["supplier_inn"], "supplier INN")
                if inn in seen_ids:
                    raise ValueError(f"Duplicate supplier in lot {lot}")
                seen_ids.add(inn)
                f = c["features"]
                if feature_names is None:
                    feature_names = sorted(f)
                    if any(any(v in name.casefold() for v in ("winner", "label", "target", "observed", "supplier_inn", "lot_id")) for name in feature_names):
                        raise ValueError("Forbidden target/identifier in pair-feature columns")
                if set(f) != set(feature_names):
                    raise ValueError(f"Lot {lot}: inconsistent feature columns")
                if any(not isinstance(f[name], (int, float)) or isinstance(f[name], bool) for name in feature_names):
                    raise ValueError("Feature values must be explicit numeric scalars")
                values = [f[name] for name in feature_names]
                score = float(c["weighted_score"])
                if not np.isfinite(values).all() or not np.isfinite(score):
                    raise ValueError("Nonfinite features/score")
                if abs(score - (0.2 * f["R"] + 0.2 * f["O"] + 0.6 * f["T"])) > 1e-6:
                    raise ValueError("Weighted control formula differs from frozen 0.2R+0.2O+0.6T")
                ids.append(inn)
                x.append(values)
                scores.append(score)
            n = len(ids)
            arrays.extend(x)
            inn_lists.extend(ids)
            observation.extend(inn in truth for inn in ids)
            sources.extend([source] * n)
            weights.extend([1 / n] * n if n else [])
            baseline.extend(scores)
            queries.append({"lot_id": lot, "source": source, "date": published,
                            "start": offset, "stop": offset + n,
                            "truth": truth, "known": known,
                            "diagnostics": row["query_diagnostics"],
                            "expanded_observed_inns": sorted((truth & seen_ids) - set(row.get("reference_pools", {}).get("depth_only_500", ids))),
                            "retrieval_feature_ms": row["retrieval_feature_ms"]})
            offset += n
    if len(queries) != export_manifest["rows"] or set(feature_names or []) != set(export_manifest["features"]):
        raise ValueError("Export rows/features differ from frozen producer manifest")
    if not queries or feature_names is None:
        raise ValueError("Empty query/feature export")
    return {"X": np.asarray(arrays, dtype=np.float32).reshape(-1, len(feature_names)),
            "inns": np.asarray(inn_lists), "observed": np.asarray(observation, dtype=bool),
            "sources": np.asarray(sources), "row_weights": np.asarray(weights),
            "baseline": np.asarray(baseline), "queries": queries,
            "features": feature_names, "preprocessing": preprocessing,
            "input_sha256": actual_sha, "producer_manifest_sha256": sha(export_manifest_path),
            "input_path": str(Path(path).resolve())}


def transformed(dataset, mean, scale):
    return np.clip((dataset["X"] - mean) / scale, -6, 6)


def scaler(train):
    # Equal-query base weighting, then equal-source weighting, fitted on TRAIN U.
    w = train["row_weights"].copy()
    for source in np.unique(train["sources"]):
        mask = train["sources"] == source
        w[mask] /= w[mask].sum()
    w /= w.sum()
    mean = np.average(train["X"], axis=0, weights=w)
    var = np.average((train["X"] - mean) ** 2, axis=0, weights=w)
    return mean, np.maximum(np.sqrt(var), 1e-4)


def rank(scores, ids):
    return np.lexsort((ids, -scores))


def fused_scores(dataset, logits, alpha):
    result = np.zeros(len(logits))
    for q in dataset["queries"]:
        s, e = q["start"], q["stop"]
        ids = dataset["inns"][s:e]
        a, b = rank(dataset["baseline"][s:e], ids), rank(logits[s:e], ids)
        ra, rb = np.empty(e - s), np.empty(e - s)
        ra[a], rb[b] = np.arange(1, e - s + 1), np.arange(1, e - s + 1)
        result[s:e] = (1 - alpha) / (60 + ra) + alpha / (60 + rb)
    return result


def query_metrics(order, truth, known, seen_positive_inns):
    p = len(truth)
    pos = [i for i, inn in enumerate(order, 1) if inn in truth]
    ideal = sum(1 / np.log2(i + 1) for i in range(1, min(p, 10) + 1))
    dcg = sum(1 / np.log2(i + 1) for i in pos if i <= 10)
    pool_ideal = sum(1 / np.log2(i + 1) for i in range(1, min(len(pos), 10) + 1))
    known_ideal = sum(1 / np.log2(i + 1) for i in range(1, min(len(known), 10) + 1))
    metrics = {"ndcg10": dcg / ideal,
               "ndcg10_pool_conditional": dcg / pool_ideal if pool_ideal else 0.0,
               "ndcg10_known_catalog": dcg / known_ideal if known_ideal else 0.0,
               "mrr": 1 / pos[0] if pos else 0.0,
               "observed_count": p, "known_count": len(known),
               "pool_hit_count": len(pos), "pool_recall": len(pos) / p,
               "known_pool_recall": len(set(order) & known) / len(known) if known else 0.0,
               "train_seen_positive_count": len(truth & seen_positive_inns),
               "train_unseen_positive_count": len(truth - seen_positive_inns)}
    for k in KS:
        top = set(order[:k])
        hits = len(top & truth)
        metrics[f"hits{k}"] = hits
        metrics[f"recall{k}"] = hits / p
        metrics[f"hit{k}"] = float(hits > 0)
        metrics[f"train_seen_hits{k}"] = len(top & truth & seen_positive_inns)
        metrics[f"train_unseen_hits{k}"] = len((top & truth) - seen_positive_inns)
    return metrics


def aggregate(rows):
    if not rows:
        return {"queries": 0}
    names = ("ndcg10", "ndcg10_pool_conditional", "ndcg10_known_catalog", "mrr", "pool_recall", "known_pool_recall") + tuple(
        f"{prefix}{k}" for k in KS for prefix in ("recall", "hit"))
    result = {"queries": len(rows), **{name: float(np.mean([r[name] for r in rows])) for name in names}}
    positives = sum(r["observed_count"] for r in rows)
    result["observed_pairs"] = positives
    available = all(r.get("expanded_diagnostic_available", False) for r in rows)
    result["expanded_diagnostic_available"] = available
    result["expanded_observed_pairs_vs_depth500"] = sum(r.get("expanded_observed_count", 0) for r in rows) if available else None
    result["expanded_promotions"] = {str(k): sum(sum(rank <= k for rank in r.get("expanded_observed_ranks", {}).values()) for r in rows) for k in KS} if available else None
    result["pool_recall_micro"] = sum(r["pool_hit_count"] for r in rows) / positives
    for k in KS:
        result[f"recall{k}_micro"] = sum(r[f"hits{k}"] for r in rows) / positives
        for flag in ("seen", "unseen"):
            denom = sum(r[f"train_{flag}_positive_count"] for r in rows)
            result[f"train_{flag}_recall{k}_micro"] = sum(r[f"train_{flag}_hits{k}"] for r in rows) / denom if denom else None
    return result


def evaluate(dataset, scores, seen_positive_inns):
    rows = []
    rank_ms = []
    for q in dataset["queries"]:
        start = time.perf_counter()
        s, e = q["start"], q["stop"]
        order = dataset["inns"][s:e][rank(scores[s:e], dataset["inns"][s:e])].tolist()
        rank_ms.append(1000 * (time.perf_counter() - start))
        expanded = set(q.get("expanded_observed_inns", []))
        ranks = {inn: i + 1 for i, inn in enumerate(order) if inn in expanded}
        rows.append({"lot_id": q["lot_id"], "source": q["source"], "diagnostics": q["diagnostics"],
                     "expanded_observed_ranks": ranks, "expanded_observed_count": len(expanded),
                     "expanded_diagnostic_available": "expanded_observed_inns" in q,
                     "top10": order[:10], **query_metrics(order, q["truth"], q["known"], seen_positive_inns)})
    by_source = {source: aggregate([r for r in rows if r["source"] == source]) for source in sorted({r["source"] for r in rows})}
    diagnostics = {}
    for field in ("rare", "unseen_code", "unseen_exact_code", "unseen_branch4", "code_text_disagreement", "identifier_rich"):
        present = [r for r in rows if field in r["diagnostics"]]
        if present:
            diagnostics[field] = {str(value): aggregate([r for r in present if bool(r["diagnostics"][field]) == value]) for value in (False, True)}
    return {"overall": aggregate(rows), "by_source": by_source, "diagnostics": diagnostics,
            "rank_only_ms": {"mean": float(np.mean(rank_ms)), "p95": float(np.percentile(rank_ms, 95))}, "per_query": rows}


def summary(result):
    return {k: v for k, v in result.items() if k != "per_query"}


def source_safe(candidate, baseline):
    return candidate["overall"]["ndcg10"] >= baseline["overall"]["ndcg10"] and all(
        candidate["by_source"][s]["ndcg10"] >= values["ndcg10"] - 0.01
        for s, values in baseline["by_source"].items())


def fit_and_select(train_path, validation_path, output, steps):
    if (output / "selection.lock.json").exists() or (output / "test_results.json").exists():
        raise FileExistsError("Fresh output required; existing selection/test is frozen")
    train = load(train_path, "train")
    validation = load(validation_path, "validation", train["features"])
    if train["preprocessing"] != validation["preprocessing"]:
        raise ValueError("Different train/validation preprocessing")
    train_lots = {q["lot_id"] for q in train["queries"]}
    if train_lots & {q["lot_id"] for q in validation["queries"]}:
        raise ValueError("Train/validation query overlap")
    seen_positive_inns = set().union(*(q["truth"] for q in train["queries"]))
    for split_name, dataset in (("train", train), ("validation", validation)):
        np.savez_compressed(output / (split_name + "_arrays.npz"), X=dataset["X"],
                            observed=dataset["observed"], sources=dataset["sources"],
                            row_weights=dataset["row_weights"], baseline=dataset["baseline"],
                            inns=dataset["inns"])
        write_json(output / (split_name + "_queries.json"), [{**q, "truth": sorted(q["truth"]),
                   "known": sorted(q["known"])} for q in dataset["queries"]])
    mean, scale = scaler(train)
    tx, vx = transformed(train, mean, scale), transformed(validation, mean, scale)
    baseline = evaluate(validation, validation["baseline"], seen_positive_inns)
    best = {"method": "weighted", "alpha": 0.0, "validation": summary(baseline)}
    best_ndcg = baseline["overall"]["ndcg10"]
    best_pure = None
    best_pure_ndcg = -1.0
    results = []
    manifest = {"train_sha256": train["input_sha256"], "validation_sha256": validation["input_sha256"],
                "features": train["features"], "preprocessing": train["preprocessing"],
                "periods": PERIODS, "history_cutoff": "2024-12-31",
                "query_counts": {"train": len(train["queries"]), "validation": len(validation["queries"])},
                "source_counts": {"train": dict(Counter(q["source"] for q in train["queries"])),
                                  "validation": dict(Counter(q["source"] for q in validation["queries"]))},
                "train_observed_retrieved_pairs": int(train["observed"].sum()),
                "train_marginal_pairs": len(tx), "feature_fit": "train only, equal query and source weights",
                "PU_risk": "Kiryo2017 Eq6 logistic nnPU, U=whole pool including P",
                "priors": PRIORS, "hidden_widths": HIDDEN, "alphas": ALPHAS,
                "steps": steps, "seed": SEED, "l2": 0.001, "learning_rate": 0.01,
                "environment": {"platform": platform.platform(), "machine": platform.machine(), "numpy": np.__version__},
                "producer_manifests": {"train_sha256": train["producer_manifest_sha256"], "validation_sha256": validation["producer_manifest_sha256"]},
                "score_semantics": "ranking score, not calibrated supplier relevance probability",
                "selection": "highest validation NDCG10; each source drop <=.01; ties retain simpler Weighted",
                "test_status": "not opened by fit; historical diagnostic replay, not blind holdout"}
    write_json(output / "input_manifest.json", manifest)
    np.savez_compressed(output / "normalization.npz", mean=mean, scale=scale)
    for hidden in HIDDEN:
        for prior in PRIORS:
            name = f"nnpu_h{hidden}_pi{prior:g}"
            t = time.perf_counter()
            try:
                model, info = fit(tx, train["observed"], train["sources"], prior=prior,
                                  hidden=hidden, steps=steps, row_weights=train["row_weights"])
            except ValueError as error:
                results.append({"model": name, "rejected": str(error)})
                continue
            fit_s = time.perf_counter() - t
            path = output / (name + ".npz")
            np.savez_compressed(path, **model.parameters)
            prediction_start = time.perf_counter()
            logits = model.predict(vx)
            prediction_ms = 1000 * (time.perf_counter() - prediction_start)
            variants = []
            for alpha in ALPHAS:
                sc = fused_scores(validation, logits, alpha)
                result = evaluate(validation, sc, seen_positive_inns)
                variants.append({"alpha": alpha, "metrics": summary(result)})
                n = result["overall"]["ndcg10"]
                if alpha == 1.0 and n > best_pure_ndcg:
                    best_pure_ndcg = n
                    best_pure = {"model": name, "hidden": hidden, "prior": prior,
                                 "alpha": 1.0, "validation": summary(result)}
                if alpha > 0 and source_safe(result, baseline) and n > best_ndcg + 1e-12:
                    best_ndcg = n
                    best = {"method": "nnpu_fusion", "model": name, "hidden": hidden,
                            "prior": prior, "alpha": alpha, "validation": summary(result)}
            results.append({"model": name, "training": info, "fit_seconds": fit_s,
                            "validation_prediction_total_ms": prediction_ms,
                            "validation_prediction_ms_per_query": prediction_ms / len(validation["queries"]),
                            "variants": variants})
            print(name, "fit_s", round(fit_s, 2), "pure_ndcg", variants[-1]["metrics"]["overall"]["ndcg10"], flush=True)
            write_json(output / "validation_progress.json", results)
    if best_pure is None:
        raise ValueError("No PU prior/model accepted on train")
    lock = {"selected": best, "exploratory_pure": best_pure,
            "train_positive_inns": sorted(seen_positive_inns), "train_lots": sorted(train_lots),
            "validation_lots": [q["lot_id"] for q in validation["queries"]],
            "feature_names": train["features"], "baseline_validation": summary(baseline),
            "input_manifest_sha256": sha(output / "input_manifest.json"),
            "normalization_sha256": sha(output / "normalization.npz"),
            "model_sha256": {r["model"]: sha(output / (r["model"] + ".npz")) for r in results if "rejected" not in r},
            "test_methods_predeclared": ["weighted_same_pool", "selected_fusion", "best_validation_pu_only"],
            "test_evaluated": False, "validation": results}
    write_json(output / "selection.lock.json", lock)
    print("selection", best.get("model", "weighted"), "alpha", best["alpha"], "val_ndcg", best_ndcg, flush=True)
    return lock


def load_model(output, choice, lock):
    model_path = output / (choice["model"] + ".npz")
    if sha(model_path) != lock["model_sha256"][choice["model"]]:
        raise ValueError("Frozen model changed")
    model = Model(len(lock["feature_names"]), hidden=choice["hidden"], prior=choice["prior"])
    with np.load(model_path, allow_pickle=False) as data:
        for name in model.parameters:
            value = data[name]
            if value.shape != model.parameters[name].shape or not np.isfinite(value).all():
                raise ValueError("Invalid saved parameter")
            model.parameters[name] = value.copy()
    return model


def bootstrap(a, b):
    delta = np.asarray([x["ndcg10"] - y["ndcg10"] for x, y in zip(a, b)])
    if len(a) != len(b) or any(x["lot_id"] != y["lot_id"] for x, y in zip(a, b)):
        raise ValueError("Bootstrap queries must pair by lot")
    rng = np.random.default_rng(SEED)
    values = delta[rng.integers(0, len(delta), (5000, len(delta)))].mean(axis=1)
    return {"delta_ndcg10": float(delta.mean()), "paired_query_bootstrap95": np.quantile(values, [.025, .975]).tolist(),
            "resamples": 5000, "seed": SEED, "queries_improved": int((delta > 1e-12).sum()),
            "queries_regressed": int((delta < -1e-12).sum())}


def evaluate_test(test_path, output):
    if (output / "test_results.json").exists() or (output / "test_started.lock.json").exists():
        raise FileExistsError("Test already evaluated/started; do not retune or silently rerun")
    lock = json.loads((output / "selection.lock.json").read_text())
    if sha(output / "input_manifest.json") != lock["input_manifest_sha256"] or sha(output / "normalization.npz") != lock["normalization_sha256"]:
        raise ValueError("Frozen manifest/normalization changed")
    data = load(test_path, "test", lock["feature_names"])
    manifest = json.loads((output / "input_manifest.json").read_text())
    if data["preprocessing"] != manifest["preprocessing"]:
        raise ValueError("Different frozen test preprocessing")
    if {q["lot_id"] for q in data["queries"]} & set(lock["train_lots"] + lock["validation_lots"]):
        raise ValueError("Test query overlap")
    write_json(output / "test_started.lock.json", {"selection_sha256": sha(output / "selection.lock.json"),
                                                  "test_sha256": data["input_sha256"]})
    with np.load(output / "normalization.npz", allow_pickle=False) as normal:
        x = transformed(data, normal["mean"], normal["scale"])
    seen = set(lock["train_positive_inns"])
    baseline = evaluate(data, data["baseline"], seen)
    choices = {"selected_fusion": lock["selected"], "best_validation_pu_only": lock["exploratory_pure"]}
    results = {"weighted_same_pool": baseline}
    for name, choice in choices.items():
        if choice.get("method") == "weighted":
            results[name] = baseline
            continue
        start = time.perf_counter()
        logits = load_model(output, choice, lock).predict(x)
        predict_ms = 1000 * (time.perf_counter() - start)
        fusion_start = time.perf_counter()
        scores = fused_scores(data, logits, choice["alpha"])
        fusion_ms = 1000 * (time.perf_counter() - fusion_start)
        result = evaluate(data, scores, seen)
        result["prediction_and_model_load_total_ms"] = predict_ms
        result["prediction_ms_per_query"] = predict_ms / len(data["queries"])
        result["fusion_ms_per_query"] = fusion_ms / len(data["queries"])
        result["comparison"] = bootstrap(result["per_query"], baseline["per_query"])
        results[name] = result
    result = {"test_sha256": data["input_sha256"], "selection_sha256": sha(output / "selection.lock.json"),
              "methods": results, "latency_scope": "cached pair-feature prediction + ranking; retrieval_feature_ms retained separately; no HTTP/enrichment",
              "retrieval_feature_ms": {"mean": float(np.mean([q["retrieval_feature_ms"] for q in data["queries"]])),
                                       "p95": float(np.percentile([q["retrieval_feature_ms"] for q in data["queries"]], 95))},
              "positive_semantics": "observed supplier-lot relation, not adjudicated capability relevance; nonobserved unjudged",
              "runner_sha256_at_test": sha(Path(__file__)), "nnpu_sha256_at_test": sha(Path(__file__).with_name("nnpu.py")),
              "denominators": "macro metrics average query fractions; micro recall divides retrieved observed pairs by all observed pairs; absent profiles stay misses",
              "not_blind_holdout": True}
    write_json(output / "test_results.json", result)
    print(json.dumps({name: summary(value) for name, value in results.items()}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    train = commands.add_parser("fit")
    train.add_argument("--train", type=Path, required=True)
    train.add_argument("--validation", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--steps", type=int, default=600)
    test = commands.add_parser("test")
    test.add_argument("--test", type=Path, required=True)
    test.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "fit" and args.steps < 1:
        parser.error("--steps must be positive")
    with guard(args.output):
        if args.action == "fit":
            fit_and_select(args.train, args.validation, args.output, args.steps)
        else:
            evaluate_test(args.test, args.output)


if __name__ == "__main__":
    main()
