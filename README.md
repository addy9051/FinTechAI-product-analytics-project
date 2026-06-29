# LoanLens — diagnosing & fixing a 32% AI-analysis drop-off in an LLM micro-loan funnel

A portfolio-grade analytics + LLM-ops pilot. It reproduces, in a fully local /
free-tier stack, the hero problem from a production FinTech blueprint:

> An LLM "bank-statement analysis" step loses **~32% of users** between *analysis
> initiated* and *completed*. This project shows the drop-off is **latency-driven**,
> fixes it with an **LLM latency-fallback router**, and **validates the fix with a
> 2×2 experiment** that protects loan-default rate as a non-inferiority guardrail.

**Headline metric:** LLM **cost per converted user** and the latency→conversion curve.

---

## The diagnostic (from real generated data)

| LLM latency band | users | avg latency | AI-analysis completion |
|---|--:|--:|--:|
| `<3s` (low)  | 3,638 | 1.8s | **88.8%** |
| `3–5s`       | 2,969 | 4.0s | 80.0% |
| `5–8s`       | 5,360 | 6.5s | 63.8% |
| `>8s` (high) | 4,318 | 9.9s | **44.0%** |

Overall initiated→completed drop-off: **32.9%**. Completion more than halves as
latency rises — the evidence base for the fallback router.

---

## Stack (everything runs at ~$0)

| Layer | Tool | Enterprise equivalent (see `docs/ADRs`) |
|---|---|---|
| Synthetic data | SDV / Faker + numpy | MOSTLY AI |
| Warehouse | **DuckDB** (local file) | Snowflake on AWS |
| Transformation | **dbt-duckdb** | dbt Core on Snowflake |
| LLM gateway | **LiteLLM** → **Ollama** (local) | LiteLLM/Portkey → GPT-4o/Claude |
| LLM observability | **Langfuse** (free tier / self-host) | Langfuse Cloud |
| Experimentation | Python (statsmodels/scipy) | Statsig |
| BI / dashboard | **Streamlit** (deployed free) | Apache Superset |
| Ingestion/stream | Python event producer | RudderStack → Kinesis/MSK |

The expensive production components (MSK, PCI tokenization, SOC2 controls) are
**documented as ADRs and a scaling section**, not built — the architecture story
without the cloud bill.

---

## Quickstart

```bash
python -m pip install -r requirements.txt

# Phase 0 — synthetic data + warehouse (done)
python synthetic-data/generate.py --users 20000 --seed 42
python synthetic-data/load_duckdb.py
```

Roadmap:
- **Phase 1** — dbt models: staging → marts, rolling-latency window function, funnel, latency-band cohorts.
- **Phase 2** — LiteLLM gateway → Ollama with a >4s latency-fallback router + Langfuse tracing; compute cost-per-converted-user.
- **Phase 3** — 2×2 factorial (progress bar × fallback) with a one-sided non-inferiority test on loan-default rate.
- **Phase 4** — Streamlit dashboard, deployed to a free host for a clickable demo.

## Repo layout
```
synthetic-data/  generators + DuckDB loader
dbt/             models (staging/intermediate/marts), tests, docs
llm/             LiteLLM gateway config, fallback rules, Langfuse instrumentation
experiments/     power analysis + 2×2 + guardrail notebooks
dashboard/       Streamlit app
infra/           sample Terraform (illustrative)
docs/            architecture diagram, ADRs, cost model
```
