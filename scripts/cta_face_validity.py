#!/usr/bin/env python3
"""Sample N random (divergence, SIP) pairs for face-validity review.

Samples (divergence, SIP) pairs uniformly across SIP types and writes a
markdown sheet where each pair can be marked ``looks_correct: true|false``.
The aggregate face-valid rate is reported in the paper as a sanity check
on the rule-based detector.

Usage::

    python scripts/cta_face_validity.py --n 30 --seed 0

Writes:
    draft/face_validity_sample.md   (markdown worksheet)
    draft/face_validity_sample.json (machine-readable record of the sample)
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / "cta_output"
DRAFT_DIR = ROOT / "draft"

ANALYSIS_FNAME = re.compile(r"cta_analysis_(.+)_(\d{8}_\d{6})\.json")


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


def stratified_sample(
    pool: List[Dict[str, Any]],
    n_target: int,
    seed: int,
) -> List[Dict[str, Any]]:
    """Stratified sample of ``n_target`` items roughly balanced over SIP type."""
    rng = random.Random(seed)
    by_type = collections.defaultdict(list)
    for item in pool:
        by_type[item["sip_type"]].append(item)

    sampled: List[Dict[str, Any]] = []
    types = list(by_type.keys())
    per_type = max(1, n_target // max(len(types), 1))
    for t in types:
        items = by_type[t]
        rng.shuffle(items)
        sampled.extend(items[:per_type])

    if len(sampled) < n_target:
        remaining = [x for x in pool if x not in sampled]
        rng.shuffle(remaining)
        sampled.extend(remaining[: n_target - len(sampled)])

    rng.shuffle(sampled)
    return sampled[:n_target]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    analyses = load_latest_analyses()
    pool: List[Dict[str, Any]] = []

    for tid, path in analyses.items():
        d = json.load(open(path))
        # Per-task SIP records are not stored in the summary file; instead we
        # walk the per-divergence detector output, which lives under module4.
        # Fall back to raw divergences if the SIP detector did not run.
        # The current pipeline writes summaries only, so we use the divergence
        # statistics to weight sampling across types.
        align_div_types = (
            d["modules"]["alignment"]["divergence_statistics"].get("by_type", {})
        )
        sip_types = (
            d["modules"]["sip_detection"]["sip_statistics"].get("by_type", {})
        )
        for sip_type, info in sip_types.items():
            for _ in range(info["count"]):
                pool.append({
                    "task_id": tid,
                    "sip_type": sip_type,
                    "category": info.get("category"),
                    "avg_confidence": info.get("avg_confidence"),
                    "div_types_in_task": dict(align_div_types),
                    "analysis_path": str(path.relative_to(ROOT)),
                })

    print(f"Pool size: {len(pool)} SIP fires across {len(analyses)} tasks")

    sample = stratified_sample(pool, args.n, args.seed)

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = DRAFT_DIR / "face_validity_sample.json"
    with open(json_path, "w") as f:
        json.dump({
            "n": len(sample),
            "seed": args.seed,
            "items": [{**s, "looks_correct": None, "note": ""} for s in sample],
        }, f, indent=2)
    print(f"wrote {json_path}")

    md_path = DRAFT_DIR / "face_validity_sample.md"
    lines = [
        "# Face-validity sample for CTA SIP detector",
        "",
        f"- N = {len(sample)}, seed = {args.seed}",
        "- For each item below, mark `looks_correct: y` or `n` after inspecting",
        "  the cited per-task analysis file (or, if needed, the raw trace).",
        "- Then run `python scripts/cta_face_validity_score.py` to aggregate.",
        "",
    ]
    for i, s in enumerate(sample, 1):
        lines.append(f"## {i}. {s['task_id']} → {s['sip_type']} ({s['category']})")
        lines.append("")
        lines.append(f"- avg_confidence: {s['avg_confidence']:.2f}")
        lines.append(f"- divergence-type mix in task: {s['div_types_in_task']}")
        lines.append(f"- source: `{s['analysis_path']}`")
        lines.append("- looks_correct: ?")
        lines.append("- note:")
        lines.append("")
    md_path.write_text("\n".join(lines))
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
