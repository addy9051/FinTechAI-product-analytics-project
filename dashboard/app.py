"""
LoanLens — Streamlit dashboard (Phase 4, the clickable recruiter-facing deliverable).

Reads small COMMITTED snapshots from dashboard/data/ (built by build_snapshots.py), so
the deployed app needs no DuckDB / dbt / Ollama. Tells the whole story top to bottom:
diagnose the 32% drop -> cost economics -> the 2x2 fix + guardrail -> production monitoring.

Run locally:   uv run streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")

ACCENT = "#6366f1"
GOOD = "#15803d"
BAD = "#dc2626"
BANDS = ["#22c55e", "#eab308", "#f97316", "#dc2626"]  # latency bands: green -> red

st.set_page_config(page_title="LoanLens", page_icon="🔍", layout="wide")


@st.cache_data
def load():
    csv = lambda n: pd.read_csv(os.path.join(DATA, n))
    js = lambda n: json.load(open(os.path.join(DATA, n)))
    return (csv("funnel.csv"), csv("latency_cohorts.csv"), csv("llm_cost.csv"),
            js("experiment_summary.json"), js("causal_summary.json"),
            csv("cusum_series.csv"), js("cusum_meta.json"))


if not os.path.exists(os.path.join(DATA, "funnel.csv")):
    st.error("Snapshots missing. Run:  uv run python dashboard/build_snapshots.py")
    st.stop()

funnel, cohorts, cost, exp, causal, cusum, cmeta = load()

# ---------------------------------------------------------------- header -----
st.title("🔍 LoanLens")
st.markdown(
    "**Diagnosing & fixing a 32% AI-analysis drop-off in an LLM micro-loan funnel.** "
    "An LLM bank-statement step loses a third of users — this shows it's *latency-driven*, "
    "fixes it with a latency-fallback router, and validates the fix with a 2×2 experiment "
    "that protects loan-default rate as a non-inferiority guardrail."
)

init = int(funnel.loc[funnel.stage == "ai_analysis_initiated", "users"].iloc[0])
comp = int(funnel.loc[funnel.stage == "ai_analysis_completed", "users"].iloc[0])
drop = 1 - comp / init
cpc_primary = float(cost.loc[cost.model_version == "primary", "cost_per_converted_user"].iloc[0])
cpc_fast = float(cost.loc[cost.model_version == "fast", "cost_per_converted_user"].iloc[0])

k1, k2, k3, k4 = st.columns(4)
k1.metric("AI-analysis drop-off", f"{drop:.1%}", help="initiated → completed")
k2.metric("Cost / converted user", f"${cpc_primary:.4f}", f"-{(1-cpc_fast/cpc_primary):.0%} on fast model",
          delta_color="inverse")
k3.metric("Best fix completion lift", f"+{max(c['lift_pp'] for c in exp['cells']):.1f}pp", "both fixes")
k4.metric("Ship decision", "SHIP ✅" if exp["ship"] else "HOLD ⛔",
          "guardrail non-inferior" if exp["guardrail"]["non_inferior"] else "guardrail breach")

st.divider()

# ---------------------------------------------------------------- funnel -----
left, right = st.columns([3, 2])
with left:
    st.subheader("The funnel")
    fig = go.Figure(go.Funnel(y=funnel.stage, x=funnel.users, textinfo="value+percent initial",
                              marker={"color": ACCENT}))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
with right:
    st.subheader("The diagnosis: latency drives it")
    fig = go.Figure(go.Bar(x=cohorts.latency_band, y=cohorts.completion_rate_pct,
                           marker_color=BANDS, text=cohorts.completion_rate_pct, textposition="outside"))
    fig.update_layout(height=360, yaxis_title="completion %", yaxis_range=[0, 100],
                      margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("Completion craters as LLM latency rises — the case for the fallback router.")

st.divider()

# ------------------------------------------------------------ cost + fix -----
c1, c2 = st.columns(2)
with c1:
    st.subheader("LLM cost per converted user")
    cc = cost[cost.model_version != "ALL"]
    fig = go.Figure(go.Bar(x=cc.model_version, y=cc.cost_per_converted_user,
                           marker_color=[ACCENT, GOOD], text=[f"${v:.4f}" for v in cc.cost_per_converted_user],
                           textposition="outside"))
    fig.update_layout(height=320, yaxis_title="$ / converted user", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption(f"The fast fallback model is ~{cpc_primary/cpc_fast:.1f}× cheaper per conversion — "
               "the router cuts cost **and** lifts completion.")
with c2:
    st.subheader("The fix: 2×2 experiment")
    names = {(0, 0): "control", (1, 0): "progress bar", (0, 1): "fallback", (1, 1): "both"}
    cells = sorted(exp["cells"], key=lambda c: (c["progress_bar"], c["fallback"]))
    labels = [names[(c["progress_bar"], c["fallback"])] for c in cells]
    vals = [100 * c["completion"] for c in cells]
    colors = ["#94a3b8", "#818cf8", "#6366f1", GOOD]
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=colors,
                           text=[f"{v:.1f}%" for v in vals], textposition="outside"))
    fig.update_layout(height=320, yaxis_title="completion %", yaxis_range=[0, 90],
                      margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    g = exp["guardrail"]
    st.caption(f"Interaction {exp['interaction_coef']:+.3f} (sub-additive). Guardrail: default "
               f"+{g['diff_pp']}pp, 95% UB **+{g['upper_bound_pp']}pp < {g['nim_pp']}pp NIM** → non-inferior.")

st.divider()

# ----------------------------------------------------- production monitor -----
st.subheader("Production monitoring: CUSUM latency-drift detector")
m1, m2 = st.columns([3, 1])
with m1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cusum.day, y=cusum.latency_s, name="daily latency (s)",
                             line=dict(color=ACCENT)))
    fig.add_vline(x=cmeta["change_day"], line=dict(color="#f97316", dash="dot"),
                  annotation_text="true regime shift")
    if cmeta["alarm_day"]:
        fig.add_vline(x=cmeta["alarm_day"], line=dict(color=BAD),
                      annotation_text="CUSUM alarm")
    fig.update_layout(height=300, yaxis_title="latency (s)", xaxis_title="day",
                      margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
with m2:
    st.metric("Detection delay", f"{cmeta['detection_delay']} days",
              help="days from the injected latency regression to the CUSUM alarm")
    st.caption("Quickest-detection monitoring of latency/default drift — the kind of "
               "production guardrail that catches a model regression before it tanks the funnel.")

st.divider()

# ------------------------------------------------------- causal + footer -----
f1, f2 = st.columns(2)
with f1:
    st.subheader("Honest causal estimate")
    st.markdown(
        f"Naive `completion ~ latency` understates the harm. Adjusting for the confounder "
        f"`requested_amount` (back-door) moves the latency coefficient "
        f"**{causal['naive']} → {causal['adjusted']}** ({causal['shift_pct']:+.0f}% stronger) — "
        "high-latency requests come from more-committed applicants who push through."
    )
with f2:
    st.subheader("Built on a $0 / local stack")
    st.markdown(
        "DuckDB · dbt · LiteLLM → **local Ollama** · Langfuse · statsmodels · Streamlit. "
        "Enterprise analogs (Snowflake · MSK · Statsig · Superset) are documented as ADRs, "
        "not built — the architecture story without the cloud bill."
    )
st.caption("Synthetic data; portfolio pilot. Code & ADRs in the repo.")
