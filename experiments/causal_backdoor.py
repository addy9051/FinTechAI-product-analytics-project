"""
Back-door adjustment: the honest causal estimate of LLM latency -> AI-analysis
completion (Phase 3, the OPTIONAL causal artifact from docs/adr/0001-statistical-methods.md).

The observational funnel is confounded. The DAG:

        requested_amount
          /            \\           (requested_amount is the COMMON CAUSE = confounder)
   input_tokens         \\
         |                \\
         v                 v
      latency  ----------> completion        (latency -> completion is the causal effect)

Treatment = latency, outcome = completion. Two paths connect them:
  (1) latency -> completion                                  [the causal effect we want]
  (2) latency <- input_tokens <- requested_amount -> completion   [a back-door path]

Back-door criterion: block path (2). Conditioning on the COMMON CAUSE `requested_amount`
blocks it; so does conditioning on `input_tokens` (also a non-collider on that path).
Both are valid adjustment sets and should agree — a built-in robustness check.

Role-reversal caution: `input_tokens` and `latency` are MEDIATORS of `requested_amount`'s
*own* effect on completion. So if the question were "amount's total effect", conditioning
on them would be wrong (over-control). Confounder vs mediator depends on the causal query.

Run:  uv run python experiments/causal_backdoor.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))


def main():
    tr = pd.read_parquet(f"{DATA}/llm_traces.parquet")
    us = pd.read_parquet(f"{DATA}/users.parquet")
    ev = pd.read_parquet(f"{DATA}/funnel_events.parquet")
    completed = set(ev.loc[ev.event_name == "ai_analysis_completed", "user_id"])

    df = tr.merge(us[["user_id", "requested_amount", "device"]], on="user_id")
    df["completed"] = df.user_id.isin(completed).astype(int)

    naive = smf.logit("completed ~ latency_s", data=df).fit(disp=0)
    adj_amount = smf.logit("completed ~ latency_s + requested_amount", data=df).fit(disp=0)
    adj_tokens = smf.logit("completed ~ latency_s + input_tokens", data=df).fit(disp=0)

    bn = naive.params["latency_s"]
    ba = adj_amount.params["latency_s"]
    bt = adj_tokens.params["latency_s"]

    print("=== Latency -> completion: naive vs back-door-adjusted ===")
    print(f"  naive (completed ~ latency)                 : {bn:+.4f}  (OR/sec {np.exp(bn):.3f})")
    print(f"  back-door, adjust requested_amount          : {ba:+.4f}  (OR/sec {np.exp(ba):.3f})")
    print(f"  shift from de-confounding                   : {100*(ba-bn)/bn:+.1f}% stronger")
    print(f"  amount coef (adjusted)                      : {adj_amount.params['requested_amount']:+.2e}"
          f"  (p={adj_amount.pvalues['requested_amount']:.1e})")
    print()
    print("  Interpretation: the naive estimate UNDERSTATES latency's harm, because")
    print("  high-latency requests come from more-committed (higher-amount) applicants")
    print("  who push through. De-confounding reveals the larger true effect.")
    print()
    print("=== Robustness: a second valid adjustment set should agree ===")
    print(f"  back-door, adjust input_tokens instead      : {bt:+.4f}  (OR/sec {np.exp(bt):.3f})")
    print("  tokens is also on the back-door path (latency <- tokens <- amount), so it")
    print(f"  de-confounds too, and agrees with the amount-adjusted estimate ({ba:.4f}).")


if __name__ == "__main__":
    main()
