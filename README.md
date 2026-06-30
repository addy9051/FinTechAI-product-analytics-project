# LoanLens — diagnosing & fixing a 32% AI-analysis drop-off in an LLM powered micro-loan funnel

[![Live dashboard](https://img.shields.io/badge/Live_Dashboard-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://fintechai-analytics-project-ankitaddya.streamlit.app/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/deps-uv-261230)](https://docs.astral.sh/uv/)
[![Cost](https://img.shields.io/badge/infra_cost-%240-16a34a)](#stack-everything-runs-at-0)

A portfolio-grade **analytics-engineering + LLM-ops** pilot. It reproduces, on a fully
local / free-tier stack, the hero problem from a production FinTech blueprint:

> An LLM "bank-statement analysis" step loses **~one-third of users** between *analysis
> initiated* and *completed*. This project proves the drop-off is **latency-driven** (with
> an honest causal adjustment for a confounder), **fixes it with a latency-fallback router**
> that is ~4.8× cheaper per conversion, and **validates the fix with a 2×2 experiment**
> guarded by both a **loan-default** and a **fair-lending** non-inferiority test.

**▶ Live dashboard:** **https://fintechai-analytics-project-ankitaddya.streamlit.app/**
&nbsp;·&nbsp; *(Streamlit Community Cloud — may take ~30s to wake from sleep)*

---

## What it does, in one screen

```
                 diagnose ───────────► fix ───────────► validate ──────────► monitor
   latency cohorts (86%→43%)   LiteLLM→Ollama router   2×2 + 2 guardrails    CUSUM drift
   + back-door causal honesty   (>4s, 4.8× cheaper)    → SHIP decision        (1-day detect)
```

The headline skill is **LLM-ops + AI cost**: the gateway, the cost-per-converted-user
metric, and the latency→conversion curve are the spine; experimentation, causal inference,
and production monitoring wrap around it.

---

## The diagnostic — completion by LLM latency band

| LLM latency band | sessions | avg latency | AI-analysis completion |
|---|--:|--:|--:|
| `<3s` (low)  | 3,778 | 1.6s | **86.4%** |
| `3–5s`       | 3,088 | 4.0s | 78.9% |
| `5–8s`       | 5,144 | 6.5s | 63.1% |
| `>8s` (high) | 4,329 | 10.0s | **43.3%** |

Overall initiated→completed drop-off: **32.8%**. Completion roughly **halves** as latency
rises — the evidence base for the fallback router.

> **Causal honesty.** A naïve `latency → completion` estimate is *confounded*:
> `requested_amount` raises latency (more tokens) *and* completion (more-committed
> applicants). A **back-door adjustment** on `requested_amount` moves the latency
> coefficient **−0.264 → −0.298 (+12.8% stronger)** — the naïve number *understates* the
> harm. The synthetic data injects this confounder on purpose so the adjustment does real
> work, not circular recovery.

---

## The fix & the results

| Result | Value | Where |
|---|---|---|
| **2×2 completion lift** | progress-bar **+3.3pp**, fallback **+8.5pp**, both **+9.2pp** (sub-additive interaction, sig.) | `experiments/` |
| **LLM cost / converted user** | primary **$0.036** vs fast **$0.0076** (~**4.8×** cheaper); blended $0.031 | `dbt` mart `fct_llm_cost` |
| **Default-rate guardrail** | one-sided 95% UB **+0.64pp < 1.0pp NIM** → **non-inferior** (fixed-horizon) | `experiments/` |
| **Fair-lending guardrail** | prime−subprime gap 95% UB **+1.25pp < 2.0pp NIM** → **non-inferior** | `experiments/` + dashboard |
| **Drift monitor** | CUSUM catches an injected latency regime shift in **1 day** | `dashboard/cusum.py` |
| **Ship decision** | completion improves **AND** both guardrails hold → **SHIP** | dashboard / CLI |

Supporting rigor (all in the analysis layer): **SRM χ²** (fires on an injected bad split),
**A/A** simulation (false-positive rate ≈ 5%, uniform p-values), **Benjamini-Hochberg**
correction, and **power/MDE** analysis.

---

## Stack — everything runs at $0

| Layer | Portfolio build (local / free) | Enterprise analog (documented as ADR) |
|---|---|---|
| Synthetic data | SDV / Faker + numpy | MOSTLY AI |
| Warehouse | **DuckDB** (local file) | Snowflake on AWS |
| Transformation | **dbt-duckdb** (4 stg → 3 int → 3 fct marts, 27 tests) | dbt Core on Snowflake |
| LLM gateway / models | **LiteLLM** → local **Ollama** (`llama3.2` → `llama3.2:1b`) | LiteLLM/Portkey → GPT-4o / Claude |
| LLM observability | **Langfuse** (`langfuse_otel`, free tier) | Langfuse Cloud |
| Experimentation | **statsmodels / scipy** | Statsig |
| Dashboard | **Streamlit** (deployed free) | Apache Superset |
| Ingestion / stream | Python event producer | RudderStack → Kinesis / MSK |

Dependency manager is **[uv](https://docs.astral.sh/uv/)**; per-phase deps live in dependency
groups. The expensive production components (MSK, PCI tokenization, SOC2 controls) are
**documented as ADRs and scaling notes**, not built — the architecture story without the cloud bill.

---

## Quickstart

```bash
uv sync                                                         # base env (Phase 0)
uv run python synthetic-data/generate.py --users 20000 --seed 42
uv run python synthetic-data/load_duckdb.py                     # load + print the diagnostic

# Phase 1 — dbt marts (run from project root)
uv sync --group dbt
uv run dbt run  --project-dir dbt --profiles-dir dbt
uv run dbt test --project-dir dbt --profiles-dir dbt

# Phase 2 — LLM fallback router (needs Ollama installed: ollama.com)
uv sync --group llm
ollama pull llama3.2 && ollama pull llama3.2:1b
uv run python llm/gateway.py                                    # warms models, routes one analysis

# Phase 3 — experiment + causal (fast; statsmodels/scipy)
uv sync --group experiments
uv run python experiments/simulate_experiment.py --n-per-arm 50000 --seed 7
uv run python experiments/analyze_experiment.py                # z-test · interaction · SRM · A/A · BH · 2 guardrails
uv run python experiments/causal_backdoor.py                   # naïve vs back-door-adjusted latency effect

# Phase 4 — dashboard
uv sync --group dashboard
uv run python dashboard/build_snapshots.py                     # export dashboard/data/*.{csv,json}
uv run streamlit run dashboard/app.py                          # http://localhost:8501
```

<details><summary>No uv? Use the pip fallback</summary>

```bash
python -m pip install -r requirements.txt   # auto-generated from uv.lock (all groups)
```
</details>

**Langfuse tracing (optional):** copy `.env.example` → `.env`, add your `pk-lf-…` / `sk-lf-…`
keys and `LANGFUSE_BASE_URL`. Without keys the gateway runs unchanged, untraced.

---

## Statistical methods (locked in an ADR)

The full build/skip triage lives in [`docs/adr/0001-statistical-methods.md`](docs/adr/0001-statistical-methods.md).
Governing rule: **the data is synthetic, so favour methods whose demonstration is *honest***
(A/A calibration, SRM with an injected bad split, CUSUM with an injected shift, a back-door
adjustment that *moves* because of an injected confounder) over ones that merely recover a
planted effect.

- **Built:** two-proportion z-test, 2×2 main effects **+ interaction**, one-sided
  **non-inferiority** guardrails on default rate **and** fairness (fixed-horizon), power/MDE,
  SRM, A/A, Benjamini-Hochberg, CUSUM changepoint monitor, back-door causal adjustment.
- **Skipped (ADR-only, with reasons):** RDD, DiD/synthetic control, bandits (conflict with a
  hard guardrail), DML, CUPED, sequential variants on the guardrail.

---

## Repo layout

```
synthetic-data/  generator (Faker+numpy, injected latency→abandon + confounder) + DuckDB loader
dbt/             dbt-duckdb models (staging → intermediate → marts), tests, sources
llm/             LiteLLM gateway + latency-fallback router + Langfuse (langfuse_otel) tracing
experiments/     2×2 simulator + analysis (z-test/interaction/power/SRM/A-A/BH/guardrails) + back-door
dashboard/       Streamlit app, CUSUM monitor, snapshot builder, committed snapshots
docs/            ADRs (statistical methods), backlog
```

---

## Honest notes

- **Synthetic data by design.** The latency→abandonment mechanism and a credit-subgroup
  fairness disparity are *injected* so every method can be validated against a known ground
  truth. Lift is measured in the simulated 2×2, then *projected* onto the observed funnel.
- **Local Ollama is CPU-bound and slow** (3B cold-load ~60s). The live gateway *proves the
  mechanism* on a few cases; at-scale cost/funnel analysis uses the synthetic LLM traces.
- **Dollar figures use labeled assumptions** (avg loan $2,300, 12% margin, $1,450 CAC) and are
  framed as **margin on incremental funded loans**, not loan principal.

*Built by [Ankit Addya](https://github.com/addy9051). Portfolio pilot — synthetic data, real methods.*
