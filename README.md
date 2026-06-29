# LoanLens — diagnosing & fixing a 32% AI-analysis drop-off in an LLM powered micro-loan funnel

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

Dependencies are managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` +
`uv.lock`). Per-phase deps live in dependency groups, so the base install stays light.

```bash
uv sync                  # create the env with base deps (Phase 0)

# Phase 0 — synthetic data + warehouse (done)
uv run python synthetic-data/generate.py --users 20000 --seed 42
uv run python synthetic-data/load_duckdb.py
```

Later phases pull their own group, e.g. `uv sync --group dbt` (also: `llm`, `experiments`, `dashboard`).

<details><summary>No uv? Use the pip fallback</summary>

```bash
python -m pip install -r requirements.txt   # auto-generated from uv.lock (all groups)
python synthetic-data/generate.py --users 20000 --seed 42
python synthetic-data/load_duckdb.py
```
</details>

## Dashboard (the clickable demo)

The recruiter-facing payoff. It reads small committed snapshots in `dashboard/data/`
(funnel, latency cohorts, cost, 2×2 results, CUSUM series), so it runs with **no DuckDB,
dbt, or Ollama** — a fast, free deploy.

```bash
uv sync --group dashboard
uv run python dashboard/build_snapshots.py   # refresh snapshots from the pipeline
uv run streamlit run dashboard/app.py        # http://localhost:8501
```

**Live demo:** _&lt;add your Streamlit Cloud URL here&gt;_

**Deploy (free):** push to GitHub → [share.streamlit.io](https://share.streamlit.io) → New app →
set the main file to `dashboard/app.py` (deps come from `dashboard/requirements.txt`).

## Status — Phases 0–4 complete
- **Phase 1 ✅** dbt: staging → marts, rolling-latency window fn, funnel + latency-band cohorts.
- **Phase 2 ✅** LiteLLM → local Ollama fallback router (>4s) + Langfuse tracing; cost-per-converted-user.
- **Phase 3 ✅** 2×2 factorial + interaction, one-sided non-inferiority guardrail, back-door causal adjustment.
- **Phase 4 ✅** Streamlit dashboard + CUSUM drift monitor (deploy = the clickable demo).

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
