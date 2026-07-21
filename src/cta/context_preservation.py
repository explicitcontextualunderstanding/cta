"""Context Window Preservation Index (CPI).

Measures how much context window consumption is offloaded to a subagent
by delegation. Higher CPI = more work done outside the primary context.

CPI = estimated_baseline_tokens / estimated_treatment_primary_tokens

A CPI of 3.0 means the baseline consumed 3x the context that the treatment
needed for equivalent work — the skill offloaded 2/3 of the context burden.

Usage:
    python -m cta.context_preservation treatment.db baseline.db
    python -m cta.context_preservation data/m3_captures/ --pair-by-task
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CHARS_PER_TOKEN = 4


def estimate_tokens(content: str) -> int:
    return max(1, len(content) // CHARS_PER_TOKEN)


def load_token_profile(db_path: Path) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    row = cur.execute("SELECT id, model FROM sessions LIMIT 1").fetchone()
    if not row:
        conn.close()
        return {}
    session_id = row["id"]

    rows = cur.execute(
        """SELECT role, content, tool_calls, token_count, reasoning, reasoning_content
           FROM messages WHERE session_id=? AND active=1 AND compacted=0 ORDER BY id""",
        (session_id,),
    ).fetchall()
    conn.close()

    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    has_native_counts = False
    message_count = len(rows)

    for r in rows:
        if r["token_count"] is not None:
            has_native_counts = True
            total_tokens += r["token_count"]
            if r["role"] == "assistant":
                output_tokens += r["token_count"]
            else:
                input_tokens += r["token_count"]
        else:
            content = r["content"] or ""
            reasoning = r["reasoning"] or r["reasoning_content"] or ""
            tool_calls = r["tool_calls"] or ""
            msg_tokens = estimate_tokens(content) + estimate_tokens(reasoning) + estimate_tokens(tool_calls)
            total_tokens += msg_tokens
            if r["role"] == "assistant":
                output_tokens += msg_tokens
                reasoning_tokens += estimate_tokens(reasoning)
            else:
                input_tokens += msg_tokens

    return {
        "session_id": session_id,
        "model": row["model"],
        "message_count": message_count,
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "native_counts": has_native_counts,
    }


def compute_cpi(treatment_profile: Dict[str, Any], baseline_profile: Dict[str, Any]) -> Dict[str, Any]:
    t_total = treatment_profile["total_tokens"]
    b_total = baseline_profile["total_tokens"]

    cpi = b_total / t_total if t_total > 0 else float("inf")

    t_input = treatment_profile["input_tokens"]
    b_input = baseline_profile["input_tokens"]
    input_cpi = b_input / t_input if t_input > 0 else float("inf")

    context_saved = max(0, b_total - t_total)
    offload_ratio = context_saved / b_total if b_total > 0 else 0.0

    return {
        "cpi": round(cpi, 3),
        "input_cpi": round(input_cpi, 3),
        "context_saved_tokens": context_saved,
        "offload_ratio": round(offload_ratio, 3),
        "treatment_total_tokens": t_total,
        "baseline_total_tokens": b_total,
        "treatment_messages": treatment_profile["message_count"],
        "baseline_messages": baseline_profile["message_count"],
        "treatment_reasoning_tokens": treatment_profile["reasoning_tokens"],
        "baseline_reasoning_tokens": baseline_profile["reasoning_tokens"],
        "native_token_counts": treatment_profile["native_counts"],
        "estimation_method": "native" if treatment_profile["native_counts"] else f"chars/{CHARS_PER_TOKEN}",
    }


def score_pair(treatment_db: Path, baseline_db: Path) -> Dict[str, Any]:
    t_profile = load_token_profile(treatment_db)
    b_profile = load_token_profile(baseline_db)

    if not t_profile or not b_profile:
        return {"error": "empty session", "treatment": str(treatment_db), "baseline": str(baseline_db)}

    result = compute_cpi(t_profile, b_profile)
    result["treatment"] = str(treatment_db)
    result["baseline"] = str(baseline_db)
    result["model"] = t_profile.get("model", "")
    return result


def discover_pairs(captures_dir: Path) -> List[Tuple[Path, Path]]:
    pairs = []
    dirs = sorted(d for d in captures_dir.iterdir() if d.is_dir())
    treatment_dirs = [d for d in dirs if "treatment" in d.name and (d / "state.db").exists()]
    for t_dir in treatment_dirs:
        b_name = t_dir.name.replace("treatment", "baseline")
        b_dir = captures_dir / b_name
        if b_dir.exists() and (b_dir / "state.db").exists():
            pairs.append((t_dir / "state.db", b_dir / "state.db"))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="Context Window Preservation Index scorer")
    parser.add_argument("paths", nargs="*", help="treatment.db baseline.db (or captures dir with --pair-by-task)")
    parser.add_argument("--output", "-o", type=str, default="", help="Write JSON to file")
    parser.add_argument("--pair-by-task", action="store_true", help="Auto-discover pairs in a captures directory")
    args = parser.parse_args()

    results: List[Dict[str, Any]] = []

    if args.pair_by_task:
        if len(args.paths) != 1:
            parser.error("--pair-by-task requires exactly one captures directory")
        captures_dir = Path(args.paths[0])
        pairs = discover_pairs(captures_dir)
        if not pairs:
            print(f"No pairs found in {captures_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Discovered {len(pairs)} pair(s)", file=sys.stderr)
        for t_db, b_db in pairs:
            results.append(score_pair(t_db, b_db))
    else:
        if len(args.paths) != 2:
            parser.error("Provide exactly 2 paths: treatment.db baseline.db")
        results.append(score_pair(Path(args.paths[0]), Path(args.paths[1])))

    output = {"pairs": results, "count": len(results)}
    if len(results) > 1:
        valid = [r for r in results if "error" not in r]
        if valid:
            cpis = [r["cpi"] for r in valid]
            output["aggregate"] = {
                "mean_cpi": round(sum(cpis) / len(cpis), 3),
                "min_cpi": round(min(cpis), 3),
                "max_cpi": round(max(cpis), 3),
                "mean_offload_ratio": round(sum(r["offload_ratio"] for r in valid) / len(valid), 3),
            }

    rendered = json.dumps(output, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(rendered + "\n")
        print(f"Written: {args.output}", file=sys.stderr)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
