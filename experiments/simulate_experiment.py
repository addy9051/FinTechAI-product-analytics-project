"""
2x2 factorial experiment simulator (Phase 3).

Randomizes a fresh user population to four cells crossing the two fixes from the
blueprint:
    A = progress bar (UX fix)            B = latency-fallback router (technical fix)

We inject KNOWN ground-truth effects so the analysis can be checked against truth
(a synthetic experiment is only useful if you can verify the test recovers what you
put in):

    completion(A,B) = P0 + a_A*A + a_B*B + a_AB*(A*B)   [subprime: a_B is FAIR_DISPARITY smaller]
    default(B)      = D0 + d_B*B          # fallback's faster/cheaper model nudges default up

We also split each cell into a credit subgroup (prime/subprime) and inject a small FAIRNESS
disparity: the fast fallback model's lower capacity gives subprime applicants a slightly
smaller completion benefit. Control completion stays equal across subgroups (no baseline
bias), so the fairness non-inferiority guardrail tests something REAL — it can fail.

P0 is grounded in the observed baseline completion (~66.6% = 1 - the 33.4% drop).

Outputs (one row per user):
    data/experiment.parquet       - balanced 25/25/25/25 randomization
    data/experiment_srm.parquet   - deliberately imbalanced on factor A (to demo the
                                     Sample-Ratio-Mismatch check firing)

Run:  uv run python experiments/simulate_experiment.py --n-per-arm 50000 --seed 7
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

# --- injected ground truth (the analysis should recover these) ---------------
P0 = 0.666          # baseline AI-analysis completion (observed ~66.6%)
A_PROGRESS = 0.030  # progress-bar main effect on completion (modest UX reassurance)
A_FALLBACK = 0.080  # fallback main effect on completion (larger: it cuts latency)
A_INTERACT = -0.015 # interaction: diminishing returns when both are on
FUNDED_RATE = 0.62  # P(funded | completed), constant across arms (treatments act earlier)
D0 = 0.078          # baseline default rate among funded loans
D_FALLBACK = 0.005  # fallback raises default slightly — the guardrail's reason to exist

# Fairness: an injected credit-subgroup disparity (makes the fairness guardrail falsifiable).
SUBPRIME_SHARE = 0.36   # ~ the data's share of credit_score < 670
FAIR_DISPARITY = 0.006  # subprime's fallback completion lift is 0.6pp smaller than prime's

CELLS = [(0, 0), (1, 0), (0, 1), (1, 1)]  # (progress_bar, fallback)


def _simulate(n_per_arm: int, seed: int, srm: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed + (99 if srm else 0))
    frames = []
    for a, b in CELLS:
        n = int(n_per_arm * 0.80) if (srm and a == 1) else n_per_arm  # break balance on A
        is_sub = rng.random(n) < SUBPRIME_SHARE
        # the fallback model benefits subprime applicants slightly less (injected disparity)
        fb_effect = np.where(is_sub, A_FALLBACK - FAIR_DISPARITY, A_FALLBACK)
        p_complete = P0 + A_PROGRESS * a + fb_effect * b + A_INTERACT * a * b
        completed = rng.random(n) < p_complete
        funded = completed & (rng.random(n) < FUNDED_RATE)
        p_default = D0 + D_FALLBACK * b
        defaulted = funded & (rng.random(n) < p_default)
        frames.append(pd.DataFrame({
            "progress_bar": a,
            "fallback": b,
            "subgroup": np.where(is_sub, "Subprime", "Prime"),
            "completed": completed.astype(int),
            "funded": funded.astype(int),
            "defaulted": defaulted.astype(int),
        }))
    df = pd.concat(frames, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


def main(n_per_arm: int, seed: int, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for srm, name in [(False, "experiment.parquet"), (True, "experiment_srm.parquet")]:
        df = _simulate(n_per_arm, seed, srm)
        df.to_parquet(f"{out_dir}/{name}", index=False)
        cell = (df.groupby(["progress_bar", "fallback"])
                  .agg(users=("completed", "size"), completion=("completed", "mean"))
                  .reset_index())
        print(f"\nwrote {name}: {len(df):,} users")
        print(cell.to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-arm", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    a = ap.parse_args()
    main(a.n_per_arm, a.seed, os.path.abspath(a.out))
