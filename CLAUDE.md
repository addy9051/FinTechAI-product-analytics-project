# CLAUDE.md — LoanLens

Portfolio project: diagnose & fix a **32% AI-analysis funnel drop-off** in an LLM
micro-loan platform. Built from an enterprise blueprint, but on a **$0 / local
stack** with a **live Streamlit demo** for recruiters. Headline skill: **LLM-ops
+ AI cost**. Full background lives in the agent memory file `project-loanlens`.

## Hard constraints (do not violate)
- **Cost = $0.** Local/free tiers only. LLM calls go to **local Ollama**, never a paid cloud API.
- **No Mixpanel, no Snowflake, no Kinesis/MSK, no Statsig SaaS, no Superset.** Those are the *enterprise* equivalents — document them as ADRs/scaling notes, don't build them.
- Never commit `data/*.parquet` or `data/*.duckdb` (already in `.gitignore`).
- Keep the blueprint's hero narrative tight; resist scope creep into the other 8 layers.

## Stack (portfolio equivalents)
| Layer | Tool | Enterprise analog (ADR only) |
|---|---|---|
| Synthetic data | SDV / Faker + numpy | MOSTLY AI |
| Warehouse | **DuckDB** (`data/warehouse.duckdb`) | Snowflake on AWS |
| Transformation | **dbt-duckdb** | dbt Core on Snowflake |
| LLM gateway | **LiteLLM** → **Ollama** | LiteLLM/Portkey → GPT-4o/Claude |
| LLM observability | **Langfuse** (Hobby/self-host) | Langfuse Cloud |
| Experiments | Python (statsmodels/scipy) | Statsig |
| Product analytics | PostHog (free cloud) | Amplitude |
| Dashboard | **Streamlit** (deploy free) | Apache Superset |

Ollama models: **`llama3.2`** = primary (slower), **`llama3.2:1b`** = fast fallback.

## Build phases
- **Phase 0 — DONE.** Synthetic data + DuckDB load. 32.9% drop confirmed, causal via latency.
- **Phase 1 — NEXT.** dbt project: staging → intermediate → marts; rolling-latency window fn; funnel + latency-band cohort marts.
- **Phase 2.** LiteLLM gateway + Ollama fallback router (>4s threshold) + Langfuse tracing; compute LLM **cost per converted user**.
- **Phase 3.** 2×2 factorial (progress bar × fallback) + one-sided **non-inferiority test** on loan-default rate (guardrail).
- **Phase 4.** Streamlit dashboard + deploy to Streamlit Cloud (the clickable link).

## Key facts (don't re-derive)
- Funnel stages: `sign_up → bank_link → ai_analysis_initiated → ai_analysis_completed → loan_terms_offered → loan_accepted`.
- The 32% drop is between `ai_analysis_initiated` and `ai_analysis_completed`, **driven by LLM latency** (`abandon_prob` in the generator).
- Latency bands: `<3s / 3–5s / 5–8s / >8s`. Confirmed completion rates: 88.8% → 80.0% → 63.8% → 44.0%.
- Raw tables in DuckDB: `raw_users`, `raw_funnel_events`, `raw_llm_traces`, `raw_loans`.
- Fallback threshold = **4s**; default rate ≈ 7.8%; default risk = f(credit_score, requested_amount).

## Commands
```bash
python -m pip install -r requirements.txt        # full deps
python synthetic-data/generate.py --users 20000 --seed 42   # regenerate data
python synthetic-data/load_duckdb.py             # load + print diagnostic
# Phase 2 prep (once Ollama installed):
ollama pull llama3.2 && ollama pull llama3.2:1b
```

## Conventions
- Heavy comments explaining the *why* (this is a portfolio piece — code is read by recruiters).
- dbt layers: `stg_` (1:1 cleanup) → `int_` (joins/logic) → `fct_`/`dim_` (marts).
- Switch high-volume models to incremental once they'd exceed ~10M rows (here: events/traces).
- Each phase is a clean context — `/clear` between phases to save tokens.

## Repo layout
```
synthetic-data/  generators + DuckDB loader   dashboard/  Streamlit app
dbt/             models, tests, docs          infra/      sample Terraform (illustrative)
llm/             gateway + Langfuse           docs/       architecture diagram, ADRs, cost model
experiments/     power analysis + 2×2
```
