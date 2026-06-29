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
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")

# ── colour palette ────────────────────────────────────────────────────────────
ACCENT = "#818cf8"          # indigo-400
ACCENT_DIM = "#6366f1"      # indigo-500
GOOD = "#34d399"             # emerald-400
BAD = "#f87171"              # red-400
WARN = "#fbbf24"             # amber-400
MUTED = "#94a3b8"            # slate-400
SURFACE = "#1e293b"          # slate-800
CARD_BG = "#0f172a"          # slate-900
TEXT = "#e2e8f0"             # slate-200
BANDS = ["#34d399", "#fbbf24", "#fb923c", "#f87171"]  # latency bands: green -> red

# Plotly layout template for dark mode
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT, family="Inter, system-ui, sans-serif"),
    xaxis=dict(gridcolor="rgba(148,163,184,0.1)", zerolinecolor="rgba(148,163,184,0.1)"),
    yaxis=dict(gridcolor="rgba(148,163,184,0.1)", zerolinecolor="rgba(148,163,184,0.1)"),
    margin=dict(l=10, r=10, t=30, b=10),
    hoverlabel=dict(bgcolor=SURFACE, font_color=TEXT, bordercolor="rgba(0,0,0,0)"),
)

st.set_page_config(page_title="LoanLens", page_icon="🔍", layout="wide")

# ── inject custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* Global font + dark background */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}
[data-testid="stHeader"] {
    background: rgba(15,23,42,0.8);
    backdrop-filter: blur(12px);
}
[data-testid="stSidebar"] {
    background: rgba(15,23,42,0.95);
    border-right: 1px solid rgba(129,140,248,0.15);
}

/* Metric cards — glassmorphism */
[data-testid="stMetric"] {
    background: rgba(30,41,59,0.6);
    border: 1px solid rgba(129,140,248,0.15);
    border-radius: 12px;
    padding: 16px 20px;
    backdrop-filter: blur(8px);
    transition: transform 0.2s ease, border-color 0.2s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    border-color: rgba(129,140,248,0.4);
}
[data-testid="stMetricLabel"] {
    color: #94a3b8 !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    color: #e2e8f0 !important;
    font-weight: 700 !important;
}
[data-testid="stMetricDelta"] {
    font-weight: 500 !important;
}

/* Tab styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: rgba(30,41,59,0.5);
    border-radius: 12px;
    padding: 4px;
    border: 1px solid rgba(129,140,248,0.1);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 10px 20px;
    color: #94a3b8;
    font-weight: 500;
    font-size: 0.9rem;
}
.stTabs [aria-selected="true"] {
    background: rgba(129,140,248,0.2) !important;
    color: #e2e8f0 !important;
    border-bottom-color: transparent !important;
}
.stTabs [data-baseweb="tab-highlight"] {
    background-color: transparent !important;
}
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* Headers */
h1 {
    background: linear-gradient(135deg, #818cf8, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800 !important;
    letter-spacing: -0.02em;
}
h2, h3 {
    color: #e2e8f0 !important;
    font-weight: 600 !important;
}
p, li, span, .stMarkdown {
    color: #cbd5e1;
}

/* Expanders */
[data-testid="stExpander"] {
    background: rgba(30,41,59,0.4);
    border: 1px solid rgba(129,140,248,0.1);
    border-radius: 12px;
}
[data-testid="stExpander"] summary {
    color: #94a3b8 !important;
    font-weight: 500;
}

/* Dividers */
hr {
    border-color: rgba(129,140,248,0.1) !important;
}

/* Captions */
.stCaption, [data-testid="stCaptionContainer"] {
    color: #64748b !important;
}

/* Slider styling */
.stSlider > div > div > div {
    color: #e2e8f0 !important;
}

/* Download buttons */
.stDownloadButton > button {
    background: rgba(129,140,248,0.15) !important;
    border: 1px solid rgba(129,140,248,0.3) !important;
    color: #818cf8 !important;
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s ease;
}
.stDownloadButton > button:hover {
    background: rgba(129,140,248,0.25) !important;
    border-color: rgba(129,140,248,0.5) !important;
    transform: translateY(-1px);
}

/* Success/error banners */
.stAlert {
    border-radius: 12px !important;
}

/* Data freshness banner */
.freshness-banner {
    background: rgba(30,41,59,0.5);
    border: 1px solid rgba(129,140,248,0.1);
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 0.8rem;
    color: #64748b;
    display: flex;
    align-items: center;
    gap: 8px;
}
</style>
""", unsafe_allow_html=True)


# ── data loading ─────────────────────────────────────────────────────────────
@st.cache_data
def load():
    csv = lambda n: pd.read_csv(os.path.join(DATA, n))
    js = lambda n: json.load(open(os.path.join(DATA, n)))
    meta_path = os.path.join(DATA, "build_meta.json")
    meta = js("build_meta.json") if os.path.exists(meta_path) else None
    
    fairness_path = os.path.join(DATA, "fairness_summary.json")
    fairness = js("fairness_summary.json") if os.path.exists(fairness_path) else None
    
    return (csv("funnel.csv"), csv("latency_cohorts.csv"), csv("llm_cost.csv"),
            js("experiment_summary.json"), js("causal_summary.json"),
            csv("cusum_series.csv"), js("cusum_meta.json"), meta, fairness)


if not os.path.exists(os.path.join(DATA, "funnel.csv")):
    st.error("Snapshots missing. Run:  uv run python dashboard/build_snapshots.py")
    st.stop()

funnel, cohorts, cost, exp, causal, cusum, cmeta, build_meta, fairness = load()

# ── precompute headline metrics ──────────────────────────────────────────────
init = int(funnel.loc[funnel.stage == "ai_analysis_initiated", "users"].iloc[0])
comp = int(funnel.loc[funnel.stage == "ai_analysis_completed", "users"].iloc[0])
drop = 1 - comp / init
cpc_primary = float(cost.loc[cost.model_version == "primary", "cost_per_converted_user"].iloc[0])
cpc_fast = float(cost.loc[cost.model_version == "fast", "cost_per_converted_user"].iloc[0])
best_cell = max(exp["cells"], key=lambda c: c["lift_pp"])
best_lift = best_cell["lift_pp"]

# Revenue & unit economics — all $ are LABELED ASSUMPTIONS; the lift is projected from the
# experiment onto the observed funnel. Revenue = MARGIN on incremental FUNDED loans (not
# loan principal, and not every completion is funded).
accepted = int(funnel.loc[funnel.stage == "loan_accepted", "users"].iloc[0])
funded_per_completion = accepted / comp           # ~0.61: completion -> funded conversion
cohort_days = 120                                 # the synthetic cohort spans ~120 days
annual_factor = 365 / cohort_days                 # ~3.04x to annualize (NOT x12)

avg_loan = 2300                                   # ~ mean requested_amount in the data
net_margin_pct = 0.12                             # assumed net margin per funded loan
margin_per_loan = avg_loan * net_margin_pct       # ~$276
cac = 1450                                        # blueprint SMB-fintech CAC benchmark

incremental_completions = best_lift / 100 * init                       # from the best fix
incremental_funded = incremental_completions * funded_per_completion   # propagate to funded
annual_funded = incremental_funded * annual_factor
annual_margin = annual_funded * margin_per_loan   # the revenue (margin), annualized
cost_saving_pct = 1 - cpc_fast / cpc_primary

# ── header ────────────────────────────────────────────────────────────────────
st.title("🔍 LoanLens")
st.markdown(
    "<span style='color:#94a3b8;font-size:1.05rem;'>"
    "Diagnosing & fixing a <b style='color:#f87171;'>32% AI-analysis drop-off</b> "
    "in an LLM micro-loan funnel — latency-driven diagnosis, cost economics, "
    "2×2 experiment validation, and production monitoring.</span>",
    unsafe_allow_html=True,
)

# Data freshness banner
if build_meta:
    built_dt = datetime.fromisoformat(build_meta["built_at"])
    total_rows = sum(build_meta.get("row_counts", {}).values())
    st.markdown(
        f"<div class='freshness-banner'>"
        f"🕐 Data snapshot: <b>{built_dt.strftime('%b %d, %Y %H:%M UTC')}</b>"
        f"&nbsp;&nbsp;|&nbsp;&nbsp;📊 {total_rows:,} rows across "
        f"{len(build_meta.get('row_counts', {}))} datasets"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("")  # spacing

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_exec, tab_funnel, tab_exp, tab_cost, tab_monitor = st.tabs([
    "📊 Executive Summary",
    "🔍 Funnel Diagnosis",
    "🧪 Experiment Results",
    "💰 Cost Economics",
    "🛡️ Production Monitoring",
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 1 — Executive Summary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_exec:
    st.subheader("The problem & the fix at a glance")

    # Row 1: Key metrics
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "AI-Analysis Drop-off",
        f"{drop:.1%}",
        help="Users lost between AI analysis initiated → completed",
    )
    k2.metric(
        "Best Completion Lift",
        f"+{best_lift:.1f}pp",
        "both fixes (progress bar + fallback)",
    )
    k3.metric(
        "Ship Decision",
        "SHIP ✅" if exp["ship"] else "HOLD ⛔",
        "guardrail non-inferior" if exp["guardrail"]["non_inferior"] else "guardrail breach",
    )
    k4.metric(
        "CUSUM Detection",
        f"{cmeta['detection_delay']} day{'s' if cmeta['detection_delay'] != 1 else ''}" if cmeta["detection_delay"] else "No alarm",
        "latency drift → alarm",
    )

    st.markdown("")

    # Row 2: Revenue impact
    st.markdown("#### 💰 Estimated Business Impact")
    st.caption(
        f"Lift projected from the experiment onto the observed funnel. The figures below use labeled "
        f"assumptions: avg loan \\${avg_loan:,}, {net_margin_pct:.0%} net margin (≈\\${margin_per_loan:,.0f}/loan), "
        f"CAC \\${cac:,} (blueprint SMB benchmark)."
    )
    r1, r2, r3, r4 = st.columns(4)
    r1.metric(
        "Incremental Funded Loans / Cohort",
        f"+{incremental_funded:,.0f}",
        help=f"{best_lift:.1f}pp lift × {init:,} initiated × {funded_per_completion:.0%} funded-per-completion",
    )
    r2.metric(
        "Annualized Margin Recovered",
        f"${annual_margin:,.0f}",
        help=f"≈ {annual_funded:,.0f} funded loans/yr × \\${margin_per_loan:,.0f} margin "
             f"(×{annual_factor:.1f} to annualize the {cohort_days}-day cohort) — margin, not principal",
    )
    r3.metric(
        "Model Cost Savings",
        f"−{cost_saving_pct:.0%}",
        f"${cpc_primary:.4f} → ${cpc_fast:.4f}",
        delta_color="inverse",
    )
    r4.metric(
        "LLM Cost vs CAC",
        f"{cpc_primary/cac:.3%} of CAC",
        f"${cpc_primary:.4f} vs ${cac:,} CAC",
        delta_color="off",
        help="Inference cost is a rounding error next to CAC — the conversion uplift, at zero marginal CAC, is the real prize.",
    )

    st.markdown("")

    # Executive narrative
    with st.expander("📋 Executive Narrative", expanded=True):
        st.markdown(f"""
**Problem**: The LLM bank-statement analysis step loses **{drop:.1%}** of users
between initiation and completion. Completion craters from **{cohorts.completion_rate_pct.iloc[0]:.0f}%** (< 3s latency)
to **{cohorts.completion_rate_pct.iloc[-1]:.0f}%** (> 8s) — the drop-off is **latency-driven**.

**Fix**: A 2×2 factorial experiment tested two interventions:
- **Progress bar** (UX): +{[c for c in exp['cells'] if c['progress_bar']==1 and c['fallback']==0][0]['lift_pp']:.1f}pp lift
- **Latency-fallback router** (MLOps): +{[c for c in exp['cells'] if c['progress_bar']==0 and c['fallback']==1][0]['lift_pp']:.1f}pp lift
- **Both combined**: **+{best_lift:.1f}pp** lift (sub-additive interaction: {exp['interaction_coef']:+.3f})

**Safety**: Default rate guardrail passes — the 95% upper bound on default increase
is **+{exp['guardrail']['upper_bound_pp']:.2f}pp**, well below the **{exp['guardrail']['nim_pp']:.1f}pp NIM** threshold.

**Recommendation**: **{"SHIP the combined fix" if exp['ship'] else "HOLD — guardrail breach"}**.
        """)

    # Causal honesty callout
    st.markdown("#### 🔬 Causal Honesty")
    ca1, ca2 = st.columns([3, 1])
    with ca1:
        st.markdown(
            f"Naive `completion ~ latency` **understates** the harm. Adjusting for the confounder "
            f"`requested_amount` (back-door criterion) moves the latency coefficient "
            f"**{causal['naive']} → {causal['adjusted']}** ({causal['shift_pct']:+.0f}% stronger) — "
            "high-latency requests come from more-committed applicants who push through."
        )
    with ca2:
        # Simple DAG
        st.markdown("""
```
requested_amount
    ├──→ input_tokens ──→ latency ──→ completion
    └──→ commitment ─────────────────→ completion
```
        """)

    st.divider()
    
    # Strategy Section
    st.markdown("#### 🚀 Long-Term Strategy & Scalability")
    st.markdown(
        "**The current 4-second latency fallback is a highly effective tactical fix, but as traffic scales 10x, "
        "we must evolve our LLM architecture:**\n\n"
        "1. **Model Fine-Tuning**: Rather than relying on a general-purpose fallback model, we should fine-tune a smaller (1B-3B parameter) model specifically on our historical underwriting data to eliminate the capability gap.\n"
        "2. **Provisioned Throughput**: If the primary model's latency variance remains high, we must evaluate purchasing provisioned throughput (e.g., AWS Bedrock PT or Azure PT) to guarantee sub-3s P99 latency on the primary model.\n"
        "3. **Fairness Audits**: We will implement quarterly demographic parity audits to ensure the fallback model does not develop biased heuristics against vulnerable populations."
    )
    
    st.divider()

    st.markdown("#### 🏗️ Built on a $0 / local stack")
    st.markdown(
        "DuckDB · dbt · LiteLLM → **local Ollama** · Langfuse · statsmodels · Streamlit. "
        "Enterprise analogs (Snowflake · MSK · Statsig · Superset) are documented as ADRs, "
        "not built — the architecture story without the cloud bill."
    )
    st.caption("Synthetic data; portfolio pilot. Code & ADRs in the repo.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 2 — Funnel Diagnosis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_funnel:
    st.subheader("The funnel: where users drop off")

    left, right = st.columns([3, 2])
    with left:
        fig = go.Figure(go.Funnel(
            y=funnel.stage,
            x=funnel.users,
            textinfo="value+percent initial",
            marker=dict(
                color=[ACCENT, ACCENT_DIM, ACCENT_DIM, BAD, MUTED, MUTED],
                line=dict(width=0),
            ),
            connector=dict(line=dict(color="rgba(129,140,248,0.2)", width=1)),
        ))
        fig.update_layout(
            height=400,
            **PLOTLY_LAYOUT,
        )
        # Annotate the drop
        fig.add_annotation(
            x=comp, y="ai_analysis_completed",
            text=f"← {drop:.0%} drop-off",
            showarrow=True, arrowhead=2,
            arrowcolor=BAD, font=dict(color=BAD, size=13, family="Inter"),
            ax=80, ay=-30,
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("#### Step conversion rates")
        for _, row in funnel.iterrows():
            stage = row["stage"].replace("_", " ").title()
            users = int(row["users"])
            step_cvr = row.get("step_conversion_pct", None)
            pct_top = row.get("pct_of_top", None)
            if pd.isna(step_cvr):
                st.markdown(f"**{stage}** — {users:,} users (top of funnel)")
            else:
                color = GOOD if step_cvr > 75 else (WARN if step_cvr > 60 else BAD)
                st.markdown(
                    f"**{stage}** — {users:,} users "
                    f"<span style='color:{color};font-weight:600;'>"
                    f"({step_cvr:.1f}% step CVR)</span>",
                    unsafe_allow_html=True,
                )

        st.download_button(
            "📥 Download funnel data",
            funnel.to_csv(index=False),
            "funnel.csv",
            "text/csv",
        )

    st.divider()

    # Latency diagnosis
    st.subheader("The diagnosis: latency drives the drop-off")

    lc, rc = st.columns([3, 2])
    with lc:
        fig = go.Figure(go.Bar(
            x=cohorts.latency_band,
            y=cohorts.completion_rate_pct,
            marker=dict(
                color=BANDS,
                line=dict(width=0),
                cornerradius=6,
            ),
            text=[f"{v:.0f}%" for v in cohorts.completion_rate_pct],
            textposition="outside",
            textfont=dict(color=TEXT, size=14, family="Inter"),
        ))
        fig.update_layout(
            height=380,
            yaxis_title="Completion %",
            yaxis_range=[0, 105],
            **PLOTLY_LAYOUT,
        )
        # Add trend annotation
        fig.add_annotation(
            x=cohorts.latency_band.iloc[-1], y=cohorts.completion_rate_pct.iloc[-1],
            text=f"2× worse<br>than fast",
            showarrow=True, arrowhead=2,
            arrowcolor=BAD, font=dict(color=BAD, size=11, family="Inter"),
            ax=0, ay=-40,
        )
        st.plotly_chart(fig, use_container_width=True)

    with rc:
        st.markdown("#### Latency band breakdown")
        for i, (_, row) in enumerate(cohorts.iterrows()):
            band = row["latency_band"]
            sessions = int(row["sessions"])
            avg_lat = float(row["avg_latency_s"])
            comp_rate = float(row["completion_rate_pct"])
            color = BANDS[i]
            st.markdown(
                f"<span style='color:{color};font-weight:700;'>●</span> "
                f"**{band}** — {sessions:,} sessions, avg {avg_lat:.1f}s, "
                f"<span style='color:{color};font-weight:600;'>{comp_rate:.1f}%</span> completion",
                unsafe_allow_html=True,
            )
        st.markdown("")
        st.caption(
            "Completion craters as LLM latency rises — the case for the fallback router. "
            "The > 8s band is nearly **half** the < 3s band."
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 3 — Experiment Results
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_exp:
    st.subheader("2×2 factorial experiment results")

    # SRM check — gatekeeper
    srm = exp.get("srm", {})
    if srm:
        srm_pass = srm.get("pass", True)
        if srm_pass:
            st.success(
                f"✅ **Randomization Integrity (SRM)**: χ² = {srm['chi2']:.1f}, "
                f"p = {srm['p_value']:.3f} — cell counts balanced. Experiment is valid.",
                icon="🔒",
            )
        else:
            st.error(
                f"⛔ **Sample Ratio Mismatch**: χ² = {srm['chi2']:.1f}, "
                f"p = {srm['p_value']:.4f} — randomization integrity compromised!",
                icon="🚨",
            )

    # Main chart: completion by cell with CIs
    names = {(0, 0): "Control", (1, 0): "Progress Bar", (0, 1): "Fallback", (1, 1): "Both"}
    cells = sorted(exp["cells"], key=lambda c: (c["progress_bar"], c["fallback"]))
    labels = [names[(c["progress_bar"], c["fallback"])] for c in cells]
    vals = [100 * c["completion"] for c in cells]
    colors = [MUTED, ACCENT_DIM, ACCENT, GOOD]

    # CI error bars
    ci_lo = [100 * c.get("ci_lo", c["completion"]) for c in cells]
    ci_hi = [100 * c.get("ci_hi", c["completion"]) for c in cells]
    error_y_minus = [v - lo for v, lo in zip(vals, ci_lo)]
    error_y_plus = [hi - v for v, hi in zip(vals, ci_hi)]

    ec1, ec2 = st.columns([3, 2])
    with ec1:
        fig = go.Figure(go.Bar(
            x=labels, y=vals,
            marker=dict(color=colors, line=dict(width=0), cornerradius=6),
            text=[f"{v:.1f}%" for v in vals],
            textposition="outside",
            textfont=dict(color=TEXT, size=13, family="Inter"),
            error_y=dict(
                type="data",
                symmetric=False,
                array=error_y_plus,
                arrayminus=error_y_minus,
                color=MUTED,
                thickness=2,
                width=6,
            ),
        ))
        fig.update_layout(
            height=400,
            yaxis_title="Completion %",
            yaxis_range=[0, max(ci_hi) + 8],
            **PLOTLY_LAYOUT,
        )
        # Annotate best cell
        best_idx = vals.index(max(vals))
        fig.add_annotation(
            x=labels[best_idx], y=vals[best_idx] + error_y_plus[best_idx] + 1,
            text=f"+{cells[best_idx]['lift_pp']:.1f}pp lift ⭐",
            showarrow=False,
            font=dict(color=GOOD, size=12, family="Inter"),
            yshift=10,
        )
        st.plotly_chart(fig, use_container_width=True)

    with ec2:
        st.markdown("#### Cell details")
        for c in cells:
            name = names[(c["progress_bar"], c["fallback"])]
            p_str = f"p < 0.001" if c.get("p_value") is not None and c["p_value"] < 0.001 else (
                f"p = {c['p_value']:.3f}" if c.get("p_value") is not None else "—"
            )
            lift_color = GOOD if c["lift_pp"] > 0 else (BAD if c["lift_pp"] < 0 else MUTED)
            st.markdown(
                f"**{name}** — {c['completion']:.1%} "
                f"<span style='color:{lift_color};'>({c['lift_pp']:+.1f}pp)</span>, "
                f"n = {c.get('n', '?'):,}, "
                f"<span style='color:#64748b;'>{p_str}</span>",
                unsafe_allow_html=True,
            )

        st.markdown("")
        st.markdown(
            f"**Interaction**: {exp['interaction_coef']:+.3f} (sub-additive) — "
            f"the two fixes share some of their lift."
        )

    st.divider()

    # Guardrail
    g1, g2 = st.columns([3, 2])
    with g1:
        st.markdown("#### 🛡️ Non-Inferiority Guardrail: Default Rate")
        g = exp["guardrail"]

        # Bullet gauge for guardrail
        fig = go.Figure(go.Indicator(
            mode="number+gauge+delta",
            value=g["upper_bound_pp"],
            delta={"reference": g["nim_pp"], "relative": False, "valueformat": ".2f",
                   "increasing": {"color": BAD}, "decreasing": {"color": GOOD}},
            number={"suffix": "pp", "font": {"color": TEXT, "size": 28}},
            title={"text": "95% Upper Bound on Default Increase", "font": {"color": MUTED, "size": 14}},
            gauge={
                "shape": "bullet",
                "axis": {"range": [0, max(g["nim_pp"] * 1.5, g["upper_bound_pp"] * 1.5)],
                         "tickfont": {"color": MUTED}},
                "bar": {"color": GOOD if g["non_inferior"] else BAD, "thickness": 0.6},
                "bgcolor": "rgba(30,41,59,0.5)",
                "threshold": {
                    "line": {"color": WARN, "width": 3},
                    "thickness": 0.8,
                    "value": g["nim_pp"],
                },
                "steps": [
                    {"range": [0, g["nim_pp"]], "color": "rgba(52,211,153,0.1)"},
                    {"range": [g["nim_pp"], g["nim_pp"] * 1.5], "color": "rgba(248,113,113,0.1)"},
                ],
            },
        ))
        fig.update_layout(height=160, **{k: v for k, v in PLOTLY_LAYOUT.items() if k != "margin"}, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        st.markdown("#### Guardrail details")
        st.markdown(f"""
- Default rate (fallback): **{g['default_fallback']:.2%}**
- Default rate (control): **{g['default_control']:.2%}**
- Difference: **{g['diff_pp']:+.2f}pp**
- 95% UB: **+{g['upper_bound_pp']:.2f}pp** < **{g['nim_pp']:.1f}pp NIM**
- Verdict: **{'✅ Non-inferior' if g['non_inferior'] else '⛔ Breach'}**
        """)
        
    st.divider()
    
    if fairness and "prime" in fairness:
        pr, sb = fairness["prime"], fairness["subprime"]
        fg1, fg2 = st.columns([3, 2])
        with fg1:
            st.markdown("#### ⚖️ Fairness Guardrail: Equal Benefit Across Credit Bands")
            st.markdown(
                "Does the latency-fallback **router** lift completion for **subprime** applicants "
                "as much as **prime** ones? (Credit score < 670 as a socioeconomic proxy.) Tested by "
                "one-sided **non-inferiority** on the prime−subprime difference-in-differences."
            )
            fig = go.Figure(data=[
                go.Bar(name="Control", x=["Prime", "Subprime"],
                       y=[pr["control"] * 100, sb["control"] * 100], marker_color=MUTED,
                       text=[f"{pr['control']*100:.1f}%", f"{sb['control']*100:.1f}%"], textposition="auto"),
                go.Bar(name="Fallback router on", x=["Prime", "Subprime"],
                       y=[pr["fallback"] * 100, sb["fallback"] * 100], marker_color=ACCENT,
                       text=[f"{pr['fallback']*100:.1f}%", f"{sb['fallback']*100:.1f}%"], textposition="auto"),
            ])
            fig.update_layout(barmode="group", height=300, yaxis_title="Completion %",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                              **PLOTLY_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

        with fg2:
            st.markdown("#### Fairness details")
            verdict = "✅ Non-inferior" if fairness["non_inferior"] else "⛔ Disparate impact"
            st.markdown(f"""
- Prime lift from router: **+{pr['lift_pp']:.1f}pp** (n={pr['n']:,})
- Subprime lift from router: **+{sb['lift_pp']:.1f}pp** (n={sb['n']:,})
- Gap the router opens: **+{fairness['disparity_pp']:.2f}pp**
- 95% upper bound: **+{fairness['upper_bound_pp']:.2f}pp** < **{fairness['nim_pp']:.1f}pp** margin
- Verdict: **{verdict}**
            """)
            st.caption(
                "The router helps subprime applicants slightly less, but the gap stays within the "
                "pre-registered fairness margin — no disparate-impact flag. A larger gap would FAIL this test."
            )

    # Statistical details expander
    with st.expander("📐 Statistical Details (Power, MDE, Multiple Testing)"):
        power = exp.get("power", {})
        pvals = exp.get("p_values", {})
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown("**Power analysis**")
            st.markdown(f"""
- Achieved power: **{power.get('achieved_power', '?')}**
- MDE (effect size h): **{power.get('mde_effect_size_h', '?')}**
- n per arm: **{power.get('n_per_arm', '?'):,}**
            """)
        with sc2:
            st.markdown("**P-values (two-sided z-test)**")
            for name, pv in pvals.items():
                badge = "🟢" if pv < 0.05 else "🔴"
                st.markdown(f"{badge} {name}: **p = {pv:.4f}**" if pv > 0 else f"{badge} {name}: **p < 0.001**")
            st.markdown(f"Interaction: **p = {exp['interaction_p']:.4f}**")
        with sc3:
            st.markdown("**SRM Check**")
            if srm:
                st.markdown(f"""
- Cell counts: {srm.get('cell_counts', '?')}
- χ²: **{srm.get('chi2', '?')}**
- p-value: **{srm.get('p_value', '?')}**
- Status: **{'✅ Pass' if srm.get('pass') else '⛔ Fail'}**
                """)

    st.download_button(
        "📥 Download experiment summary",
        json.dumps(exp, indent=2),
        "experiment_summary.json",
        "application/json",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 4 — Cost Economics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_cost:
    st.subheader("LLM cost per converted user")

    co1, co2 = st.columns([3, 2])
    with co1:
        cc = cost[cost.model_version != "ALL"]
        fig = go.Figure(go.Bar(
            x=cc.model_version,
            y=cc.cost_per_converted_user,
            marker=dict(color=[ACCENT, GOOD], line=dict(width=0), cornerradius=6),
            text=[f"${v:.4f}" for v in cc.cost_per_converted_user],
            textposition="outside",
            textfont=dict(color=TEXT, size=14, family="Inter"),
        ))
        fig.update_layout(
            height=380,
            yaxis_title="$ / converted user",
            **PLOTLY_LAYOUT,
        )
        # Annotate savings
        fig.add_annotation(
            x="fast", y=cpc_fast,
            text=f"{cpc_primary/cpc_fast:.1f}× cheaper",
            showarrow=True, arrowhead=2,
            arrowcolor=GOOD, font=dict(color=GOOD, size=12, family="Inter"),
            ax=60, ay=-30,
        )
        st.plotly_chart(fig, use_container_width=True)

    with co2:
        st.markdown("#### Cost breakdown")
        for _, row in cc.iterrows():
            mv = row["model_version"]
            sessions = int(row["sessions"])
            total = float(row["total_cost_usd"])
            cpc_val = float(row["cost_per_converted_user"])
            color = ACCENT if mv == "primary" else GOOD
            st.markdown(
                f"<span style='color:{color};font-weight:700;'>●</span> "
                f"**{mv}** — {sessions:,} sessions, "
                f"\\${total:.2f} total, "
                f"<span style='color:{color};font-weight:600;'>"
                f"\\${cpc_val:.4f}/conv</span>",
                unsafe_allow_html=True,
            )
        st.markdown("")
        st.caption(
            f"The fast fallback model is **{cpc_primary/cpc_fast:.1f}×** cheaper per conversion — "
            "the router cuts cost **and** lifts completion."
        )

    st.divider()

    # What-If simulator
    st.subheader("🔮 What-If Simulator")
    st.caption("Estimate the impact of routing more traffic to the fast model.")

    sim1, sim2 = st.columns(2)
    with sim1:
        fast_pct = st.slider(
            "% of traffic routed to fast model",
            min_value=0, max_value=100, value=15,
            format="%d%%",
            help="Currently ~15% of sessions use the fast model.",
        )
    with sim2:
        latency_target = st.slider(
            "Target P95 latency (seconds)",
            min_value=1.0, max_value=12.0, value=5.0, step=0.5,
            help="Slide to estimate completion at different latency targets.",
        )

    # Compute what-if outcomes
    total_sessions = int(cost.loc[cost.model_version == "ALL", "sessions"].iloc[0])
    total_converted = int(cost.loc[cost.model_version == "ALL", "converted_users"].iloc[0])

    fast_sessions_sim = int(total_sessions * fast_pct / 100)
    primary_sessions_sim = total_sessions - fast_sessions_sim
    avg_cost_primary = float(cost.loc[cost.model_version == "primary", "avg_cost_per_session"].iloc[0])
    avg_cost_fast = float(cost.loc[cost.model_version == "fast", "avg_cost_per_session"].iloc[0])
    sim_total_cost = primary_sessions_sim * avg_cost_primary + fast_sessions_sim * avg_cost_fast
    sim_cpc = sim_total_cost / total_converted if total_converted > 0 else 0

    # Latency → completion interpolation from cohort data
    lat_points = cohorts.avg_latency_s.tolist()
    comp_points = cohorts.completion_rate_pct.tolist()
    projected_completion = float(np.interp(latency_target, lat_points, comp_points))

    ws1, ws2, ws3, ws4 = st.columns(4)
    ws1.metric("Projected Blended Cost", f"${sim_total_cost:.2f}",
               f"{(sim_total_cost / float(cost.loc[cost.model_version == 'ALL', 'total_cost_usd'].iloc[0]) - 1):.0%} vs current")
    ws2.metric("Projected CPC", f"${sim_cpc:.4f}",
               f"{(sim_cpc / float(cost.loc[cost.model_version == 'ALL', 'cost_per_converted_user'].iloc[0]) - 1):.0%} vs current")
    ws3.metric(f"Est. Completion @ {latency_target:.1f}s", f"{projected_completion:.1f}%",
               help="Interpolated from latency cohort data")
    ws4.metric("Fast Model Sessions", f"{fast_sessions_sim:,}",
               f"{fast_pct}% of {total_sessions:,}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB 5 — Production Monitoring
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_monitor:
    st.subheader("CUSUM latency-drift detector")

    # Status indicator
    alarm_fired = cmeta["alarm_day"] is not None
    if alarm_fired:
        st.warning(
            f"🔴 **Alarm fired on Day {cmeta['alarm_day']}** — "
            f"latency regime shift detected {cmeta['detection_delay']} day(s) after injection at Day {cmeta['change_day']}.",
            icon="⚠️",
        )
    else:
        st.success("🟢 **No drift detected** — CUSUM statistic remains below threshold.", icon="✅")

    # Dual-axis chart: latency + CUSUM statistic
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.45],
        vertical_spacing=0.08,
        subplot_titles=["Daily Mean Latency (s)", "CUSUM Statistic (Sₜ)"],
    )

    # Top: latency series
    # Pre-alarm region
    pre_alarm = cusum[cusum.day < cmeta.get("change_day", len(cusum))]
    post_alarm = cusum[cusum.day >= cmeta.get("change_day", len(cusum))]

    fig.add_trace(go.Scatter(
        x=pre_alarm.day, y=pre_alarm.latency_s,
        name="Latency (normal)",
        line=dict(color=ACCENT, width=2),
        mode="lines",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=post_alarm.day, y=post_alarm.latency_s,
        name="Latency (post-shift)",
        line=dict(color=BAD, width=2),
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(248,113,113,0.08)",
    ), row=1, col=1)

    # Regime shift vline
    fig.add_vline(x=cmeta["change_day"], line=dict(color=WARN, dash="dot", width=2),
                  annotation_text="Regime shift", annotation_font=dict(color=WARN, size=11),
                  row=1, col=1)

    # Alarm vline
    if alarm_fired:
        fig.add_vline(x=cmeta["alarm_day"], line=dict(color=BAD, width=2),
                      annotation_text="CUSUM alarm", annotation_font=dict(color=BAD, size=11),
                      row=1, col=1)

    # Baseline reference
    fig.add_hline(y=cmeta["mu0"], line=dict(color=MUTED, dash="dash", width=1),
                  annotation_text=f"μ₀ = {cmeta['mu0']}s", annotation_font=dict(color=MUTED, size=10),
                  row=1, col=1)

    # Bottom: CUSUM statistic
    cusum_pre = cusum[cusum.day < cmeta.get("change_day", len(cusum))]
    cusum_post = cusum[cusum.day >= cmeta.get("change_day", len(cusum))]

    fig.add_trace(go.Scatter(
        x=cusum_pre.day, y=cusum_pre.cusum,
        name="Sₜ (normal)",
        line=dict(color=ACCENT_DIM, width=2),
        mode="lines",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=cusum_post.day, y=cusum_post.cusum,
        name="Sₜ (post-shift)",
        line=dict(color=BAD, width=2.5),
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(248,113,113,0.12)",
    ), row=2, col=1)

    # Threshold line
    fig.add_hline(y=cmeta["threshold_h"], line=dict(color=WARN, dash="dash", width=2),
                  annotation_text=f"h = {cmeta['threshold_h']}",
                  annotation_font=dict(color=WARN, size=11),
                  row=2, col=1)

    fig.update_layout(
        height=550,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=MUTED, size=11)),
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("xaxis", "yaxis", "margin")},
        margin=dict(l=10, r=10, t=50, b=10),
    )
    # Style subplots
    for i in range(1, 3):
        fig.update_xaxes(gridcolor="rgba(148,163,184,0.1)", row=i, col=1)
        fig.update_yaxes(gridcolor="rgba(148,163,184,0.1)", row=i, col=1)
    fig.update_xaxes(title_text="Day", row=2, col=1)
    fig.update_yaxes(title_text="Latency (s)", row=1, col=1)
    fig.update_yaxes(title_text="Sₜ", row=2, col=1)

    # Update subplot title colors
    for ann in fig.layout.annotations:
        ann.font.color = TEXT

    st.plotly_chart(fig, use_container_width=True)

    # Metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Detection Delay", f"{cmeta['detection_delay']} day{'s' if cmeta['detection_delay'] != 1 else ''}" if cmeta["detection_delay"] else "N/A",
              help="Days from injected regression to CUSUM alarm")
    m2.metric("Threshold (h)", f"{cmeta['threshold_h']:.1f}",
              help="CUSUM decision interval: h = 5σ")
    m3.metric("Baseline μ₀", f"{cmeta['mu0']}s",
              help="Expected mean latency under normal operation")
    m4.metric("Alarm Day", f"Day {cmeta['alarm_day']}" if alarm_fired else "None",
              help="Day the CUSUM statistic exceeded threshold h")

    with st.expander("📖 How CUSUM works"):
        # NOTE: keep the LaTeX in a RAW string and inject the delay separately — calling
        # str.format() on a string containing $S_{t-1}$ raises KeyError('t-1').
        st.markdown(r"""
**Cumulative Sum (CUSUM)** is a sequential analysis technique for quickest detection of mean shifts.

The one-sided upper CUSUM accumulates evidence of an upward shift:

$$S_t = \max(0,\; S_{t-1} + (x_t - \mu_0 - k))$$

An alarm fires when $S_t > h$, where:
- $\mu_0$ = expected mean under normal operation
- $k$ = allowance (typically $0.5\sigma$) — controls sensitivity
- $h$ = decision interval (typically $5\sigma$) — controls false alarm rate

The tradeoff: smaller $h$ detects faster but triggers more false alarms (ARL₀).
        """)
        _delay = f"{cmeta['detection_delay']} day(s)" if cmeta["detection_delay"] else "N/A"
        st.markdown(f"In this demo, the injected shift (μ jumps from 5.9s to 7.5s) is large "
                    f"enough that the detector fires in just **{_delay}**.")

    st.download_button(
        "📥 Download CUSUM series",
        cusum.to_csv(index=False),
        "cusum_series.csv",
        "text/csv",
    )
