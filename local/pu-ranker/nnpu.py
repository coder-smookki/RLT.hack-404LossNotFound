"""Small numerical nnPU model; unlabeled rows never become negative labels.

P is a sample of observed positives, U is a sample of the whole marginal pool
(including observed P). Uses logistic loss and the nonnegative empirical risk
in Kiryo et al. 2017, Eq. 6. Unknown priors and SCAR are research assumptions.
"""
from __future__ import annotations
import numpy as np


def sigmoid(x):
    return np.exp(-np.logaddexp(0.0, -np.asarray(x)))


def risk_and_grad(positive_logits, marginal_logits, prior):
    if not 0 < prior < 1:
        raise ValueError("PU prior must be strictly between zero and one")
    p = np.asarray(positive_logits, dtype=np.float64)
    u = np.asarray(marginal_logits, dtype=np.float64)
    if p.ndim != 1 or u.ndim != 1 or not len(p) or not len(u):
        raise ValueError("Both positive and marginal batches must be nonempty vectors")
    if not np.isfinite(p).all() or not np.isfinite(u).all():
        raise ValueError("Logits must be finite")
    positive_risk = prior * np.logaddexp(0.0, -p).mean()
    negative_risk = np.logaddexp(0.0, u).mean() - prior * np.logaddexp(0.0, p).mean()
    dp = prior * (sigmoid(p) - 1.0) / len(p)
    du = np.zeros_like(u)
    if negative_risk > 0.0:
        dp -= prior * sigmoid(p) / len(p)
        du += sigmoid(u) / len(u)
    return float(positive_risk + max(0.0, negative_risk)), dp, du, float(negative_risk)


class Model:
    def __init__(self, features, hidden=0, seed=20261001, prior=0.02):
        self.hidden = hidden
        rng = np.random.default_rng(seed)
        bias = np.log(prior / (1 - prior))
        if hidden:
            self.parameters = {
                "w1": rng.normal(0, 0.1 / np.sqrt(features), (features, hidden)),
                "b1": np.zeros(hidden),
                "w2": rng.normal(0, 0.1 / np.sqrt(hidden), hidden),
                "b2": np.asarray([bias]),
            }
        else:
            self.parameters = {"w": np.zeros(features), "b": np.asarray([bias])}

    def forward(self, x):
        if not self.hidden:
            return x @ self.parameters["w"] + self.parameters["b"][0], None
        h = np.tanh(x @ self.parameters["w1"] + self.parameters["b1"])
        return h @ self.parameters["w2"] + self.parameters["b2"][0], h

    def backward(self, x, hidden, d):
        if not self.hidden:
            return {"w": x.T @ d, "b": np.asarray([d.sum()])}
        dh = d[:, None] * self.parameters["w2"] * (1 - hidden * hidden)
        return {"w1": x.T @ dh, "b1": dh.sum(axis=0),
                "w2": hidden.T @ d, "b2": np.asarray([d.sum()])}

    def predict(self, x):
        result = []
        for start in range(0, len(x), 8192):
            result.append(self.forward(x[start:start + 8192])[0])
        return np.concatenate(result) if result else np.zeros(0)


def fit(x, observed, sources, prior, hidden=0, steps=600, l2=0.001,
        learning_rate=0.01, seed=20261001, batch_u=2048, batch_p=128,
        row_weights=None):
    """Equal source risk; caller gives inverse pool-size weights for equal-query U.

    Normalization X must already be fitted on TRAIN only. P indices are observed
    rows; U indices include every row, including P. Source risks are averaged,
    so an EM-heavy export cannot dominate merely through its number of rows.
    P sampling inherits the same base row weights, conditional on observation.
    """
    x = np.asarray(x, dtype=np.float64)
    observed = np.asarray(observed, dtype=bool)
    sources = np.asarray(sources)
    if x.ndim != 2 or not len(x) or len(x) != len(observed) or len(x) != len(sources) or not np.isfinite(x).all():
        raise ValueError("Invalid train arrays")
    if row_weights is None:
        row_weights = np.ones(len(x), dtype=np.float64)
    row_weights = np.asarray(row_weights, dtype=np.float64)
    if row_weights.shape != (len(x),) or not np.isfinite(row_weights).all() or (row_weights <= 0).any():
        raise ValueError("Row weights must be finite and positive")
    if steps < 1 or hidden < 0 or l2 < 0 or learning_rate <= 0:
        raise ValueError("Invalid training hyperparameters")
    strata = []
    for source in np.unique(sources):
        marginal = np.flatnonzero(sources == source)
        positive = marginal[observed[marginal]]
        if not len(positive):
            raise ValueError(f"Source {source!r} has no retrieved positive evidence")
        rate = row_weights[positive].sum() / row_weights[marginal].sum()
        if prior < rate:
            raise ValueError(f"Prior {prior} below observed rate {rate} in {source!r}")
        cp = np.cumsum(row_weights[positive])
        cu = np.cumsum(row_weights[marginal])
        cp /= cp[-1]
        cu /= cu[-1]
        strata.append((positive, marginal, cp, cu))
    model = Model(x.shape[1], hidden=hidden, seed=seed, prior=prior)
    rng = np.random.default_rng(seed)
    m = {k: np.zeros_like(v) for k, v in model.parameters.items()}
    v = {k: np.zeros_like(p) for k, p in model.parameters.items()}
    clipped = 0
    history = []
    for step in range(1, steps + 1):
        gradients = {k: np.zeros_like(v) for k, v in model.parameters.items()}
        total = 0.0
        for positive, marginal, cp, cu in strata:
            pp = x[positive[np.searchsorted(cp, rng.random(batch_p), side="right")]]
            uu = x[marginal[np.searchsorted(cu, rng.random(batch_u), side="right")]]
            logits_p, hidden_p = model.forward(pp)
            logits_u, hidden_u = model.forward(uu)
            loss, dp, du, negative = risk_and_grad(logits_p, logits_u, prior)
            clipped += negative <= 0
            gp = model.backward(pp, hidden_p, dp)
            gu = model.backward(uu, hidden_u, du)
            for k in gradients:
                gradients[k] += (gp[k] + gu[k]) / len(strata)
            total += loss / len(strata)
        for k, parameter in model.parameters.items():
            if k.startswith("w"):
                gradients[k] += l2 * parameter
            gradient = gradients[k]
            m[k] = 0.9 * m[k] + 0.1 * gradient
            v[k] = 0.999 * v[k] + 0.001 * gradient * gradient
            parameter -= learning_rate * (m[k] / (1 - 0.9 ** step)) / (
                np.sqrt(v[k] / (1 - 0.999 ** step)) + 1e-8)
        if step % 100 == 0 or step == steps:
            history.append({"step": step, "risk_batch": total})
    return model, {"steps": steps, "source_count": len(strata),
                   "clipped_negative_risk_fraction": clipped / (steps * len(strata)),
                   "training_curve": history, "U_includes_observed_P": True, "equal_source_risk": True,
                   "sampler": "conditional positive and marginal distribution share inverse-pool-size base row weights",
                   "risk": "pi*E_P[softplus(-g)] + max(0, E_U[softplus(g)] - pi*E_P[softplus(g)])"}
