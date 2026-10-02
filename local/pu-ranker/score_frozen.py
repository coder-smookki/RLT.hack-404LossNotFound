"""Score a new compatible P1 feature row using frozen numeric artifacts.

No labels/observed history targets are required. This only reorders the exact
supplied pool; feature construction remains owned by the retrieval producer.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from runner import literal, load_model, rank, sha, write_json


def score_row(row, artifact_directory):
    artifact_directory = Path(artifact_directory)
    lock = json.loads((artifact_directory / 'selection.lock.json').read_text())
    manifest_path = artifact_directory / 'input_manifest.json'
    if sha(manifest_path) != lock['input_manifest_sha256']:
        raise ValueError('Frozen model manifest changed')
    manifest = json.loads(manifest_path.read_text())
    if row.get('preprocessing') != manifest['preprocessing'] or row.get('history_cutoff') != manifest['history_cutoff']:
        raise ValueError('New features differ from frozen preprocessing/history snapshot contract')
    lot_id = literal(row['lot_id'], 'lot_id')
    choice = lock['selected']
    candidates = row['candidates']
    if not isinstance(candidates, list) or len(candidates) > 1500:
        raise ValueError('Candidate pool must be a list with at most 1500 candidates')
    names = lock['feature_names']
    ids, features, control = [], [], []
    for c in candidates:
        ids.append(literal(c['supplier_inn'], 'supplier_inn'))
        f = c['features']
        if set(f) != set(names) or any(isinstance(f[n], bool) or not isinstance(f[n], (int, float)) for n in names):
            raise ValueError('Finite numeric features with exact frozen names are required')
        values = [f[n] for n in names]
        weighted = 0.2 * f['R'] + 0.2 * f['O'] + 0.6 * f['T']
        supplied_weighted = float(c['weighted_score'])
        if not np.isfinite(values).all() or not np.isfinite(supplied_weighted) or abs(supplied_weighted - weighted) > 1e-6:
            raise ValueError('Invalid features or inconsistent Weighted control score')
        features.append(values)
        control.append(weighted)
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate candidate IDs')
    scores, logits, weighted_ranks, pu_ranks = [], [], [], []
    if candidates:
        x = np.asarray(features)
        ids_array = np.asarray(ids)
        control_array = np.asarray(control)
        weighted_ranks = np.empty(len(ids), dtype=int)
        weighted_ranks[rank(control_array, ids_array)] = np.arange(1, len(ids) + 1)
        if choice['method'] == 'weighted':
            scores = control_array
            logits = np.full(len(ids), np.nan)
            pu_ranks = np.zeros(len(ids), dtype=int)
        else:
            norm_path = artifact_directory / 'normalization.npz'
            if sha(norm_path) != lock['normalization_sha256']:
                raise ValueError('Frozen normalization changed')
            with np.load(norm_path, allow_pickle=False) as normal:
                mean, scale = normal['mean'], normal['scale']
                if mean.shape != (len(names),) or scale.shape != (len(names),) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or (scale <= 0).any():
                    raise ValueError('Invalid numeric normalization artifact')
                x = np.clip((x - mean) / scale, -6, 6)
            logits = load_model(artifact_directory, choice, lock).predict(x)
            if not np.isfinite(logits).all():
                raise ValueError('Nonfinite frozen model predictions')
            pu_ranks = np.empty(len(ids), dtype=int)
            pu_ranks[rank(logits, ids_array)] = np.arange(1, len(ids) + 1)
            alpha = choice['alpha']
            scores = (1 - alpha) / (60 + weighted_ranks) + alpha / (60 + pu_ranks)
    order = rank(np.asarray(scores), np.asarray(ids)) if candidates else []
    output = []
    for position, i in enumerate(order, 1):
        output.append({**candidates[i], 'scoring': {
            'rank': position, 'score': float(scores[i]), 'weighted_score': float(control[i]),
            'weighted_rank': int(weighted_ranks[i]),
            'pu_logit': float(logits[i]) if np.isfinite(logits[i]) else None,
            'pu_rank': int(pu_ranks[i]) if pu_ranks[i] else None}})
    return {'lot_id': lot_id, 'method': choice['method'], 'selected_model': choice.get('model'),
            'selection_sha256': sha(artifact_directory / 'selection.lock.json'),
            'score_semantics': 'ordering evidence only, not calibrated supplier relevance probability',
            'pool_preserved': True, 'candidates': output}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Output already exists; choose a new path')
    write_json(args.output, score_row(json.loads(args.input.read_text()), args.artifacts))
    print(json.dumps({'output': str(args.output.resolve())}))


if __name__ == '__main__':
    main()
