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
import sys

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(__file__))
from cusum import cusum_upper, demo_latency_series  # noqa: E402

HERE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(HERE, "..", "data"))
OUT = os.path.join(HERE, "data")
NIM = 0.01
os.makedirs(OUT, exist_ok=True)


def _marts():
    con = duckdb.connect(os.path.join(DATA, "warehouse.duckdb"), read_only=True)
    funnel = con.execute("select * from fct_funnel order by stage_order").df()
    cohorts = con.execute("select * from fct_latency_cohorts order by latency_band").df()
    cost = con.execute("select * from fct_llm_cost order by model_version").df()
    con.close()
    funnel.to_csv(f"{OUT}/funnel.csv", index=False)
    cohorts.to_csv(f"{OUT}/latency_cohorts.csv", index=False)
    cost.to_csv(f"{OUT}/llm_cost.csv", index=False)
    print(f"  marts: funnel({len(funnel)}), cohorts({len(cohorts)}), cost({len(cost)})")


def _experiment():
    df = pd.read_parquet(f"{DATA}/experiment.parquet")
    cells = (df.groupby(["progress_bar", "fallback"])["completed"].agg(["size", "mean"])
               .reset_index().rename(columns={"size": "n", "mean": "completion"}))
    p0 = float(cells[(cells.progress_bar == 0) & (cells.fallback == 0)]["completion"].iloc[0])
    rows = []
    for _, r in cells.iterrows():
        rows.append({"progress_bar": int(r.progress_bar), "fallback": int(r.fallback),
                     "completion": round(float(r.completion), 4),
                     "lift_pp": round(100 * (float(r.completion) - p0), 2)})
    m = smf.logit("completed ~ progress_bar * fallback", data=df).fit(disp=0)
    # guardrail: default among funded, fallback on vs off
    fb1 = df[(df.fallback == 1) & (df.funded == 1)]["defaulted"]
    fb0 = df[(df.fallback == 0) & (df.funded == 1)]["defaulted"]
    d1, d0 = fb1.mean(), fb0.mean()
    diff = d1 - d0
    se = np.sqrt(d1 * (1 - d1) / len(fb1) + d0 * (1 - d0) / len(fb0))
    ub = diff + norm.ppf(0.95) * se
    summary = {
        "cells": rows,
        "interaction_coef": round(float(m.params["progress_bar:fallback"]), 4),
        "interaction_p": float(m.pvalues["progress_bar:fallback"]),
        "guardrail": {
            "default_fallback": round(float(d1), 4), "default_control": round(float(d0), 4),
            "diff_pp": round(100 * float(diff), 2), "upper_bound_pp": round(100 * float(ub), 2),
            "nim_pp": round(100 * NIM, 2), "non_inferior": bool(ub < NIM),
        },
    }
    summary["ship"] = bool(any(r["fallback"] and r["progress_bar"] and r["lift_pp"] > 0 for r in rows)
                           and summary["guardrail"]["non_inferior"])
    with open(f"{OUT}/experiment_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  experiment: ship={summary['ship']}, guardrail non-inferior={summary['guardrail']['non_inferior']}")


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
    print(f"  cusum: change@{change_day}, alarm@{alarm}, delay={alarm - change_day if alarm else 'none'}")


def main():
    print("building dashboard snapshots ->", OUT)
    _marts(); _experiment(); _causal(); _cusum()
    print("done.")


if __name__ == "__main__":
    main()
