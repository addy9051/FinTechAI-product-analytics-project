"""
CUSUM changepoint monitor (Phase 4 differentiator — the LLM-ops 'production monitoring'
story that's rarer in portfolios than another A/B test).

A one-sided upper CUSUM detects an UPWARD mean shift quickly. It's tuned by the classic
speed-vs-false-alarm tradeoff: `k` (allowance ~ half the shift to detect) and `h` (the
decision interval, which sets the Average Run Length to false alarm). Honest on synthetic
data: we inject a real latency regime-shift and show the detector catches it, reporting
the detection delay.
"""
from __future__ import annotations

import numpy as np


def cusum_upper(x, mu0: float, sigma: float, k_sigma: float = 0.5, h_sigma: float = 5.0):
    """One-sided upper CUSUM for an upward mean shift.

    S_t = max(0, S_{t-1} + (x_t - mu0 - k)),  alarm when S_t > h.
    Returns (S, h, alarm_index). alarm_index is None if no alarm.
    """
    x = np.asarray(x, dtype=float)
    k = k_sigma * sigma
    h = h_sigma * sigma
    S = np.zeros(len(x))
    alarm = None
    for t in range(1, len(x)):
        S[t] = max(0.0, S[t - 1] + (x[t] - mu0 - k))
        if alarm is None and S[t] > h:
            alarm = t
    return S, h, alarm


def demo_latency_series(n_days: int = 120, change_day: int = 80, mu_before: float = 5.9,
                        mu_after: float = 7.5, sigma_day: float = 0.30, seed: int = 11):
    """Simulated DAILY mean-latency series with an injected upward regime shift at
    `change_day` (a 'model degradation' incident) — so the monitor has a real change to
    catch. Returns the series; the true changepoint is `change_day`."""
    rng = np.random.default_rng(seed)
    mu = np.where(np.arange(n_days) < change_day, mu_before, mu_after)
    return mu + rng.normal(0, sigma_day, n_days)
