# Backlog — tracked carry-over items

Small, deliberately-deferred items that must not be forgotten. Each says *when* it
must land. Newest at top.

---

## [ ] Confounder enrichment of `abandon_prob` — **do before Phase 3**

**Why.** Today `abandon_prob = f(latency)` only, so LLM latency is the *sole* systematic
driver of abandonment. That is too clean and, critically, makes the planned **back-door
causal adjustment circular** — there is no confounder to adjust for, so the "adjusted"
estimate just re-recovers the injected effect. (See `docs/adr/0001-statistical-methods.md`,
Consequences; graph edge: `Back-door adjustment —requires confounder in→ Synthetic data generator`.)

**Change** (in `synthetic-data/generate.py`): introduce a real confounder + secondary
drivers so latency and abandonment share a common cause.
- Make LLM `latency_s` partly depend on `input_tokens` (more tokens → slower).
- Make `input_tokens` correlate with `requested_amount` (bigger loans → richer bank
  statements → more tokens).
- Add a **commitment** effect: higher `requested_amount` → *lower* baseline abandonment,
  independent of latency (more-committed applicants push through).
- Add a secondary `device` effect (mobile more impatient) + irreducible noise.
- Keep **latency the dominant driver** so the diagnostic still holds.

**Acceptance criteria.**
- initiated→completed drop stays ~32–33%.
- Latency-band completion gradient stays strong & monotone (~mid-80s% → ~mid-40s%).
- Base default rate held ~8%.
- **The real test:** the naive latency↔completion correlation must differ from the
  back-door-*adjusted* estimate — i.e. confounding is real and adjustment moves the
  number. If they're identical, the confounder isn't doing anything.

**When.** Before Phase 3; ideally folded into Phase 1 data refinement so the dbt marts
are built on the enriched data once, not twice.
