"""
Synthetic data generator for the FinTech micro-loan analytics pilot.

Design goal: make the 32% AI-analysis drop-off REAL in the data by letting LLM
latency causally drive abandonment. Everything downstream (cohorts, the funnel,
the experiment) then analyses a genuine signal rather than a hard-coded number.

Tables produced (written to ../data as parquet):
  users         - one row per signup
  llm_traces    - one row per "AI bank-statement analysis" call (the LLM telemetry)
  funnel_events - long event log: Sign Up -> ... -> Loan Accepted
  loans         - one row per offered loan, incl. matured default outcome (guardrail)

Run:  python synthetic-data/generate.py --users 20000 --seed 42
Upgrade path: swap the funnel/loan tabular draws for SDV (CTGAN/TVAE) once you
want statistically-fitted multivariate data; Faker+numpy is used here for speed
and zero heavy dependencies.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

FUNNEL = [
    "sign_up",
    "bank_link",
    "ai_analysis_initiated",
    "ai_analysis_completed",
    "loan_terms_offered",
    "loan_accepted",
]

# Two model versions so the fallback story has something to compare.
# `fast` is the latency-fallback target; `primary` is slower but a touch sharper.
MODELS = {
    "primary": {"latency_mean_s": 6.5, "latency_sd_s": 3.0, "cost_per_1k_in": 0.0030,
                "cost_per_1k_out": 0.0150, "quality": 0.86},
    "fast":    {"latency_mean_s": 2.2, "latency_sd_s": 0.9, "cost_per_1k_in": 0.0008,
                "cost_per_1k_out": 0.0040, "quality": 0.80},
}


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def abandon_prob(latency_s: np.ndarray) -> np.ndarray:
    """P(user abandons during AI analysis) rising with latency.

    Tuned so the overall initiated->completed drop lands near ~32% given the
    primary model's latency distribution. This is the causal core of the dataset.
    """
    # ~5% baseline impatience, climbing past the 4s threshold; tuned so the
    # latency-weighted average abandonment lands near 32%.
    return np.clip(0.05 + 0.62 * _sigmoid(0.5 * (latency_s - 6.5)), 0.0, 0.95)


def generate(n_users: int, seed: int, out_dir: str) -> None:
    rng = np.random.default_rng(seed)
    fake = Faker()
    Faker.seed(seed)

    start = datetime(2026, 1, 1)
    user_ids = np.arange(1, n_users + 1)
    signup_ts = [start + timedelta(minutes=int(m)) for m in rng.integers(0, 60 * 24 * 120, n_users)]

    # ---- users -----------------------------------------------------------
    users = pd.DataFrame({
        "user_id": user_ids,
        "signup_ts": signup_ts,
        "country": rng.choice(["US", "UK", "DE", "IN", "NG"], n_users, p=[.45, .2, .12, .15, .08]),
        "device": rng.choice(["ios", "android", "web"], n_users, p=[.4, .4, .2]),
        # credit_score drives loan default later. Beta(5,2) gives a realistic
        # left-skewed, FICO-like shape (peak ~740, long tail toward subprime) —
        # a symmetric normal would over-state the share of mid-range scores.
        "credit_score": np.clip((rng.beta(5, 2, n_users) * 550 + 300).round().astype(int), 300, 850),
        "requested_amount": rng.choice([500, 1000, 2000, 3000, 5000], n_users),
    })

    # ---- assign each user a model version (experiment-free baseline world) -
    # Most traffic on primary; this is the pre-fix state we are diagnosing.
    model_choice = rng.choice(["primary", "fast"], n_users, p=[0.85, 0.15])

    # ---- funnel simulation ----------------------------------------------
    events = []
    traces = []
    loans = []

    # stage-by-stage pass rates BEFORE the AI step (independent of latency)
    p_bank_link = 0.82
    p_offer_given_complete = 0.92      # underwriting offer rate
    p_accept_given_offer = 0.74

    for i in range(n_users):
        uid = int(user_ids[i])
        ts = signup_ts[i]
        events.append((uid, "sign_up", ts))

        if rng.random() > p_bank_link:
            continue
        ts += timedelta(seconds=int(rng.integers(20, 300)))
        events.append((uid, "bank_link", ts))

        # AI analysis initiated
        ts += timedelta(seconds=int(rng.integers(5, 60)))
        events.append((uid, "ai_analysis_initiated", ts))

        m = model_choice[i]
        spec = MODELS[m]
        latency_s = float(max(0.3, rng.normal(spec["latency_mean_s"], spec["latency_sd_s"])))
        in_tok = int(rng.integers(1800, 4200))    # bank statement is token-heavy
        out_tok = int(rng.integers(180, 700))
        cached = int(in_tok * rng.uniform(0.0, 0.4))
        cost = ((in_tok - cached) / 1000 * spec["cost_per_1k_in"]
                + cached / 1000 * spec["cost_per_1k_in"] * 0.25
                + out_tok / 1000 * spec["cost_per_1k_out"])
        # confidence: noisy, deliberately imperfectly calibrated (mirrors blueprint)
        confidence = float(np.clip(rng.beta(6, 2) * spec["quality"] + rng.normal(0, 0.05), 0, 1))
        fallback_triggered = latency_s > 4.0 and m == "primary"  # would-have-fired flag

        traces.append((uid, m, round(latency_s, 3), in_tok, out_tok, cached,
                       round(cost, 6), round(confidence, 4), fallback_triggered, ts))

        # ABANDON during analysis as a function of latency (the 32% drop)
        if rng.random() < abandon_prob(np.array([latency_s]))[0]:
            continue
        ts += timedelta(seconds=int(latency_s))
        events.append((uid, "ai_analysis_completed", ts))

        # offer
        if rng.random() > p_offer_given_complete or confidence < 0.45:
            # low-confidence -> abstain / route to human -> no auto-offer
            continue
        ts += timedelta(seconds=int(rng.integers(2, 20)))
        events.append((uid, "loan_terms_offered", ts))

        # default risk: lower credit score + higher amount -> higher default.
        # Reference score 690 ≈ the realistic Beta(5,2) mean, so the intercept
        # reads as "baseline default for a median-credit applicant"; intercept
        # tuned to hold the base default rate near the documented ~7.8%.
        score = users.loc[i, "credit_score"]
        amount = users.loc[i, "requested_amount"]
        default_logit = -3.35 - 0.012 * (score - 690) + 0.00018 * amount
        default_prob = float(_sigmoid(np.array([default_logit]))[0])

        accepted = rng.random() < p_accept_given_offer
        if accepted:
            ts += timedelta(seconds=int(rng.integers(5, 120)))
            events.append((uid, "loan_accepted", ts))
            defaulted = rng.random() < default_prob
            loans.append((uid, amount, int(score), round(default_prob, 4), defaulted, ts))

    # ---- frames ----------------------------------------------------------
    events_df = pd.DataFrame(events, columns=["user_id", "event_name", "event_ts"])
    traces_df = pd.DataFrame(traces, columns=[
        "user_id", "model_version", "latency_s", "input_tokens", "output_tokens",
        "cached_tokens", "cost_usd", "confidence_score", "fallback_triggered", "event_ts"])
    loans_df = pd.DataFrame(loans, columns=[
        "user_id", "amount", "credit_score", "default_prob", "defaulted", "accepted_ts"])

    os.makedirs(out_dir, exist_ok=True)
    users.to_parquet(f"{out_dir}/users.parquet", index=False)
    events_df.to_parquet(f"{out_dir}/funnel_events.parquet", index=False)
    traces_df.to_parquet(f"{out_dir}/llm_traces.parquet", index=False)
    loans_df.to_parquet(f"{out_dir}/loans.parquet", index=False)

    # ---- quick sanity print ---------------------------------------------
    stage_counts = events_df.groupby("event_name")["user_id"].nunique().reindex(FUNNEL)
    init = stage_counts["ai_analysis_initiated"]
    comp = stage_counts["ai_analysis_completed"]
    drop = 1 - comp / init
    print("\n=== Funnel (unique users per stage) ===")
    for s in FUNNEL:
        print(f"  {s:24s} {int(stage_counts[s]):>7,}")
    print(f"\nAI-analysis drop-off (initiated->completed): {drop:.1%}  (target ~32%)")
    print(f"LLM traces: {len(traces_df):,} | loans accepted: {len(loans_df):,} | "
          f"default rate: {loans_df['defaulted'].mean():.2%}")
    print(f"Wrote parquet to {out_dir}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    a = ap.parse_args()
    generate(a.users, a.seed, os.path.abspath(a.out))
