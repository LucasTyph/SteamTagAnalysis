"""Leave-mix-out baselines: compare each tag mix with a model fitted without its games.

With one shared baseline, a mix's own games help fit the tag coefficients, so part
of a real interaction is absorbed into the tags' coefficients and the mix's mean
residual understates it. Refitting the ridge model without each mix's games removes
that, and for ridge it has a closed form (no refit needed). For the held-out rows S:

    r_held = (I - H_SS)^-1 r_S,   H_SS = X_S A^-1 X_S',   A = X'X + diag(penalty)

which for large S is cheaper as r_S + X_S (A - X_S'X_S)^-1 X_S' r_S (same thing,
by the Woodbury identity). `r` is the logit-scale residual of the full fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse, special

# Mixes up to this many games use the m x m form; bigger ones the p x p form.
SMALL_MIX = 400


@dataclass
class Baseline:
    """Ridge fit with an unpenalized intercept, set up for leave-group-out residuals."""

    X1: sparse.csr_matrix  # [1, X]
    A: np.ndarray  # X1'X1 + diag(penalty)
    A_inv: np.ndarray
    beta: np.ndarray
    y: np.ndarray  # logit-scale target
    score: np.ndarray  # score in [0, 1]

    @classmethod
    def fit(cls, X: sparse.csr_matrix, y: np.ndarray, alpha: float) -> Baseline:
        n = X.shape[0]
        X1 = sparse.hstack([sparse.csr_matrix(np.ones((n, 1))), X], format="csr")
        penalty = np.full(X1.shape[1], float(alpha))
        penalty[0] = 0.0
        A = (X1.T @ X1).toarray() + np.diag(penalty)
        beta = np.linalg.solve(A, X1.T @ y)
        return cls(X1, A, np.linalg.inv(A), beta, y, special.expit(y))

    @property
    def predicted(self) -> np.ndarray:
        """Shared-baseline prediction, score scale."""
        return special.expit(self.X1 @ self.beta)

    def held_out(self, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(predicted, residual) on the score scale for `rows`, from a fit without them."""
        XS = self.X1[rows]
        r = self.y[rows] - XS @ self.beta
        if len(rows) <= SMALL_MIX:
            B = np.asarray(XS @ self.A_inv)  # m x p; A^-1 is symmetric, so H = X_S B'
            H = np.asarray(XS @ B.T)
            r_held = np.linalg.solve(np.eye(len(rows)) - H, r)
        else:
            G = (XS.T @ XS).toarray()
            w = np.linalg.solve(self.A - G, XS.T @ r)
            r_held = r + XS @ w
        pred = special.expit(self.y[rows] - r_held)
        return pred, self.score[rows] - pred


def mix_effects(
    base: Baseline,
    combo_ids: np.ndarray,
    rows: np.ndarray,
    dev: np.ndarray,
    n_combos: int,
) -> dict[str, np.ndarray]:
    """Developer-clustered effect per mix against its leave-mix-out baseline.

    combo_ids/rows: membership pairs (mix index, game row), sorted by mix index.
    dev: developer code per game row. Returns effect, resid_var (across developers)
    and mean_predicted, in percentage points, indexed by mix.
    """
    effect = np.full(n_combos, np.nan)
    resid_var = np.full(n_combos, np.nan)
    mean_pred = np.full(n_combos, np.nan)
    bounds = np.searchsorted(combo_ids, np.arange(n_combos + 1))
    for c in range(n_combos):
        lo, hi = bounds[c], bounds[c + 1]
        if hi <= lo:
            continue
        r = rows[lo:hi]
        pred, resid = base.held_out(r)
        _, inv = np.unique(dev[r], return_inverse=True)
        k = np.bincount(inv)
        dev_resid = np.bincount(inv, resid) / k
        dev_pred = np.bincount(inv, pred) / k
        effect[c] = 100 * dev_resid.mean()
        mean_pred[c] = 100 * dev_pred.mean()
        resid_var[c] = (100**2) * dev_resid.var(ddof=1) if len(k) > 1 else np.nan
    return {"effect": effect, "resid_var": resid_var, "mean_predicted": mean_pred}


def planted_recovery(
    X: sparse.csr_matrix,
    y: np.ndarray,
    alpha: float,
    groups: list[np.ndarray],
    delta: float,
    batch: int = 6,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Plant +`delta` (logit) on a few groups at a time and measure how much of it
    each baseline recovers: (estimated shift in the group's mean residual) / (true
    shift in its mean score). Returns per-group recovery for both baselines."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(groups))
    base0 = Baseline.fit(X, y, alpha)
    shared0 = base0.score - base0.predicted
    out = {"shared": [], "leave_mix_out": []}
    for start in range(0, len(order), batch):
        picked = [groups[i] for i in order[start : start + batch]]
        y2 = y.copy()
        for g in picked:
            y2[g] += delta
        base1 = Baseline.fit(X, y2, alpha)
        shared1 = base1.score - base1.predicted
        for g in picked:
            true = np.mean(base1.score[g] - base0.score[g])
            out["shared"].append((shared1[g].mean() - shared0[g].mean()) / true)
            out["leave_mix_out"].append(
                (base1.held_out(g)[1].mean() - base0.held_out(g)[1].mean()) / true
            )
    return {k: np.array(v) for k, v in out.items()}
