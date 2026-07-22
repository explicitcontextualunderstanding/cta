#!/usr/bin/env python3
"""Independent-scorer pattern for CTA metrics (Plan 9 §6, M5).

Generates a BLIND classification task: strips condition-identifying metadata
from NDJSON sessions, shuffles order, and outputs a scoring sheet. A second
scorer (human or agent) classifies each session as CLEAN or FRICTION without
knowing the true condition or FI score. Agreement with FI breaks the
co-adaptation loop (R4) and makes the "two engines" framing literally true.

Workflow:
  1. Run this script to generate the blind scoring sheet
  2. Give the sheet to an independent scorer (no access to FI or condition labels)
  3. Scorer fills in their classification for each session
  4. Run with --evaluate to compute agreement

Usage:
    # Generate blind scoring sheet
    python3 scripts/independent_scorer.py --generate

    # Evaluate completed scoring sheet
    python3 scripts/independent_scorer.py --evaluate scoring_sheet.json

Requires: numpy
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROSPECTIVE_DIR = PROJECT_ROOT / "data/m3_captures/P8-phase2-prospective"
FRICTION_DIR = PROJECT_ROOT / "data/m3_captures/P8-synthetic-friction-g3run1"
OUTPUT_DIR = PROJECT_ROOT / "data/independent_scorer"


def extract_blind_features(ndjson_path: Path) -> dict:
    """Extract features from an NDJSON session WITHOUT revealing condition.

    Strips: file path, session ID, any metadata that identifies treatment/control.
    Retains: behavioral signals a blind scorer can use (event patterns, tool usage,
    error patterns, session length).
    """
    content = ndjson_path.read_text()
    events = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue

    # Extract blind-safe features
    tool_names = []
    error_indicators = 0
    total_events = len(events)
    assistant_turns = 0
    tool_results = 0
    text_snippets = []

    for ev in events:
        ev_type = ev.get("type", "")
        if ev_type == "assistant":
            assistant_turns += 1
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    tool_names.append(block.get("name", "unknown"))
                elif block.get("type") == "text":
                    text = block.get("text", "")
                    if len(text) > 20:
                        text_snippets.append(text[:100])
        elif ev_type == "user":
            tr = ev.get("tool_use_result", {})
            if tr:
                tool_results += 1
                ec = tr.get("exitCode", 0)
                if ec != 0:
                    error_indicators += 1

    # Create anonymous session ID (hash of content, not path)
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

    return {
        "anonymous_id": f"S-{content_hash}",
        "total_events": total_events,
        "assistant_turns": assistant_turns,
        "tool_results": tool_results,
        "error_indicators": error_indicators,
        "unique_tools": len(set(tool_names)),
        "tool_sequence": tool_names[:20],  # first 20 tool calls
        "text_snippets": text_snippets[:3],  # first 3 text blocks (truncated)
        "scorer_classification": None,  # TO BE FILLED BY INDEPENDENT SCORER
        "scorer_confidence": None,  # high/medium/low
        "scorer_notes": None,
    }


def generate_scoring_sheet():
    """Generate the blind scoring sheet from all available sessions."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sessions = []

    # Clean sessions
    for path in sorted(PROSPECTIVE_DIR.glob("session_*.ndjson")):
        if path.exists():
            features = extract_blind_features(path)
            features["_true_label"] = "clean"  # hidden from scorer
            features["_source_file"] = path.name  # hidden from scorer
            sessions.append(features)

    # Friction sessions
    friction_path = FRICTION_DIR / "raw.ndjson"
    if friction_path.exists():
        features = extract_blind_features(friction_path)
        features["_true_label"] = "friction"  # hidden from scorer
        features["_source_file"] = friction_path.name  # hidden from scorer
        sessions.append(features)

    # Shuffle deterministically (seed from content hashes for reproducibility)
    rng = np.random.default_rng(2026)
    indices = rng.permutation(len(sessions))
    shuffled = [sessions[i] for i in indices]

    # Split into scorer-facing sheet (no hidden fields) and answer key
    scorer_sheet = []
    answer_key = []
    for i, s in enumerate(shuffled):
        scorer_entry = {k: v for k, v in s.items() if not k.startswith("_")}
        scorer_entry["order"] = i + 1
        scorer_sheet.append(scorer_entry)

        answer_key.append({
            "order": i + 1,
            "anonymous_id": s["anonymous_id"],
            "true_label": s["_true_label"],
            "source_file": s["_source_file"],
        })

    # Write outputs
    sheet_path = OUTPUT_DIR / "blind_scoring_sheet.json"
    key_path = OUTPUT_DIR / "answer_key.json"

    with open(sheet_path, "w") as f:
        json.dump({
            "instructions": (
                "INDEPENDENT SCORER TASK: For each session below, classify as "
                "CLEAN or FRICTION based solely on the behavioral features shown. "
                "Do NOT look at friction_index scores or condition labels. "
                "Fill in scorer_classification ('clean' or 'friction'), "
                "scorer_confidence ('high'/'medium'/'low'), and optional notes."
            ),
            "n_sessions": len(scorer_sheet),
            "sessions": scorer_sheet,
        }, f, indent=2)

    with open(key_path, "w") as f:
        json.dump({
            "note": "ANSWER KEY — DO NOT SHARE WITH SCORER until evaluation",
            "n_sessions": len(answer_key),
            "key": answer_key,
        }, f, indent=2)

    print(f"Generated blind scoring sheet: {sheet_path}")
    print(f"  {len(scorer_sheet)} sessions (shuffled, anonymized)")
    print(f"Answer key (hidden from scorer): {key_path}")
    print()
    print("Next steps:")
    print("  1. Give blind_scoring_sheet.json to an independent scorer")
    print("  2. Scorer fills in scorer_classification for each session")
    print("  3. Run: python3 scripts/independent_scorer.py --evaluate <completed_sheet>")


def evaluate_scoring(completed_sheet_path: str):
    """Evaluate a completed scoring sheet against the answer key."""
    key_path = OUTPUT_DIR / "answer_key.json"
    if not key_path.exists():
        print("ERROR: answer_key.json not found. Run --generate first.", file=sys.stderr)
        sys.exit(1)

    with open(completed_sheet_path) as f:
        sheet = json.load(f)
    with open(key_path) as f:
        key_data = json.load(f)

    key_by_id = {k["anonymous_id"]: k["true_label"] for k in key_data["key"]}

    agreements = 0
    disagreements = 0
    unfilled = 0
    results = []

    for entry in sheet["sessions"]:
        scorer_class = entry.get("scorer_classification")
        anon_id = entry["anonymous_id"]
        true_label = key_by_id.get(anon_id)

        if scorer_class is None:
            unfilled += 1
            continue

        scorer_class = scorer_class.lower().strip()
        agreed = scorer_class == true_label
        if agreed:
            agreements += 1
        else:
            disagreements += 1

        results.append({
            "anonymous_id": anon_id,
            "scorer": scorer_class,
            "true": true_label,
            "agreed": agreed,
            "confidence": entry.get("scorer_confidence", "unknown"),
        })

    total_scored = agreements + disagreements
    agreement_rate = agreements / total_scored if total_scored > 0 else 0

    print("=" * 60)
    print("INDEPENDENT SCORER EVALUATION (Plan 9 §6, M5)")
    print("=" * 60)
    print(f"  Sessions scored: {total_scored}/{len(sheet['sessions'])}")
    print(f"  Unfilled: {unfilled}")
    print(f"  Agreements: {agreements}/{total_scored} = {agreement_rate:.1%}")
    print(f"  Disagreements: {disagreements}")
    print()

    if disagreements > 0:
        print("  Disagreement details:")
        for r in results:
            if not r["agreed"]:
                print(f"    {r['anonymous_id']}: scorer={r['scorer']}, "
                      f"true={r['true']} (confidence: {r['confidence']})")
        print()

    # M5 verdict
    if total_scored == 0:
        print("  M5: NOT EVALUATED (no scores filled in)")
    elif agreement_rate >= 0.80:
        print(f"  M5: PASS ({agreement_rate:.0%} agreement). Independent scorer "
              f"confirms FI discrimination. 'Two engines' framing validated.")
    elif agreement_rate >= 0.60:
        print(f"  M5: PARTIAL ({agreement_rate:.0%} agreement). Moderate "
              f"independent confirmation. R4 concern reduced but not eliminated.")
    else:
        print(f"  M5: FAIL ({agreement_rate:.0%} agreement). Independent scorer "
              f"disagrees with FI. Co-adaptation or metric validity concern.")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="Generate blind scoring sheet")
    parser.add_argument("--evaluate", metavar="COMPLETED_SHEET",
                        help="Evaluate a completed scoring sheet")
    args = parser.parse_args()

    if args.generate:
        generate_scoring_sheet()
    elif args.evaluate:
        evaluate_scoring(args.evaluate)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
