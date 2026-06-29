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
- **Phase 1 — DONE.** dbt-duckdb project: 4 `stg_` → 3 `int_` → 2 `fct_` marts; rolling-latency window fn; funnel + latency-band cohort marts. 9 models, 27 tests pass. Marts: `fct_funnel`, `fct_latency_cohorts`.
- **Phase 2 — DONE.** Router (`llm/gateway.py`): primary `ollama_chat/llama3.2` → fast `ollama_chat/llama3.2:1b` on >4s, with telemetry. Cost-per-converted-user mart `fct_llm_cost`. Langfuse tracing via litellm `langfuse_otel` — verified traces land (name/user/tags/session).
- **Phase 3 — DONE.** `experiments/`: 2×2 factorial (z-test + **interaction**), power, SRM, A/A, Benjamini-Hochberg, one-sided **non-inferiority guardrail** → SHIP decision; back-door causal (`causal_backdoor.py`). Confounder enrichment done. Optional remaining: sequential mSPRT.
- **Phase 4 — BUILT.** Streamlit dashboard (`dashboard/app.py`) reads committed snapshots (`dashboard/data/`, built by `build_snapshots.py`) — no DuckDB/Ollama at runtime. CUSUM drift monitor (`dashboard/cusum.py`, 1-day detection). Verified via Streamlit AppTest. **Deploy = user step** (Streamlit Cloud, main file `dashboard/app.py`, deps `dashboard/requirements.txt`).

**Tracked carry-overs** (`docs/BACKLOG.md`): none open — confounder enrichment DONE.

## Key facts (don't re-derive)
- Funnel stages: `sign_up → bank_link → ai_analysis_initiated → ai_analysis_completed → loan_terms_offered → loan_accepted`.
- The ~33% drop is between `ai_analysis_initiated` and `ai_analysis_completed`, **driven by LLM latency** (`abandon_logit` in the generator). `requested_amount` is a **confounder**: → tokens → latency, AND → commitment → completion. So naive latency↔completion is biased; back-door adjustment on amount is needed.
- Latency bands: `<3s / 3–5s / 5–8s / >8s`. Completion rates (post-enrichment): 86.4% → 78.9% → 63.1% → 43.3%.
- Raw tables in DuckDB: `raw_users`, `raw_funnel_events`, `raw_llm_traces`, `raw_loans`.
- Fallback threshold = **4s**; default rate ≈ 7.8%; default risk = f(credit_score, requested_amount).
- Local Ollama is **CPU-only and slow** (3B cold-load ~60s; even 1B inference ~8s). So: `warmup()` models before timed routing; the live gateway *proves the mechanism* on a few cases, while at-scale cost/funnel analysis uses the synthetic `raw_llm_traces` (never 20k live calls).
- **Cost per converted user** (`fct_llm_cost`): primary **$0.036** vs fast **$0.0076** (~4.8×); blended $0.031. The fallback **cuts cost AND lifts completion** — the core Phase 2 result.
- Langfuse: litellm **`langfuse_otel`** callback (matches v4 SDK), needs **`pydantic-settings`** installed, reads **`LANGFUSE_OTEL_HOST`** (gateway derives it from canonical **`LANGFUSE_BASE_URL`**). Keys in `.env`, **EU region**. Attempt+fallback grouped by `session_id`. Official Langfuse skill installed at `.claude/skills/langfuse/`.
- **Phase 3 experiment** (`experiments/`, fresh 2×2 sim, injected ground truth): completion lifts progress **+3.3pp**, fallback **+8.5pp**, both **~+9.2pp**; interaction sub-additive (sig). Guardrail default +0.33pp, one-sided 95% UB **+0.64pp < NIM 1.0pp → non-inferior → SHIP**. Back-door latency coef **−0.264 (naive) → −0.298 (adjusted)**.
- **Fairness guardrail** (`experiments/analyze_experiment.py` §8 + dashboard, in parity): the 2×2 sim injects a credit subgroup (subprime 36%) whose fallback completion lift is **0.6pp smaller**; a one-sided **non-inferiority** test on the prime−subprime difference-in-differences (router widens gap ~0.3pp, 95% UB ~1.3pp **< 2pp NIM → non-inferior**). Folded into the ship gate. This *can* fail — it replaced an earlier circular check that grouped by `fallback_triggered` (= slow-primary, not the fast model) and was null-by-construction.
- **Dashboard economics** (exec tab): revenue = **MARGIN on incremental FUNDED loans** (avg loan $2,300, 12% margin ≈ $276/loan, funded/completion ~0.61, annualized ×365/120) — NOT loan principal. CAC **$1,450** (blueprint SMB benchmark); LLM cost is ~0.003% of CAC.
- **Dashboard is now tabbed** (`dashboard/app.py`): Exec Summary · Funnel · Experiment (incl. SRM/power/fairness) · Cost (what-if sim) · Monitoring (CUSUM). Dark theme. Snapshots incl. `fairness_summary.json`, `build_meta.json`.

## Statistical methods (Phase 3) — locked
Full rationale + triage table: `docs/adr/0001-statistical-methods.md`. Governing rule:
data is **synthetic**, so favour methods whose demonstration is *honest* (A/A calibration,
changepoint with an injected shift, SRM with an injected bad split) over ones that merely
recover an injected effect.
- **BUILD — core:** two-proportion z-test (completion), 2×2 main effects **+ interaction**, one-sided non-inferiority test on default rate (**fixed-horizon**), power/sample-size.
- **BUILD — cheap rigor:** SRM χ² check, A/A simulation, Benjamini-Hochberg.
- **BUILD — one differentiator (LLM-ops headline):** CUSUM changepoint monitor on latency/default drift → dashboard. Add sequential mSPRT on the primary metric if time.
- **OPTIONAL — causal:** one back-door/DAG adjustment (backs the "causal via latency" claim); IV (ITT vs per-protocol) as the flex.
- **SKIP — ADR-only:** RDD, DiD/synthetic control, bandits (conflict with guardrail), DML, CUPED, GLR/weighted-SPRT/multistream.
- Guardrail stays **fixed-horizon** even when the primary metric runs sequential. Bandits skipped *because* a regret term can't encode a hard default-rate constraint.

## Commands
Dependency manager is **uv** (`pyproject.toml` + `uv.lock`). Phase deps are in
dependency groups; pull them per-phase. `requirements.txt` is an auto-generated
pip fallback — don't hand-edit it.
```bash
uv sync                                          # base env (Phase 0)
uv sync --group dbt                              # add a phase group: dbt | llm | experiments | dashboard
uv run python synthetic-data/generate.py --users 20000 --seed 42   # regenerate data
uv run python synthetic-data/load_duckdb.py      # load + print diagnostic
# Phase 1 — dbt (always run from project root):
uv run dbt run  --project-dir dbt --profiles-dir dbt
uv run dbt test --project-dir dbt --profiles-dir dbt
# Phase 2 — Ollama models (installed) + run the fallback router demo:
ollama pull llama3.2 && ollama pull llama3.2:1b
uv run python llm/gateway.py                      # warms models, then routes one analysis
# Phase 3 — experiment (fast; statsmodels/scipy):
uv run python experiments/simulate_experiment.py --n-per-arm 50000 --seed 7
uv run python experiments/analyze_experiment.py   # z-test, interaction, SRM, A/A, BH, guardrail
uv run python experiments/causal_backdoor.py      # naive vs back-door-adjusted latency effect
# Phase 4 — dashboard (rebuild snapshots after data changes, then run):
uv run python dashboard/build_snapshots.py        # export dashboard/data/*.{csv,json}
uv run streamlit run dashboard/app.py             # local dashboard at localhost:8501
# After changing deps, refresh the pip fallback:
uv export --all-groups --no-hashes --no-emit-project -o requirements.txt
```

## Conventions
- Heavy comments explaining the *why* (this is a portfolio piece — code is read by recruiters).
- dbt layers: `stg_` (1:1 cleanup) → `int_` (joins/logic) → `fct_`/`dim_` (marts).
- Switch high-volume models to incremental once they'd exceed ~10M rows (here: events/traces).
- Each phase is a clean context — `/clear` between phases to save tokens.
- Manage deps with uv only (`uv add`, `uv sync`) — never `pip install` into the project. New phase deps go in the matching `[dependency-groups]` entry.

## Repo layout
```
synthetic-data/  generators + DuckDB loader   dashboard/  Streamlit app
dbt/             models, tests, docs          infra/      sample Terraform (illustrative)
llm/             gateway + Langfuse           docs/       architecture diagram, ADRs, cost model
experiments/     power analysis + 2×2
```
