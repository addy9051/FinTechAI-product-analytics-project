"""
Build small, COMMITTED snapshots for the Streamlit dashboard so the deployed app needs
no DuckDB / dbt / Ollama at runtime (Streamlit Cloud just reads these files).

Reads the local warehouse + experiment data, computes the summary stats, and writes
dashboard/data/*.{csv,json}. Re-run after regenerating data:

    uv run python dashboard/build_snapshots.py
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import chisquare, norm

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dashboard.cusum import cusum_upper, demo_latency_series

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.join(HERE, "data")
NIM = 0.01
FAIR_NIM = 0.02   # the fallback router may widen the prime-subprime completion gap by at most 2pp
ALPHA = 0.05
os.makedirs(OUT, exist_ok=True)

# Track row counts for meta
_row_counts: dict[str, int] = {}


def _marts():
    con = duckdb.connect(os.path.join(DATA, "warehouse.duckdb"), read_only=True)
    funnel = con.execute("select * from fct_funnel order by stage_order").df()
    cohorts = con.execute("select * from fct_latency_cohorts order by latency_band").df()
    cost = con.execute("select * from fct_llm_cost order by model_version").df()
    con.close()
    funnel.to_csv(f"{OUT}/funnel.csv", index=False)
    cohorts.to_csv(f"{OUT}/latency_cohorts.csv", index=False)
    cost.to_csv(f"{OUT}/llm_cost.csv", index=False)
    _row_counts["funnel"] = len(funnel)
    _row_counts["latency_cohorts"] = len(cohorts)
    _row_counts["llm_cost"] = len(cost)
    print(f"  marts: funnel({len(funnel)}), cohorts({len(cohorts)}), cost({len(cost)})")


def _experiment():
    df = pd.read_parquet(f"{DATA}/experiment.parquet")
    _row_counts["experiment"] = len(df)

    cells = (df.groupby(["progress_bar", "fallback"])["completed"].agg(["size", "mean"])
               .reset_index().rename(columns={"size": "n", "mean": "completion"}))
    p0 = float(cells[(cells.progress_bar == 0) & (cells.fallback == 0)]["completion"].iloc[0])
    n0 = int(cells[(cells.progress_bar == 0) & (cells.fallback == 0)]["n"].iloc[0])

    rows = []
    pvals = {}
    for _, r in cells.iterrows():
        p1 = float(r.completion)
        n1 = int(r.n)
        # Confidence interval for completion rate (Wilson score interval)
        z = norm.ppf(1 - ALPHA / 2)
        denom = 1 + z**2 / n1
        centre = (p1 + z**2 / (2 * n1)) / denom
        spread = z * np.sqrt((p1 * (1 - p1) + z**2 / (4 * n1)) / n1) / denom
        ci_lo = round(float(centre - spread), 4)
        ci_hi = round(float(centre + spread), 4)

        # Two-proportion z-test vs control (skip for control itself)
        cell_key = (int(r.progress_bar), int(r.fallback))
        if cell_key == (0, 0):
            p_value = None
        else:
            # z-test for difference in proportions
            p_pool = (p1 * n1 + p0 * n0) / (n1 + n0)
            se = np.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n0))
            z_stat = (p1 - p0) / se if se > 0 else 0
            p_value = round(float(2 * (1 - norm.cdf(abs(z_stat)))), 6)
            name = {(1, 0): "progress-bar", (0, 1): "fallback", (1, 1): "both"}[cell_key]
            pvals[name] = p_value

        rows.append({
            "progress_bar": int(r.progress_bar),
            "fallback": int(r.fallback),
            "completion": round(p1, 4),
            "lift_pp": round(100 * (p1 - p0), 2),
            "n": n1,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "p_value": p_value,
        })

    m = smf.logit("completed ~ progress_bar * fallback", data=df).fit(disp=0)

    # Guardrail: default among funded, fallback on vs off
    fb1 = df[(df.fallback == 1) & (df.funded == 1)]["defaulted"]
    fb0 = df[(df.fallback == 0) & (df.funded == 1)]["defaulted"]
    d1, d0 = fb1.mean(), fb0.mean()
    diff = d1 - d0
    se = np.sqrt(d1 * (1 - d1) / len(fb1) + d0 * (1 - d0) / len(fb0))
    ub = diff + norm.ppf(0.95) * se

    # SRM check (chi-square on cell counts)
    srm_counts = df.groupby(["progress_bar", "fallback"]).size().to_numpy()
    srm_chi, srm_p = chisquare(srm_counts)

    # Power analysis (fallback vs control)
    from statsmodels.stats.power import NormalIndPower
    from statsmodels.stats.proportion import proportion_effectsize
    ctrl_rate = float(cells[(cells.progress_bar == 0) & (cells.fallback == 0)]["completion"].iloc[0])
    fb_rate = float(cells[(cells.progress_bar == 0) & (cells.fallback == 1)]["completion"].iloc[0])
    es = proportion_effectsize(fb_rate, ctrl_rate)
    achieved_power = NormalIndPower().power(es, nobs1=n0, alpha=ALPHA, ratio=1.0, alternative="two-sided")
    mde_es = NormalIndPower().solve_power(None, nobs1=n0, alpha=ALPHA, power=0.80, ratio=1.0)

    summary = {
        "cells": rows,
        "interaction_coef": round(float(m.params["progress_bar:fallback"]), 4),
        "interaction_p": float(m.pvalues["progress_bar:fallback"]),
        "guardrail": {
            "default_fallback": round(float(d1), 4), "default_control": round(float(d0), 4),
            "diff_pp": round(100 * float(diff), 2), "upper_bound_pp": round(100 * float(ub), 2),
            "nim_pp": round(100 * NIM, 2), "non_inferior": bool(ub < NIM),
        },
        "srm": {
            "cell_counts": srm_counts.tolist(),
            "chi2": round(float(srm_chi), 2),
            "p_value": round(float(srm_p), 4),
            "pass": bool(srm_p >= ALPHA),
        },
        "power": {
            "achieved_power": round(float(achieved_power), 3),
            "mde_effect_size_h": round(float(mde_es), 4),
            "n_per_arm": n0,
        },
        "p_values": pvals,
    }
    summary["ship"] = bool(any(r["fallback"] and r["progress_bar"] and r["lift_pp"] > 0 for r in rows)
                           and summary["guardrail"]["non_inferior"])
    with open(f"{OUT}/experiment_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  experiment: ship={summary['ship']}, guardrail non-inferior={summary['guardrail']['non_inferior']}")
    print(f"  srm: chi2={srm_chi:.1f} p={srm_p:.3f} -> {'pass' if srm_p >= ALPHA else 'FAIL'}")
    print(f"  power: achieved={achieved_power:.3f}, MDE(h)={mde_es:.4f}")


def _causal():
    tr = pd.read_parquet(f"{DATA}/llm_traces.parquet")
    us = pd.read_parquet(f"{DATA}/users.parquet")
    ev = pd.read_parquet(f"{DATA}/funnel_events.parquet")
    comp = set(ev.loc[ev.event_name == "ai_analysis_completed", "user_id"])
    df = tr.merge(us[["user_id", "requested_amount"]], on="user_id")
    df["completed"] = df.user_id.isin(comp).astype(int)
    bn = smf.logit("completed ~ latency_s", data=df).fit(disp=0).params["latency_s"]
    ba = smf.logit("completed ~ latency_s + requested_amount", data=df).fit(disp=0).params["latency_s"]
    with open(f"{OUT}/causal_summary.json", "w") as f:
        json.dump({"naive": round(float(bn), 4), "adjusted": round(float(ba), 4),
                   "shift_pct": round(100 * (ba - bn) / bn, 1)}, f, indent=2)
    print(f"  causal: naive {bn:.4f} -> adjusted {ba:.4f}")


def _cusum():
    change_day, mu0, sigma = 80, 5.9, 0.30
    x = demo_latency_series(change_day=change_day, mu_before=mu0, sigma_day=sigma)
    S, h, alarm = cusum_upper(x, mu0=mu0, sigma=sigma)
    pd.DataFrame({"day": np.arange(len(x)), "latency_s": np.round(x, 3),
                  "cusum": np.round(S, 3)}).to_csv(f"{OUT}/cusum_series.csv", index=False)
    with open(f"{OUT}/cusum_meta.json", "w") as f:
        json.dump({"change_day": change_day, "alarm_day": int(alarm) if alarm else None,
                   "detection_delay": int(alarm - change_day) if alarm else None,
                   "threshold_h": round(float(h), 3), "mu0": mu0}, f, indent=2)
    _row_counts["cusum_series"] = len(x)
    print(f"  cusum: change@{change_day}, alarm@{alarm}, delay={alarm - change_day if alarm else 'none'}")


def _fairness():
    """Fairness guardrail: does the fallback ROUTER benefit subprime applicants as much as
    prime ones? Uses the randomized 2x2 (progress_bar=0 cells isolate the fallback effect,
    no UX confound) and a one-sided NON-INFERIORITY test on the difference-in-differences —
    the completion gap the router opens between prime and subprime. Parallel to the
    default-rate guardrail; this version can actually FAIL (an injected disparity exists)."""
    df = pd.read_parquet(f"{DATA}/experiment.parquet")
    if "subgroup" not in df.columns:
        print("  fairness: SKIP (experiment.parquet has no subgroup — re-run simulate_experiment.py)")
        return
    sub = df[df.progress_bar == 0]

    def rate(group, fb):
        s = sub[(sub.subgroup == group) & (sub.fallback == fb)]["completed"]
        return float(s.mean()), int(len(s))

    p_pc, n_pc = rate("Prime", 0); p_pf, n_pf = rate("Prime", 1)
    p_sc, n_sc = rate("Subprime", 0); p_sf, n_sf = rate("Subprime", 1)
    lift_prime, lift_sub = p_pf - p_pc, p_sf - p_sc
    dgap = lift_prime - lift_sub  # how much MORE the router helps prime than subprime
    se = np.sqrt(p_pc * (1 - p_pc) / n_pc + p_pf * (1 - p_pf) / n_pf
                 + p_sc * (1 - p_sc) / n_sc + p_sf * (1 - p_sf) / n_sf)
    ub = dgap + norm.ppf(0.95) * se

    res = {
        "prime": {"control": round(p_pc, 4), "fallback": round(p_pf, 4),
                  "lift_pp": round(100 * lift_prime, 2), "n": n_pc + n_pf},
        "subprime": {"control": round(p_sc, 4), "fallback": round(p_sf, 4),
                     "lift_pp": round(100 * lift_sub, 2), "n": n_sc + n_sf},
        "disparity_pp": round(100 * dgap, 2),
        "upper_bound_pp": round(100 * ub, 2),
        "nim_pp": round(100 * FAIR_NIM, 2),
        "non_inferior": bool(ub < FAIR_NIM),
    }
    with open(f"{OUT}/fairness_summary.json", "w") as f:
        json.dump(res, f, indent=2)
    print(f"  fairness: router widens prime-subprime gap {100*dgap:+.2f}pp, 95% UB {100*ub:.2f}pp "
          f"vs NIM {100*FAIR_NIM:.1f}pp -> {'non-inferior' if ub < FAIR_NIM else 'BREACH'}")


def _build_meta():
    """Write build metadata: timestamp and row counts."""
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": _row_counts,
    }
    with open(f"{OUT}/build_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  meta: built_at={meta['built_at']}")


def main():
    print("building dashboard snapshots ->", OUT)
    _marts(); _experiment(); _causal(); _cusum(); _fairness(); _build_meta()
    print("done.")


if __name__ == "__main__":
    main()
