#!/usr/bin/env python3
"""G1 go/no-go probe: validate the Hermes -> CTA adapter on real sessions.

Runs hermes_session_to_trace over recent Hermes CLI sessions and asserts the
gate criteria:
    - zero events with a None EventType
    - zero unmapped tool names (every tool landed on an explicit EventType)
    - at least one event produced

Usage:
    python -m scripts.g1_probe [session_glob]
    python scripts/g1_probe.py [session_glob]
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.hermes_adapter import (  # noqa: E402
    hermes_session_to_trace,
    evaluate_gate,
)


DEFAULT_GLOB = os.path.expanduser("~/.hermes/sessions/session_*.json")


def main(argv: list) -> int:
    pattern = argv[1] if len(argv) > 1 else DEFAULT_GLOB
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:120]
    if not files:
        print(f"no session files matched: {pattern}")
        return 2

    reports = []
    skipped = 0
    for path in files:
        try:
            with open(path) as f:
                session = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        _, report = hermes_session_to_trace(session)
        if report["event_count"] > 0:
            reports.append(report)

    print(f"sessions matched: {len(files)}  parsed-with-events: {len(reports)}  skipped: {skipped}")
    print()

    # Per-tool mapping coverage across the corpus.
    agg_counts: dict = {}
    for r in reports:
        for tool, n in r["tool_counts"].items():
            agg_counts[tool] = agg_counts.get(tool, 0) + n
    print("tool -> event count (corpus aggregate):")
    for tool, n in sorted(agg_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {tool}")
    print()

    gate = evaluate_gate(reports)
    print("G1 GATE VERDICT")
    print(f"  passed:            {gate['passed']}")
    print(f"  total events:      {gate['total_events']}")
    print(f"  none-type events:  {gate['total_none_events']}")
    print(f"  unmapped tools:    {gate['unmapped_tools'] or 'none'}")

    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
