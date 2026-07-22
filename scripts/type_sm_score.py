#!/usr/bin/env python3
"""Type S/M scoring for CTA inductive claims (Plan 9 §2-§3, M3).

Computes Type S (sign error probability) and Type M (exaggeration ratio)
for paired CPI data using a Bayesian posterior approximation.

Method: For paired designs, the treatment effect is the mean of within-pair
differences d_i = cpi_treatment[i] - cpi_control[i]. With a skeptical prior
beta1 ~ N(0, 1), the posterior is:
  posterior_mean = (prior_prec * prior_mean + data_prec * data_mean) / (prior_prec + data_prec)
  posterior_var = 1 / (prior_prec + data_prec)

Type S = P(beta1 < 0 | data) when estimate > 0 (or vice versa)
Type M = E[|beta1| / |true| | data, sign correct] ≈ |posterior_mean| / |true_effect|
  where true_effect is approximated by the posterior median (conservative).

Usage:
    python3 scripts/type_sm_score.py --treatment 1.2,1.5,0.9 --control 1.0,1.1,1.0
    python3 scripts/type_sm_score.py --json --treatment 1.2,1.5,0.9 --control 1.0,1.1,1.0

Requires: numpy (pip install numpy)
"""

import argparse
import json
import math
import sys

import numpy as np


def norm_cdf(x: float, loc: float = 0.0, scale: float = 1.0) -> float:
    """Standard Normal CDF via math.erf (no scipy needed)."""
    z = (x - loc) / scale
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def compute_type_sm(
    treatment: np.ndarray,
    control: np.ndarray,
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
) -> dict:
    """Compute Type S/M for a paired design.

    Args:
        treatment: CPI values for treatment sessions (N pairs)
        control: CPI values for control sessions (N pairs)
        prior_mean: Prior mean for treatment effect (skeptical: 0.0)
        prior_sd: Prior SD for treatment effect (weakly informative: 1.0)

    Returns:
        Dict with posterior summary, Type S, Type M, and claim label.
    """
    n = len(treatment)
    if n < 3:
        return {
            "error": f"N={n} < 3. Type S/M requires N>=3 paired observations. "
                     f"Label as [EXPLORATORY].",
            "n": n,
            "label": "[EXPLORATORY]",
        }

    differences = treatment - control
    data_mean = np.mean(differences)
    data_se = np.std(differences, ddof=1) / np.sqrt(n)

    # Bayesian update: Normal-Normal conjugate
    prior_prec = 1.0 / (prior_sd ** 2)
    data_prec = 1.0 / (data_se ** 2) if data_se > 0 else 1e10

    post_prec = prior_prec + data_prec
    post_mean = (prior_prec * prior_mean + data_prec * data_mean) / post_prec
    post_sd = np.sqrt(1.0 / post_prec)

    # 95% Credible Interval
    cri_low = post_mean - 1.96 * post_sd
    cri_high = post_mean + 1.96 * post_sd

    # Type S: probability the sign is wrong
    if post_mean > 0:
        type_s = norm_cdf(0, loc=post_mean, scale=post_sd)
    elif post_mean < 0:
        type_s = 1.0 - norm_cdf(0, loc=post_mean, scale=post_sd)
    else:
        type_s = 0.5

    # Type M: expected exaggeration ratio
    # E[|estimate| / |true|] approximated via posterior simulation
    n_sim = 100000
    posterior_samples = np.random.default_rng(42).normal(post_mean, post_sd, n_sim)

    # Conditional on sign being correct
    if post_mean > 0:
        correct_sign_samples = posterior_samples[posterior_samples > 0]
    else:
        correct_sign_samples = posterior_samples[posterior_samples < 0]

    if len(correct_sign_samples) > 0:
        # Type M = E[|estimate|] / |true_effect|
        # Use posterior median as "true effect" (conservative)
        true_effect = abs(np.median(correct_sign_samples))
        expected_abs = np.mean(np.abs(correct_sign_samples))
        type_m = expected_abs / true_effect if true_effect > 0 else float("inf")
    else:
        type_m = float("inf")

    # Claim label based on thresholds (Plan 9 §10)
    if type_s > 0.10:
        label = "[EXPLORATORY]"
        verdict = "SIGN UNCERTAIN — effect may be zero or reversed"
    elif type_m > 2.0:
        label = "[INDUCTIVE — EXAGGERATED]"
        verdict = "Direction likely correct but magnitude overstated (>2x)"
    else:
        label = "[INDUCTIVE]"
        verdict = "Direction and magnitude reasonably estimated"

    return {
        "n": n,
        "data_mean_diff": round(float(data_mean), 4),
        "data_se": round(float(data_se), 4),
        "posterior_mean": round(float(post_mean), 4),
        "posterior_sd": round(float(post_sd), 4),
        "posterior_median": round(float(post_mean), 4),  # Normal → mean=median
        "cri_95": [round(float(cri_low), 4), round(float(cri_high), 4)],
        "type_s": round(float(type_s), 4),
        "type_s_pct": f"{type_s * 100:.1f}%",
        "type_m": round(float(type_m), 3),
        "label": label,
        "verdict": verdict,
        "prior": f"N({prior_mean}, {prior_sd})",
        "model": "paired-difference, Normal-Normal conjugate (Plan 9 §3 minimal)",
        "differences": [round(float(d), 4) for d in differences],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--treatment", required=True,
                        help="Comma-separated CPI treatment values")
    parser.add_argument("--control", required=True,
                        help="Comma-separated CPI control values")
    parser.add_argument("--prior-mean", type=float, default=0.0,
                        help="Prior mean for effect (default: 0.0, skeptical)")
    parser.add_argument("--prior-sd", type=float, default=1.0,
                        help="Prior SD for effect (default: 1.0)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    treatment = np.array([float(x) for x in args.treatment.split(",")])
    control = np.array([float(x) for x in args.control.split(",")])

    if len(treatment) != len(control):
        print(f"ERROR: treatment (N={len(treatment)}) != control (N={len(control)})",
              file=sys.stderr)
        sys.exit(1)

    result = compute_type_sm(treatment, control, args.prior_mean, args.prior_sd)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 60)
        print("TYPE S/M ANALYSIS (Plan 9 §2-§3)")
        print("=" * 60)
        print(f"  N pairs: {result['n']}")
        print(f"  Model: {result.get('model', 'N/A')}")
        print(f"  Prior: {result.get('prior', 'N/A')}")
        print()

        if "error" in result:
            print(f"  ERROR: {result['error']}")
            print(f"  Label: {result['label']}")
            return

        print(f"  Within-pair differences: {result['differences']}")
        print(f"  Mean difference: {result['data_mean_diff']} (SE: {result['data_se']})")
        print()
        print(f"  Posterior: {result['posterior_mean']} "
              f"(95% CrI: [{result['cri_95'][0]}, {result['cri_95'][1]}])")
        print()
        print(f"  Type S (sign error): {result['type_s_pct']}")
        print(f"  Type M (exaggeration): {result['type_m']}x")
        print()
        print(f"  Label: {result['label']}")
        print(f"  Verdict: {result['verdict']}")
        print("=" * 60)


if __name__ == "__main__":
    main()
