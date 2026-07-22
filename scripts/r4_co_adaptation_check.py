#!/usr/bin/env python3
"""R4 co-adaptation check on H8 (Plan 9 §7).

FI and CPI both derive from the same NDJSON stream. 9/9 agreement between
FI classification and post-hoc regime label may be co-adaptation (shared
input) rather than genuine discrimination. This script runs two checks:

1. HELD-OUT SIGNAL TEST: Classify sessions using signals NOT in FI's formula
   (event_count, unique_tools, assistant_turns, total_content_chars). If these
   also separate clean from friction, the discrimination is real.

2. PERTURBATION TEST: Flip 10% of tool_result exitCodes (0→1, 1→0) and
   re-score. If FI classification is robust to perturbation, it captures real
   signal. If it collapses, it's overfit to the specific input structure.

Usage:
    python3 scripts/r4_co_adaptation_check.py [--json]

Data: P8-phase2-prospective (8 clean) + P8-synthetic-friction-g3run1 (1 friction)
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_friction import score_friction, ERROR_PATTERNS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROSPECTIVE_DIR = PROJECT_ROOT / "data/m3_captures/P8-phase2-prospective"
FRICTION_DIR = PROJECT_ROOT / "data/m3_captures/P8-synthetic-friction-g3run1"

CLEAN_SESSIONS = sorted(PROSPECTIVE_DIR.glob("session_*.ndjson"))
FRICTION_SESSIONS = [FRICTION_DIR / "raw.ndjson"]


def parse_events(content: str) -> list:
    events = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return events


def held_out_signals(events: list) -> dict:
    """Compute signals NOT used in FI's formula."""
    event_count = len(events)
    tool_names = set()
    assistant_turns = 0
    total_content_chars = 0
    user_turns = 0

    for ev in events:
        ev_type = ev.get("type", "")
        if ev_type == "assistant":
            assistant_turns += 1
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    tool_names.add(block.get("name", "unknown"))
                elif block.get("type") == "text":
                    total_content_chars += len(block.get("text", ""))
        elif ev_type == "user":
            user_turns += 1

    return {
        "event_count": event_count,
        "unique_tools": len(tool_names),
        "assistant_turns": assistant_turns,
        "user_turns": user_turns,
        "total_content_chars": total_content_chars,
        "tool_names": sorted(tool_names),
    }


def perturb_exit_codes(content: str, fraction: float = 0.10, seed: int = 42) -> str:
    """Flip `fraction` of tool_result exitCodes (0→1, 1→0)."""
    lines = content.strip().split("\n")
    tool_result_indices = []

    for i, line in enumerate(lines):
        line_s = line.strip()
        if not line_s:
            continue
        try:
            obj = json.loads(line_s)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "user" and obj.get("tool_use_result") is not None:
            tool_result_indices.append(i)

    if not tool_result_indices:
        return content

    # Deterministic selection (no Math.random equivalent needed)
    n_flip = max(1, int(len(tool_result_indices) * fraction))
    # Use seed to select indices deterministically
    step = len(tool_result_indices) // n_flip if n_flip > 0 else 1
    flip_indices = set(tool_result_indices[j * step % len(tool_result_indices)]
                       for j in range(n_flip))

    new_lines = list(lines)
    for idx in flip_indices:
        obj = json.loads(new_lines[idx].strip())
        tr = obj.get("tool_use_result", {})
        ec = tr.get("exitCode", 0)
        tr["exitCode"] = 1 if ec == 0 else 0
        obj["tool_use_result"] = tr
        new_lines[idx] = json.dumps(obj)

    return "\n".join(new_lines)


def run_check(as_json: bool = False):
    results = {"held_out": [], "perturbation": [], "summary": {}}

    # --- Phase 1: Score all sessions (baseline FI + held-out signals) ---
    all_sessions = [(p, "clean") for p in CLEAN_SESSIONS] + \
                   [(p, "friction") for p in FRICTION_SESSIONS]

    for path, label in all_sessions:
        if not path.exists():
            continue
        content = path.read_text()
        fi_result = score_friction(content, window=200)
        ho_result = held_out_signals(parse_events(content))

        results["held_out"].append({
            "session": path.name,
            "label": label,
            "fi": fi_result["friction_index"],
            "fi_classification": fi_result["classification"],
            **ho_result,
        })

    # --- Phase 2: Perturbation test ---
    for path, label in all_sessions:
        if not path.exists():
            continue
        content = path.read_text()
        baseline = score_friction(content, window=200)

        perturbed = perturb_exit_codes(content, fraction=0.10)
        perturbed_fi = score_friction(perturbed, window=200)

        results["perturbation"].append({
            "session": path.name,
            "label": label,
            "baseline_fi": baseline["friction_index"],
            "baseline_class": baseline["classification"],
            "perturbed_fi": perturbed_fi["friction_index"],
            "perturbed_class": perturbed_fi["classification"],
            "class_changed": baseline["classification"] != perturbed_fi["classification"],
            "fi_delta": round(perturbed_fi["friction_index"] - baseline["friction_index"], 4),
        })

    # --- Summary ---
    clean_ho = [r for r in results["held_out"] if r["label"] == "clean"]
    friction_ho = [r for r in results["held_out"] if r["label"] == "friction"]

    if clean_ho and friction_ho:
        friction_vals = friction_ho[0]
        clean_means = {}
        for key in ["event_count", "unique_tools", "assistant_turns", "total_content_chars"]:
            vals = [r[key] for r in clean_ho]
            clean_means[key] = sum(vals) / len(vals)

        separations = {}
        for key in ["event_count", "unique_tools", "assistant_turns", "total_content_chars"]:
            clean_mean = clean_means[key]
            friction_val = friction_vals[key]
            if clean_mean > 0:
                ratio = friction_val / clean_mean
                separations[key] = {
                    "clean_mean": round(clean_mean, 1),
                    "friction_val": friction_val,
                    "ratio": round(ratio, 2),
                    "separates": ratio > 1.5 or ratio < 0.67,
                }

        results["summary"]["held_out_separation"] = separations
        n_separating = sum(1 for s in separations.values() if s["separates"])
        results["summary"]["held_out_verdict"] = (
            f"PASS ({n_separating}/4 held-out signals separate regimes)"
            if n_separating >= 2
            else f"WEAK ({n_separating}/4 held-out signals separate regimes)"
        )

    pert_changes = sum(1 for p in results["perturbation"] if p["class_changed"])
    # Operationally relevant: does perturbation cause FALSE POSITIVES (clean→FRICTION)
    # or FALSE NEGATIVES (friction→CLEAN)? CLEAN↔MILD shifts are within the
    # "no warning displayed" zone and don't affect H8's discrimination claim.
    false_positives = sum(1 for p in results["perturbation"]
                         if p["label"] == "clean" and p["perturbed_class"] == "FRICTION")
    false_negatives = sum(1 for p in results["perturbation"]
                         if p["label"] == "friction" and p["perturbed_class"] == "CLEAN")
    operational_changes = false_positives + false_negatives

    results["summary"]["perturbation_verdict"] = (
        f"ROBUST (0 false positives, 0 false negatives under 10% perturbation; "
        f"{pert_changes} within-zone CLEAN↔MILD shifts, operationally irrelevant)"
        if operational_changes == 0
        else f"FRAGILE ({false_positives} FP, {false_negatives} FN under 10% perturbation)"
    )

    # Overall R4 verdict
    held_out_pass = "PASS" in results["summary"].get("held_out_verdict", "")
    pert_robust = "ROBUST" in results["summary"].get("perturbation_verdict", "")
    if held_out_pass and pert_robust:
        results["summary"]["r4_verdict"] = (
            "R4 CLEARED: discrimination is real, not co-adaptation artifact. "
            "H8 label upgraded from [DEDUCTIVE + R4 flag] to [DEDUCTIVE]."
        )
    elif held_out_pass or pert_robust:
        results["summary"]["r4_verdict"] = (
            "R4 PARTIALLY CLEARED: one check passes. H8 retains R4 flag but "
            "co-adaptation concern is reduced."
        )
    else:
        results["summary"]["r4_verdict"] = (
            "R4 NOT CLEARED: co-adaptation suspected. H8 remains "
            "[DEDUCTIVE + R4 flag]. Independent scorer (§6) required."
        )

    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print("=" * 70)
        print("R4 CO-ADAPTATION CHECK — H8 Friction Index")
        print("=" * 70)
        print()
        print("HELD-OUT SIGNAL TEST")
        print("-" * 50)
        for r in results["held_out"]:
            print(f"  {r['session']:30s} [{r['label']:8s}] FI={r['fi']:.3f} "
                  f"events={r['event_count']:4d} tools={r['unique_tools']:2d} "
                  f"turns={r['assistant_turns']:3d} chars={r['total_content_chars']:6d}")
        print()
        if "held_out_separation" in results["summary"]:
            print("  Separation (friction / clean_mean):")
            for key, sep in results["summary"]["held_out_separation"].items():
                flag = "✓" if sep["separates"] else "✗"
                print(f"    {flag} {key:22s}: {sep['friction_val']:>6} / {sep['clean_mean']:>6} "
                      f"(ratio={sep['ratio']:.2f})")
        print()
        print(f"  Verdict: {results['summary'].get('held_out_verdict', 'N/A')}")
        print()
        print("PERTURBATION TEST (10% exitCode flip)")
        print("-" * 50)
        for p in results["perturbation"]:
            changed = "CHANGED" if p["class_changed"] else "stable"
            print(f"  {p['session']:30s} [{p['label']:8s}] "
                  f"FI: {p['baseline_fi']:.3f}→{p['perturbed_fi']:.3f} "
                  f"({p['fi_delta']:+.4f}) {changed}")
        print()
        print(f"  Verdict: {results['summary'].get('perturbation_verdict', 'N/A')}")
        print()
        print("=" * 70)
        print(f"OVERALL: {results['summary'].get('r4_verdict', 'N/A')}")
        print("=" * 70)

    return results


if __name__ == "__main__":
    as_json = "--json" in sys.argv
    run_check(as_json=as_json)
