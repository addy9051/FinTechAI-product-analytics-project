"""
2x2 factorial experiment analysis (Phase 3), implementing the build/skip triage from
docs/adr/0001-statistical-methods.md. Runs on data/experiment.parquet.

Sections:
  1. Two-proportion z-tests   - each cell vs control on completion (primary metric)
  2. 2x2 factorial logit      - main effects A, B + the A:B interaction
  3. Power / sample size      - achieved power + MDE for the completion metric
  4. SRM chi-square           - randomization integrity (passes here; fires on *_srm)
  5. A/A simulation           - false-positive rate ~5%, p-values ~uniform (honest on
                                synthetic data: validates the test pipeline by construction)
  6. Benjamini-Hochberg       - multiple-testing correction across the test suite
  7. Non-inferiority guardrail- one-sided, FIXED-HORIZON test that default rate is not
                                meaningfully worse (a null superiority test is NOT safety)
  8. Fairness guardrail       - one-sided non-inferiority on the prime-subprime completion
                                gap the router opens (fair-lending / disparate-impact check)
  9. Ship decision            - primary improves AND both guardrails non-inferior

Run:  uv run python experiments/analyze_experiment.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import chisquare, norm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest

DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
ALPHA = 0.05
NIM = 0.01          # non-inferiority margin: default rate may rise at most +1.0pp (risk-set)
FAIR_NIM = 0.02     # fairness margin: the router may widen the prime-subprime gap at most +2.0pp
CELL_NAMES = {(0, 0): "control", (1, 0): "progress-bar", (0, 1): "fallback", (1, 1): "both"}


def _rate(df, mask=None):
    s = df["completed"] if mask is None else df.loc[mask, "completed"]
    return s.mean(), len(s)


def two_prop(c1, n1, c0, n0):
    stat, p = proportions_ztest([c1, c0], [n1, n0])
    return stat, p


def section_ztests(df):
    print("\n=== 1. Two-proportion z-tests (completion vs control) ===")
    ctrl = df[(df.progress_bar == 0) & (df.fallback == 0)]
    c0, n0 = ctrl.completed.sum(), len(ctrl)
    p0 = c0 / n0
    pvals = {}
    for (a, b), name in CELL_NAMES.items():
        if (a, b) == (0, 0):
            continue
        arm = df[(df.progress_bar == a) & (df.fallback == b)]
        c1, n1 = arm.completed.sum(), len(arm)
        p1 = c1 / n1
        _, p = two_prop(c1, n1, c0, n0)
        pvals[name] = p
        print(f"  {name:12s}: {p1:.3%} vs {p0:.3%}  lift {100*(p1-p0):+.2f}pp  p={p:.2e}")
    return pvals


def section_factorial(df):
    print("\n=== 2. 2x2 factorial logit: completed ~ progress_bar * fallback ===")
    m = smf.logit("completed ~ progress_bar * fallback", data=df).fit(disp=0)
    for term in ["progress_bar", "fallback", "progress_bar:fallback"]:
        coef, p = m.params[term], m.pvalues[term]
        print(f"  {term:24s} coef={coef:+.4f}  OR={np.exp(coef):.3f}  p={p:.2e}")
    print("  (negative interaction => the two fixes are sub-additive, as injected)")


def section_power(df):
    print("\n=== 3. Power / sample size (completion) ===")
    ctrl = df[(df.progress_bar == 0) & (df.fallback == 0)]
    fb = df[(df.progress_bar == 0) & (df.fallback == 1)]
    p0, p1 = ctrl.completed.mean(), fb.completed.mean()
    n = len(ctrl)
    es = proportion_effectsize(p1, p0)
    power = NormalIndPower().power(es, nobs1=n, alpha=ALPHA, ratio=1.0, alternative="two-sided")
    mde_es = NormalIndPower().solve_power(None, nobs1=n, alpha=ALPHA, power=0.80, ratio=1.0)
    print(f"  fallback effect {p0:.3f}->{p1:.3f} (ES={es:.3f}), n/arm={n:,}")
    print(f"  achieved power for this effect: {power:.3f}")
    print(f"  MDE at 80% power (effect size h): {mde_es:.4f}")


def section_srm(df, label):
    counts = df.groupby(["progress_bar", "fallback"]).size().to_numpy()
    chi, p = chisquare(counts)  # H0: equal 25% per cell
    verdict = "FAIL (mismatch!)" if p < ALPHA else "pass"
    print(f"  {label:18s} cell counts {list(counts)}  chi2={chi:.1f} p={p:.2e}  -> {verdict}")


def section_aa(df, n_sims=2000, seed=0):
    print("\n=== 5. A/A simulation (split control in two; expect ~5% false positives) ===")
    ctrl = df[(df.progress_bar == 0) & (df.fallback == 0)]["completed"].to_numpy()
    rng = np.random.default_rng(seed)
    pvals = np.empty(n_sims)
    for i in range(n_sims):
        mask = rng.random(len(ctrl)) < 0.5
        a, b = ctrl[mask], ctrl[~mask]
        _, pvals[i] = proportions_ztest([a.sum(), b.sum()], [len(a), len(b)])
    fpr = float(np.mean(pvals < ALPHA))
    # uniformity: share of p-values in each decile should be ~0.1
    deciles = np.histogram(pvals, bins=10, range=(0, 1))[0] / n_sims
    print(f"  false-positive rate: {fpr:.3f} (target ~{ALPHA})")
    print(f"  p-value decile spread (each ~0.10): {np.round(deciles, 3).tolist()}")


def section_bh(pvals_dict):
    print("\n=== 6. Benjamini-Hochberg correction across the test suite ===")
    names = list(pvals_dict)
    raw = [pvals_dict[n] for n in names]
    rej, padj, _, _ = multipletests(raw, alpha=ALPHA, method="fdr_bh")
    for n, r, pa in zip(names, raw, padj):
        print(f"  {n:14s} raw={r:.2e}  BH-adj={pa:.2e}  {'sig' if pa < ALPHA else 'ns'}")


def section_guardrail(df):
    print("\n=== 7. Non-inferiority guardrail: default rate (fixed-horizon, one-sided) ===")
    # default rate among FUNDED loans, fallback on vs off (progress bar doesn't touch default)
    fb1 = df[(df.fallback == 1) & (df.funded == 1)]["defaulted"]
    fb0 = df[(df.fallback == 0) & (df.funded == 1)]["defaulted"]
    d1, d0 = fb1.mean(), fb0.mean()
    n1, n0 = len(fb1), len(fb0)
    diff = d1 - d0
    se = np.sqrt(d1 * (1 - d1) / n1 + d0 * (1 - d0) / n0)
    ub = diff + norm.ppf(1 - ALPHA) * se        # one-sided 95% upper bound on the increase
    non_inferior = ub < NIM
    print(f"  default(fallback)={d1:.3%}  default(control)={d0:.3%}  diff={100*diff:+.2f}pp")
    print(f"  one-sided 95% upper bound on increase: {100*ub:.2f}pp  vs NIM {100*NIM:.1f}pp")
    print(f"  -> {'NON-INFERIOR (guardrail holds)' if non_inferior else 'BREACH (do not ship)'}")
    return non_inferior


def section_fairness(df):
    print("\n=== 8. Fairness guardrail: equal benefit across credit bands (non-inferiority) ===")
    if "subgroup" not in df.columns:
        print("  (experiment.parquet has no subgroup — re-run simulate_experiment.py)")
        return True
    sub = df[df.progress_bar == 0]  # isolate the fallback effect (no UX confound)

    def rate(group, fb):
        s = sub[(sub.subgroup == group) & (sub.fallback == fb)]["completed"]
        return s.mean(), len(s)

    p_pc, n_pc = rate("Prime", 0); p_pf, n_pf = rate("Prime", 1)
    p_sc, n_sc = rate("Subprime", 0); p_sf, n_sf = rate("Subprime", 1)
    lift_prime, lift_sub = p_pf - p_pc, p_sf - p_sc
    dgap = lift_prime - lift_sub  # how much MORE the router helps prime than subprime
    se = np.sqrt(p_pc * (1 - p_pc) / n_pc + p_pf * (1 - p_pf) / n_pf
                 + p_sc * (1 - p_sc) / n_sc + p_sf * (1 - p_sf) / n_sf)
    ub = dgap + norm.ppf(1 - ALPHA) * se        # one-sided 95% upper bound on the gap
    non_inferior = ub < FAIR_NIM
    print(f"  router lift  prime {100*lift_prime:+.2f}pp | subprime {100*lift_sub:+.2f}pp")
    print(f"  prime-subprime gap {100*dgap:+.2f}pp, one-sided 95% UB {100*ub:.2f}pp  vs NIM {100*FAIR_NIM:.1f}pp")
    print(f"  -> {'NON-INFERIOR (fairness holds)' if non_inferior else 'DISPARATE IMPACT (do not ship)'}")
    return non_inferior


def main():
    df = pd.read_parquet(f"{DATA}/experiment.parquet")
    print(f"loaded experiment: {len(df):,} users, {df.progress_bar.nunique()*df.fallback.nunique()} cells")

    pvals = section_ztests(df)
    section_factorial(df)
    section_power(df)

    print("\n=== 4. Sample Ratio Mismatch (chi-square) ===")
    section_srm(df, "balanced design")
    try:
        section_srm(pd.read_parquet(f"{DATA}/experiment_srm.parquet"), "injected 80/100 A")
    except FileNotFoundError:
        print("  (experiment_srm.parquet not found — run the simulator to get the SRM demo)")

    section_aa(df)

    # BH across the completion tests + the interaction term
    m = smf.logit("completed ~ progress_bar * fallback", data=df).fit(disp=0)
    section_bh({**pvals, "interaction": m.pvalues["progress_bar:fallback"]})

    non_inferior = section_guardrail(df)
    fair_non_inferior = section_fairness(df)

    print("\n=== 9. Ship decision ===")
    primary_improves = pvals["both"] < ALPHA  # combined fix beats control on completion
    ship = primary_improves and non_inferior and fair_non_inferior
    print(f"  primary completion improves: {primary_improves}")
    print(f"  default guardrail non-inferior: {non_inferior}")
    print(f"  fairness guardrail non-inferior: {fair_non_inferior}")
    print(f"  DECISION: {'SHIP the combined fix' if ship else 'DO NOT SHIP'}")


if __name__ == "__main__":
    main()
