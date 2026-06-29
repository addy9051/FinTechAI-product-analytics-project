# ADR 0001 — Statistical methods for the funnel experiment & monitoring

- **Status:** Accepted
- **Date:** 2026-06-29
- **Phase:** 3 (experiment) + a Phase 4 monitoring extension
- **Deciders:** project owner

## Context

Phase 3 fixes the 32% AI-analysis drop-off and must *prove* the fix works without
quietly worsening credit quality. The space of applicable statistical methods is
large (fixed-horizon tests, sequential/always-valid tests, changepoint detection,
causal inference, bandits). This ADR triages that space into **build / cheap-add /
differentiator / skip**, so Phase 3 has a locked scope and the portfolio carries a
defensible "what we deliberately did *not* build, and why" story.

### Governing constraint — the data is synthetic and we wrote the generator

This is the single most important filter. It means:

- Methods that merely **recover an effect we injected** (most causal inference) are
  partly **circular** — usable as a *methods showcase* only if framed honestly, never
  sold as "discovery".
- Methods we can **validate by construction are legitimately impressive**: A/A
  calibration (p-values come out uniform), changepoint detection (inject a real
  latency regime-shift and show it's caught), SRM (inject a 55/45 split and show the
  χ² test fire). These earn their keep because the ground truth is knowable.

We therefore weight "does this demonstrate skill *without looking circular on data we
control*" alongside "does it serve the tight narrative".

## Decision

| Method | Verdict | Rationale (for *this* project) |
|---|---|---|
| Two-proportion z-test (completion rate) | **BUILD — core** | Primary metric of the 2×2. Non-negotiable. |
| 2×2 factorial: main effects **+ interaction** | **BUILD — core** | The interaction *is* the reason to run a 2×2 vs. two A/Bs. Headline artifact. |
| One-sided non-inferiority test (default rate) | **BUILD — core** | The guardrail. Most credible piece. Evaluated **fixed-horizon** (see Nuance 1). |
| Power / sample-size analysis | **BUILD — core** | Shows the test was sized deliberately (α=0.05, power=0.80, MDE). |
| Sample Ratio Mismatch (χ²) | **BUILD — cheap** | ~3 lines. Inject a bad split to show it firing — the honest version. |
| A/A simulation | **BUILD — cheap** | Non-circular: show false-positive rate ≈ 5%, p-values uniform. |
| Benjamini-Hochberg correction | **BUILD — cheap** | One call over the metric suite + interaction; shows multiple-testing maturity. |
| CUSUM changepoint monitor | **BUILD — differentiator** | Best fit for the **LLM-ops headline**; monitor latency/default drift → dashboard. Rarer in portfolios than another A/B test. |
| Sequential mSPRT (primary metric) | **BUILD — 2nd differentiator** | Mirrors Statsig "always-valid p-values"; pairs with the fixed-horizon guardrail contrast. Add if time allows. |
| Back-door / DAG adjustment | **OPTIONAL — one notebook** | Upgrades the diagnosis from "correlation" to "causal" — backs a claim CLAUDE.md already makes. |
| IV (ITT vs per-protocol) | **OPTIONAL — best causal flex** | Genuinely motivated: assignment to the router arm ≠ actually triggering a fallback (only >4s users do). Honest, not contrived. |
| DML (continuous latency) | **SKIP — stretch** | "Right" tool for continuous treatment, but effort + circular on synthetic data. |
| CUPED / delta method | **SKIP — for now** | Needs a pre-period covariate the funnel doesn't richly provide. |
| Regression Discontinuity (RDD) | **SKIP** | No credit-limit threshold *with an outcome on both sides* exists; adding one just to demo RDD is contrived. |
| Difference-in-differences / synthetic control | **SKIP** | No staged/geo rollout in a pilot synthetic set. Pure scope creep. |
| Bandits (Thompson / UCB / contextual) | **SKIP** | Conflicts with the guardrail narrative (see Nuance 2). |
| GLR, weighted SPRT, multistream, Shiryaev variants | **SKIP — ADR-only** | Gold-plating; name as "what we'd add at scale". |

## Three nuanced calls (the reasoning that matters)

**1. The guardrail stays fixed-horizon — even though the primary metric may be sequential.**
Run the latency/completion primary metric on a sequential engine (speed), but evaluate
the **default-rate guardrail fixed-horizon and maturation-adjusted** (auditability — no
peeking on the credit-risk metric; a null sequential result is not evidence of safety).
Articulating *that contrast* is more impressive than implementing both sequentially.

**2. Bandits: the reason to skip is itself the portfolio artifact.**
A regret-minimizing bandit will happily exploit a high-conversion arm that quietly
worsens defaults, because it treats reward as a scalar. The guardrail must be a **hard
constraint, not a reward term**. Writing this paragraph demonstrates more judgment than
a working Thompson sampler would. (A *constrained* bandit paired with the changepoint
monitor would be the real-world answer — noted as future work.)

**3. Causal inference: pick exactly one, framed honestly.**
Build the **back-door adjustment** — CLAUDE.md already claims the drop-off is "causal via
latency", and that claim currently rests on a cohort correlation. One DAG + adjusted
estimate (controlling device, requested_amount, etc.) closes that open loop. **IV** is the
better *range* flex if a second causal artifact is wanted; everything else causal is skipped.

## What we will build (Phase 3 shortlist)

1. **Core experiment:** two-proportion z-test + 2×2 interaction + one-sided
   non-inferiority guardrail (fixed-horizon) + power analysis.
2. **Cheap rigor wrap:** SRM χ² (with an injected bad split), A/A simulation,
   Benjamini-Hochberg.
3. **One headline differentiator:** CUSUM monitor on latency/default drift, surfaced on
   the Streamlit dashboard (Phase 4). Sequential mSPRT on the primary metric is the
   second pick if time allows.
4. **Optional causal notebook:** back-door/DAG adjustment (IV as a stretch).

## Consequences

- Phase 3 scope is bounded and defensible; no drift into RDD/DiD/bandits.
- The synthetic generator may need a mild enrichment (a confounder such as
  `requested_amount → tokens → latency` **and** `→ commitment → abandonment`) so the
  back-door adjustment has real work to do and isn't circular. (Tracked separately.)
- The "methods we deliberately did not build, and why" section above is itself a
  portfolio signal — judgment, which is rarer than technique.
