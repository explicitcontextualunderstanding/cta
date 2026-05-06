#!/usr/bin/env python3
"""Compute every number / table cited in the paper draft.

Reads:
  - config/cta_task_metadata.json
  - cta_output/cta_analysis_<task>_<ts>.json (latest per task)

Writes:
  - draft/paper_stats.json  (machine-readable)
  - draft/tab_stratified.tex  (LaTeX table cited as Table~\ref{tab:stratified})
  - draft/tab_sips.tex         (LaTeX table cited as Table~\ref{tab:sip-distribution})
  - draft/tab_topdelta.tex     (LaTeX table cited as Table~\ref{tab:top-delta})

Print a human summary to stdout so the numbers can be eyeballed.
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Dict, Tuple

ROOT = Path(__file__).resolve().parent.parent
META_FILE = ROOT / "config/cta_task_metadata.json"
ANALYSIS_DIR = ROOT / "cta_output"
DRAFT_DIR = ROOT / "draft"
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

ANALYSIS_FNAME = re.compile(r"cta_analysis_(.+)_(\d{8}_\d{6})\.json")

SIP_ORDER = [
    ("procedural_scaffolding", "PS", "constructive"),
    ("edge_case_prompting", "EP", "constructive"),
    ("redundant_exploration", "RE", "neutral"),
    ("surface_anchoring", "SA", "destructive"),
    ("concept_bleed", "CB", "destructive"),
]

DIV_ORDER = ["target_mismatch", "content_mismatch", "unilateral_action"]


def bucket_of(baseline: float) -> str:
    if baseline >= 0.9:
        return "ceiling"
    if baseline >= 0.5:
        return "mid"
    return "floor"


def load_latest_analyses() -> Dict[str, Path]:
    latest: Dict[str, Tuple[str, Path]] = {}
    for f in glob.glob(str(ANALYSIS_DIR / "cta_analysis_*.json")):
        m = ANALYSIS_FNAME.match(os.path.basename(f))
        if not m:
            continue
        tid, ts = m.group(1), m.group(2)
        if tid not in latest or ts > latest[tid][0]:
            latest[tid] = (ts, Path(f))
    return {k: v[1] for k, v in latest.items()}


def fmt_pct_signed(x: float) -> str:
    """Format a pass-rate delta in percentage points (pp).

    The paper draft (\S6.1 \"Notation\") fixes the convention that $\\Delta P$
    is reported in pp rather than %, since it is a difference of two pass
    rates rather than a relative change. The trailing ``\\,pp`` keeps the
    LaTeX rendering tight (thin space between the number and the unit).
    """
    return f"{x*100:+.1f}\\,pp"


def write_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def main() -> None:
    metadata = json.load(open(META_FILE))
    evaluated = {tid: v for tid, v in metadata.items() if v.get("pass_rate_source") == "eval_report"}
    analyses = load_latest_analyses()

    # Per-task bucket
    t2bk = {tid: bucket_of(v["baseline_pass_rate"]) for tid, v in evaluated.items()}

    # Aggregate counters
    bk_n = collections.Counter()
    bk_div_total = collections.Counter()
    bk_div_type = collections.defaultdict(collections.Counter)
    bk_div_phase = collections.defaultdict(collections.Counter)
    bk_sip_total = collections.Counter()
    bk_sip_type = collections.defaultdict(collections.Counter)
    bk_dp = collections.defaultdict(list)
    bk_tok = collections.defaultdict(list)
    bk_skill_sim = collections.defaultdict(list)
    bk_avg_conf = collections.defaultdict(list)

    overall_div_phase = collections.Counter()
    overall_div_type = collections.Counter()
    overall_sip_type = collections.Counter()

    for tid in sorted(evaluated):
        bk = t2bk[tid]
        bk_n[bk] += 1
        analysis_path = analyses.get(tid)
        if analysis_path is None:
            continue
        d = json.load(open(analysis_path))
        align = d["modules"]["alignment"]["divergence_statistics"]
        sip_stats = d["modules"]["sip_detection"]["sip_statistics"]

        bk_div_total[bk] += align.get("total_divergences", 0)
        for k, v in align.get("by_type", {}).items():
            bk_div_type[bk][k] += v
            overall_div_type[k] += v
        for k, v in align.get("by_phase", {}).items():
            bk_div_phase[bk][k] += v
            overall_div_phase[k] += v
        if "avg_skill_similarity" in align:
            bk_skill_sim[bk].append(align["avg_skill_similarity"])

        bk_sip_total[bk] += sip_stats.get("total_sips", 0)
        for k, v in sip_stats.get("by_type", {}).items():
            bk_sip_type[bk][k] += v["count"]
            overall_sip_type[k] += v["count"]
        if "avg_confidence" in sip_stats:
            bk_avg_conf[bk].append(sip_stats["avg_confidence"])

        bk_dp[bk].append(evaluated[tid]["pass_rate_delta"])
        bk_tok[bk].append(evaluated[tid]["token_overhead_ratio"])

    n_tasks = sum(bk_n.values())
    overall_dp = [v["pass_rate_delta"] for v in evaluated.values()]
    overall_tok = [v["token_overhead_ratio"] for v in evaluated.values()]

    # ===== Print human summary =====
    print(f"Tasks evaluated: {n_tasks}")
    print(f"Overall mean ΔP: {mean(overall_dp):+.4f}  (median {median(overall_dp):+.4f}, sd {pstdev(overall_dp):.4f})")
    print(f"Overall mean baseline pass rate: {mean(v['baseline_pass_rate'] for v in evaluated.values()):.4f}")
    print(f"Overall mean token overhead: {mean(overall_tok):.2f}x")
    print(f"Total divergences: {sum(bk_div_total.values())} | per-task mean: {sum(bk_div_total.values())/max(n_tasks,1):.1f}")
    print(f"Total SIPs: {sum(bk_sip_total.values())} | per-task mean: {sum(bk_sip_total.values())/max(n_tasks,1):.1f}")
    print()
    print("By bucket:")
    print(f"{'bk':<10}{'n':<4}{'mean ΔP':<11}{'div':<6}{'SIP':<6}{'tok×':<8}")
    for bk in ["ceiling", "mid", "floor"]:
        n = bk_n[bk]
        if n == 0:
            continue
        print(
            f"{bk:<10}{n:<4}"
            f"{mean(bk_dp[bk]):+.4f}    "
            f"{bk_div_total[bk]:<6}"
            f"{bk_sip_total[bk]:<6}"
            f"{mean(bk_tok[bk]):.2f}"
        )
    print()
    print("SIP per-task averages by bucket:")
    print(f"{'bk':<10}" + "".join(f"{abbr:>6}" for _, abbr, _ in SIP_ORDER))
    for bk in ["ceiling", "mid", "floor"]:
        n = bk_n[bk]
        if n == 0:
            continue
        line = f"{bk:<10}"
        for key, abbr, _ in SIP_ORDER:
            line += f"{bk_sip_type[bk][key]/n:>6.2f}"
        print(line)
    print()
    print("Divergence by phase (overall):")
    total_phase = sum(overall_div_phase.values())
    for k, v in overall_div_phase.most_common():
        print(f"  {k:<14} {v:>4} ({v/total_phase:.0%})")

    # ===== Write JSON =====
    stats = {
        "n_tasks": n_tasks,
        "model": "claude-sonnet-4-5-20250929",
        "n_reps": 1,
        "overall": {
            "mean_pass_rate_delta": mean(overall_dp),
            "median_pass_rate_delta": median(overall_dp),
            "sd_pass_rate_delta": pstdev(overall_dp),
            "mean_baseline_pass_rate": mean(v["baseline_pass_rate"] for v in evaluated.values()),
            "mean_token_overhead": mean(overall_tok),
            "total_divergences": sum(bk_div_total.values()),
            "total_sips": sum(bk_sip_total.values()),
            "divergences_per_task": sum(bk_div_total.values()) / max(n_tasks, 1),
            "sips_per_task": sum(bk_sip_total.values()) / max(n_tasks, 1),
            "divergence_by_type": dict(overall_div_type),
            "divergence_by_phase": dict(overall_div_phase),
            "sip_by_type": dict(overall_sip_type),
        },
        "by_bucket": {
            bk: {
                "n_tasks": bk_n[bk],
                "mean_pass_rate_delta": mean(bk_dp[bk]) if bk_n[bk] else None,
                "mean_token_overhead": mean(bk_tok[bk]) if bk_n[bk] else None,
                "total_divergences": bk_div_total[bk],
                "total_sips": bk_sip_total[bk],
                "divergences_per_task": bk_div_total[bk] / bk_n[bk] if bk_n[bk] else None,
                "sips_per_task": bk_sip_total[bk] / bk_n[bk] if bk_n[bk] else None,
                "divergence_by_type": dict(bk_div_type[bk]),
                "divergence_by_phase": dict(bk_div_phase[bk]),
                "sip_by_type": dict(bk_sip_type[bk]),
                "mean_skill_similarity": mean(bk_skill_sim[bk]) if bk_skill_sim[bk] else None,
                "mean_sip_confidence": mean(bk_avg_conf[bk]) if bk_avg_conf[bk] else None,
            }
            for bk in ["ceiling", "mid", "floor"]
            if bk_n[bk]
        },
    }
    write_json(stats, DRAFT_DIR / "paper_stats.json")
    print(f"\nwrote {DRAFT_DIR/'paper_stats.json'}")

    # ===== Stratified table =====
    lines = [
        r"% Auto-generated by scripts/cta_paper_stats.py — do not edit by hand.",
        r"\begin{tabular}{lrrrrrrrr}",
        r"\toprule",
        r" & $n$ & Baseline & $\Delta P$ & Tok.\,$\times$ & \#Div & \#SIP & \#Div/task & \#SIP/task \\",
        r"\midrule",
    ]
    for bk in ["ceiling", "mid", "floor"]:
        n = bk_n[bk]
        if n == 0:
            continue
        baselines = [evaluated[tid]["baseline_pass_rate"] for tid in evaluated if t2bk[tid] == bk]
        lines.append(
            f"{bk.capitalize():<8} ($\\geq 0.9$)" if bk == "ceiling"
            else (f"{bk.capitalize():<8} ($0.5\\!-\\!0.9$)" if bk == "mid"
                  else f"{bk.capitalize():<8} ($<0.5$)")
        )
        line_body = (
            f" & {n} & {mean(baselines):.2f} & {fmt_pct_signed(mean(bk_dp[bk]))}"
            f" & {mean(bk_tok[bk]):.2f}"
            f" & {bk_div_total[bk]} & {bk_sip_total[bk]}"
            f" & {bk_div_total[bk]/n:.1f} & {bk_sip_total[bk]/n:.1f} \\\\"
        )
        lines[-1] = lines[-1] + line_body
    lines.append(r"\midrule")
    lines.append(
        f"All & {n_tasks} & {mean(v['baseline_pass_rate'] for v in evaluated.values()):.2f}"
        f" & {fmt_pct_signed(mean(overall_dp))}"
        f" & {mean(overall_tok):.2f}"
        f" & {sum(bk_div_total.values())} & {sum(bk_sip_total.values())}"
        f" & {sum(bk_div_total.values())/n_tasks:.1f} & {sum(bk_sip_total.values())/n_tasks:.1f} \\\\"
    )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    (DRAFT_DIR / "tab_stratified.tex").write_text("\n".join(lines) + "\n")
    print(f"wrote {DRAFT_DIR/'tab_stratified.tex'}")

    # ===== SIP per-task table =====
    sip_lines = [
        r"% Auto-generated by scripts/cta_paper_stats.py.",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r" & PS & EP & RE & SA & CB \\",
        r" & (constr.) & (constr.) & (neutral) & (destr.) & (destr.) \\",
        r"\midrule",
    ]
    for bk in ["ceiling", "mid", "floor"]:
        n = bk_n[bk]
        if n == 0:
            continue
        cells = []
        for key, _, _ in SIP_ORDER:
            cells.append(f"{bk_sip_type[bk][key]/n:.2f}")
        sip_lines.append(f"{bk.capitalize()} ($n={n}$) & " + " & ".join(cells) + r" \\")
    # All
    cells = []
    for key, _, _ in SIP_ORDER:
        cells.append(f"{overall_sip_type[key]/n_tasks:.2f}")
    sip_lines.append(r"\midrule")
    sip_lines.append(f"All ($n={n_tasks}$) & " + " & ".join(cells) + r" \\")
    sip_lines += [r"\bottomrule", r"\end{tabular}"]
    (DRAFT_DIR / "tab_sips.tex").write_text("\n".join(sip_lines) + "\n")
    print(f"wrote {DRAFT_DIR/'tab_sips.tex'}")

    # ===== Top |ΔP| table =====
    top = sorted(evaluated.values(), key=lambda v: -abs(v["pass_rate_delta"]))[:6]
    top_lines = [
        r"% Auto-generated by scripts/cta_paper_stats.py.",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Task & Baseline & With-skill & $\Delta P$ & Tok.\,$\times$ \\",
        r"\midrule",
    ]
    for v in top:
        tid = v["skill_id"].replace("_", "\\_")
        top_lines.append(
            f"\\texttt{{{tid}}} & {v['baseline_pass_rate']:.2f} & {v['with_skill_pass_rate']:.2f}"
            f" & {fmt_pct_signed(v['pass_rate_delta'])} & {v['token_overhead_ratio']:.2f} \\\\"
        )
    top_lines += [r"\bottomrule", r"\end{tabular}"]
    (DRAFT_DIR / "tab_topdelta.tex").write_text("\n".join(top_lines) + "\n")
    print(f"wrote {DRAFT_DIR/'tab_topdelta.tex'}")


if __name__ == "__main__":
    main()
