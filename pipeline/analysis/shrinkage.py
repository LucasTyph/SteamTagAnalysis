"""Empirical-Bayes game scores.

Each game's positive-review rate is modeled as p ~ Beta(alpha, beta), with
n_pos ~ Binomial(n, p). Fitting alpha and beta across all games (maximum
likelihood on the beta-binomial) gives a prior. A game's score is its posterior
mean, (n_pos + alpha) / (n + alpha + beta): small games move toward the global
mean, while big games keep their own rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize, special


@dataclass(frozen=True)
class BetaPrior:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        """Prior weight in 'pseudo-reviews'."""
        return self.alpha + self.beta


def _neg_loglik(log_ab: np.ndarray, k: np.ndarray, n: np.ndarray) -> float:
    a, b = np.exp(log_ab)
    # log BetaBinom(k | n, a, b) without the binomial coefficient (constant in a, b)
    ll = special.betaln(k + a, n - k + b) - special.betaln(a, b)
    return -float(ll.sum())


def fit_prior(n_pos: np.ndarray, n: np.ndarray) -> BetaPrior:
    k = np.asarray(n_pos, dtype=float)
    n = np.asarray(n, dtype=float)
    mask = n > 0
    k, n = k[mask], n[mask]
    # Method-of-moments starting point
    p = k / n
    m, v = p.mean(), max(p.var(), 1e-6)
    s0 = max(m * (1 - m) / v - 1, 1.0)
    x0 = np.log([m * s0, (1 - m) * s0])
    res = optimize.minimize(_neg_loglik, x0, args=(k, n), method="L-BFGS-B")
    a, b = np.exp(res.x)
    return BetaPrior(alpha=float(a), beta=float(b))


def posterior_mean(n_pos: np.ndarray, n: np.ndarray, prior: BetaPrior) -> np.ndarray:
    return (np.asarray(n_pos, float) + prior.alpha) / (np.asarray(n, float) + prior.strength)
