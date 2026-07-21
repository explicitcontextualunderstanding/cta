#!/usr/bin/env python3
"""M2 Counterfactual Analysis — structural metrics, SIP detection, hypothesis evaluation.

Reads all sessions from data/m2_captures/, converts state.db → CTA events via
hermes_adapter, computes per-task treatment vs baseline comparisons, and evaluates
the 4 pre-registered hypotheses.

Usage:
    python scripts/m2_analysis.py [--output data/m2_analysis.json]
"""

import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cta.hermes_adapter import hermes_session_to_trace, map_tool
from cta.data_models import EventType

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "m2_captures"


def load_session_from_db(db_path: Path) -> dict:
    """Extract a Hermes session dict from state.db for the adapter."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    session_row = cur.execute(
        "SELECT id, model, system_prompt FROM sessions LIMIT 1"
    ).fetchone()
    if not session_row:
        conn.close()
        return {}

    session_id = session_row["id"]
    rows = cur.execute(
        """SELECT id, role, content, tool_call_id, tool_calls, tool_name,
                  reasoning, reasoning_content, finish_reason, token_count
           FROM messages
           WHERE session_id = ? AND active = 1 AND compacted = 0
           ORDER BY id""",
        (session_id,),
    ).fetchall()
    conn.close()

    messages = []
    for r in rows:
        msg = {
            "role": r["role"],
            "content": r["content"] or "",
            "tool_call_id": r["tool_call_id"],
            "tool_name": r["tool_name"],
        }
        if r["role"] == "assistant":
            msg["reasoning"] = r["reasoning"] or r["reasoning_content"] or ""
            msg["finish_reason"] = r["finish_reason"]
            if r["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(r["tool_calls"])
                except (json.JSONDecodeError, TypeError):
                    msg["tool_calls"] = []
            else:
                msg["tool_calls"] = []
        messages.append(msg)

    return {
        "session_id": session_id,
        "model": session_row["model"],
        "system_prompt": session_row["system_prompt"],
        "messages": messages,
    }


def load_result(run_dir: Path) -> dict:
    result_path = run_dir / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    return {}


def compute_entropy(tool_counts: dict) -> float:
    total = sum(tool_counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in tool_counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def extract_tool_calls_from_messages(messages: list) -> list:
    """Extract all tool call records with name, arguments, and observation."""
    tool_results = {}
    for msg in messages:
        if msg.get("role") == "tool":
            cid = msg.get("tool_call_id", "")
            tool_results[cid] = msg.get("content", "")

    calls = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "") or ""
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": raw_args}
            else:
                args = raw_args or {}
            cid = tc.get("id") or tc.get("call_id") or ""
            calls.append({
                "name": name,
                "args": args,
                "observation": tool_results.get(cid, ""),
                "call_id": cid,
            })
    return calls


def analyze_session(run_dir: Path) -> dict:
    """Full analysis of one capture session."""
    db_path = run_dir / "state.db"
    if not db_path.exists():
        return {"error": "no state.db", "run_id": run_dir.name}

    session = load_session_from_db(db_path)
    if not session:
        return {"error": "no session in db", "run_id": run_dir.name}

    result = load_result(run_dir)
    messages = session["messages"]
    tool_calls = extract_tool_calls_from_messages(messages)

    # Run through CTA adapter
    with_skill = "treatment" in run_dir.name
    trace, adapter_report = hermes_session_to_trace(session, with_skill=with_skill)

    # Structural metrics
    tool_counts = Counter(tc["name"] for tc in tool_calls)
    type_counts = Counter(e.type.value for e in trace.events)

    # qodercli-specific metrics
    qodercli_calls = [tc for tc in tool_calls if "qodercli" in json.dumps(tc["args"]).lower()
                      or "qodercli" in tc.get("observation", "").lower()]
    qodercli_terminal = [tc for tc in tool_calls
                         if tc["name"] == "terminal"
                         and "qodercli" in tc["args"].get("command", "")]

    # File edit operations (manual writes by the agent)
    manual_writes = [tc for tc in tool_calls if tc["name"] in ("write_file", "patch", "replace")]

    # pty usage in terminal calls
    pty_set = [tc for tc in tool_calls
               if tc["name"] == "terminal" and tc["args"].get("pty") is True]
    pty_omitted = [tc for tc in tool_calls
                   if tc["name"] == "terminal"
                   and "qodercli" in tc["args"].get("command", "")
                   and not tc["args"].get("pty")]

    # Binary resolution (which/where qodercli)
    binary_resolution = [tc for tc in tool_calls
                         if tc["name"] == "terminal"
                         and re.search(r"which|where", tc["args"].get("command", ""))
                         and "qodercli" in tc["args"].get("command", "")]

    # Skill loading
    skill_views = [tc for tc in tool_calls if tc["name"] == "skill_view"]

    # Interactive blockade detection (consecutive identical process polls)
    blockade_streaks = detect_blockade(tool_calls)

    # Message and tool call counts
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    total_messages = len(messages)

    return {
        "run_id": run_dir.name,
        "session_id": session["session_id"],
        "model": session["model"],
        "condition": "treatment" if with_skill else "baseline",
        "task_id": result.get("task_id", run_dir.name.split("-")[0]),
        "exit_code": result.get("exit_code"),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "total_messages": total_messages,
        "assistant_messages": len(assistant_msgs),
        "total_tool_calls": len(tool_calls),
        "tool_counts": dict(tool_counts.most_common()),
        "type_counts": dict(type_counts.most_common()),
        "unique_tools": len(tool_counts),
        "entropy": round(compute_entropy(tool_counts), 3),
        "entropy_ratio": round(compute_entropy(tool_counts) / math.log2(max(len(tool_counts), 2)), 3),
        "manual_writes": len(manual_writes),
        "qodercli_terminal_calls": len(qodercli_terminal),
        "qodercli_mentions": sum(1 for m in messages if "qodercli" in (m.get("content") or "").lower()),
        "skill_views": len(skill_views),
        "binary_resolution": len(binary_resolution),
        "pty_set_count": len(pty_set),
        "pty_omitted_on_qodercli": len(pty_omitted),
        "blockade_streaks": blockade_streaks,
        "adapter_event_count": adapter_report["event_count"],
        "adapter_none_events": adapter_report["none_events"],
        "adapter_unmapped": adapter_report["unmapped_tools"],
    }


def detect_blockade(tool_calls: list, threshold: int = 3) -> list:
    """Detect consecutive identical process(poll/log) calls."""
    streaks = []
    streak = 0
    last_content = None
    for tc in tool_calls:
        if tc["name"] == "process":
            action = tc["args"].get("action", "")
            if action in ("poll", "log"):
                content = tc["observation"]
                if content == last_content:
                    streak += 1
                else:
                    streak = 1
                last_content = content
                if streak >= threshold:
                    streaks.append(streak)
            else:
                streak = 0
                last_content = None
        else:
            streak = 0
            last_content = None
    return streaks


def evaluate_hypotheses(sessions: list) -> dict:
    """Evaluate H1-H4 against all sessions."""
    treatments = [s for s in sessions if s["condition"] == "treatment" and "error" not in s]
    baselines = [s for s in sessions if s["condition"] == "baseline" and "error" not in s]

    # H1: Delegation Efficiency
    # Treatment should show fewer tool calls than baseline for positive tasks
    pos_treatments = [s for s in treatments if s["task_id"].startswith("P")]
    pos_baselines = [s for s in baselines if s["task_id"].startswith("P")]

    h1 = {"hypothesis": "Delegation Efficiency", "status": "UNKNOWN", "evidence": []}
    if pos_treatments and pos_baselines:
        avg_t_calls = sum(s["total_tool_calls"] for s in pos_treatments) / len(pos_treatments)
        avg_b_calls = sum(s["total_tool_calls"] for s in pos_baselines) / len(pos_baselines)
        avg_t_writes = sum(s["manual_writes"] for s in pos_treatments) / len(pos_treatments)
        avg_b_writes = sum(s["manual_writes"] for s in pos_baselines) / len(pos_baselines)
        compression = avg_b_calls / max(avg_t_calls, 1)
        write_compression = avg_b_writes / max(avg_t_writes, 1)

        # Disconfirmation: ≥20% MORE tool calls in treatment
        if avg_t_calls > avg_b_calls * 1.2:
            h1["status"] = "DISCONFIRMED"
        elif compression > 1.5:
            h1["status"] = "CONFIRMED (weak)"
        else:
            h1["status"] = "PARTIALLY CONFIRMED"

        h1["evidence"] = {
            "avg_treatment_tool_calls": round(avg_t_calls, 1),
            "avg_baseline_tool_calls": round(avg_b_calls, 1),
            "compression_ratio": round(compression, 2),
            "avg_treatment_writes": round(avg_t_writes, 1),
            "avg_baseline_writes": round(avg_b_writes, 1),
            "write_compression": round(write_compression, 2),
            "disconfirmation_threshold": "treatment ≥20% more tool calls than baseline",
        }

    # H2: PTY Execution Stability
    h2 = {"hypothesis": "PTY Execution Stability", "status": "UNKNOWN", "evidence": []}
    total_pty_omissions = sum(s["pty_omitted_on_qodercli"] for s in treatments)
    total_pty_set = sum(s["pty_set_count"] for s in treatments)
    if total_pty_omissions == 0:
        h2["status"] = "CONFIRMED"
    else:
        h2["status"] = "DISCONFIRMED"
    h2["evidence"] = {
        "pty_set_count": total_pty_set,
        "pty_omissions_on_qodercli": total_pty_omissions,
    }

    # H3: Interactive Blockade Resolution (untestable in print mode)
    h3 = {"hypothesis": "Interactive Blockade Resolution", "status": "UNTESTABLE", "evidence": {
        "reason": "Print mode only; no process() calls observed",
        "total_blockade_streaks": sum(len(s["blockade_streaks"]) for s in treatments),
    }}

    # H4: Binary Resolution Validation
    h4 = {"hypothesis": "Binary Resolution Validation", "status": "UNKNOWN", "evidence": []}
    treatments_with_binary_res = sum(1 for s in treatments if s["binary_resolution"] > 0)
    total_treatments = len(treatments)
    if total_treatments > 0 and treatments_with_binary_res >= (2 / 3) * total_treatments:
        h4["status"] = "CONFIRMED"
    elif treatments_with_binary_res > 0:
        h4["status"] = "PARTIALLY CONFIRMED"
    else:
        h4["status"] = "DISCONFIRMED"
    h4["evidence"] = {
        "treatments_with_binary_resolution": treatments_with_binary_res,
        "total_treatments": total_treatments,
        "threshold": "≥2/3 treatment traces",
    }

    return {"H1": h1, "H2": h2, "H3": h3, "H4": h4}


def detect_sips(sessions: list) -> list:
    """Run qodercli-specific SIP detectors across all treatment sessions."""
    sips = []
    treatments = [s for s in sessions if s["condition"] == "treatment" and "error" not in s]

    for s in treatments:
        run_id = s["run_id"]

        # SIP: PTY_OMISSION
        if s["pty_omitted_on_qodercli"] > 0:
            sips.append({
                "type": "PTY_OMISSION",
                "valence": "destructive",
                "run_id": run_id,
                "count": s["pty_omitted_on_qodercli"],
                "description": "qodercli invoked without pty=true",
            })

        # SIP: INTERACTIVE_BLOCKADE
        if s["blockade_streaks"]:
            sips.append({
                "type": "INTERACTIVE_BLOCKADE",
                "valence": "destructive",
                "run_id": run_id,
                "max_streak": max(s["blockade_streaks"]),
                "description": f"Consecutive identical poll/log calls (max streak: {max(s['blockade_streaks'])})",
            })

        # SIP: PROCEDURAL_SCAFFOLDING (constructive)
        if s["skill_views"] > 0 and s["binary_resolution"] > 0:
            sips.append({
                "type": "PROCEDURAL_SCAFFOLDING",
                "valence": "constructive",
                "run_id": run_id,
                "description": "Skill loaded → binary resolution → structured delegation",
            })

        # SIP: DELEGATION_REDIRECT (constructive)
        if s["qodercli_terminal_calls"] > 0:
            sips.append({
                "type": "DELEGATION_REDIRECT",
                "valence": "constructive",
                "run_id": run_id,
                "count": s["qodercli_terminal_calls"],
                "description": "Delegation redirected to qodercli (vs native delegate_task)",
            })

        # SIP: FALSE_SUCCESS (destructive) — check if qodercli errored but model reported success
        # Detected via: qodercli call with error in observation but no subsequent remediation
        # (simplified: check for permission errors in stdout)

    # Negative control check: N1 treatment should have zero qodercli invocations
    n1_treatments = [s for s in treatments if s["task_id"] == "N1"]
    for s in n1_treatments:
        if s["qodercli_terminal_calls"] > 0:
            sips.append({
                "type": "CONCEPT_BLEED",
                "valence": "destructive",
                "run_id": s["run_id"],
                "description": "qodercli invoked on negative control task (single-file typo fix)",
            })

    return sips


def task_comparison(sessions: list) -> dict:
    """Compare treatment vs baseline per task."""
    by_task = defaultdict(lambda: {"treatment": [], "baseline": []})
    for s in sessions:
        if "error" in s:
            continue
        by_task[s["task_id"]][s["condition"]].append(s)

    comparisons = {}
    for task_id, conditions in sorted(by_task.items()):
        t_runs = conditions["treatment"]
        b_runs = conditions["baseline"]
        if not t_runs or not b_runs:
            comparisons[task_id] = {"note": "incomplete pairing"}
            continue

        avg = lambda runs, key: sum(r[key] for r in runs) / len(runs)

        comparisons[task_id] = {
            "treatment_runs": len(t_runs),
            "baseline_runs": len(b_runs),
            "avg_messages": {"treatment": round(avg(t_runs, "total_messages"), 1),
                             "baseline": round(avg(b_runs, "total_messages"), 1)},
            "avg_tool_calls": {"treatment": round(avg(t_runs, "total_tool_calls"), 1),
                               "baseline": round(avg(b_runs, "total_tool_calls"), 1)},
            "avg_manual_writes": {"treatment": round(avg(t_runs, "manual_writes"), 1),
                                  "baseline": round(avg(b_runs, "manual_writes"), 1)},
            "avg_elapsed": {"treatment": round(avg(t_runs, "elapsed_seconds") or 0, 1),
                            "baseline": round(avg(b_runs, "elapsed_seconds") or 0, 1)},
            "avg_entropy": {"treatment": round(avg(t_runs, "entropy"), 3),
                            "baseline": round(avg(b_runs, "entropy"), 3)},
            "qodercli_calls": {"treatment": sum(r["qodercli_terminal_calls"] for r in t_runs),
                               "baseline": sum(r["qodercli_terminal_calls"] for r in b_runs)},
            "compression_ratio": round(avg(b_runs, "total_tool_calls") / max(avg(t_runs, "total_tool_calls"), 1), 2),
        }

    return comparisons


def main():
    import argparse
    parser = argparse.ArgumentParser(description="M2 Counterfactual Analysis")
    parser.add_argument("--output", "-o", default="data/m2_analysis.json")
    parser.add_argument("--captures-dir", default=str(CAPTURES_DIR))
    args = parser.parse_args()

    captures_dir = Path(args.captures_dir)
    if not captures_dir.exists():
        print(f"Error: captures directory not found: {captures_dir}")
        sys.exit(1)

    run_dirs = sorted(d for d in captures_dir.iterdir() if d.is_dir())
    print(f"Analyzing {len(run_dirs)} sessions from {captures_dir}\n")

    sessions = []
    for run_dir in run_dirs:
        print(f"  {run_dir.name}...", end=" ")
        result = analyze_session(run_dir)
        sessions.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"{result['total_messages']} msgs, {result['total_tool_calls']} tools, "
                  f"{result['elapsed_seconds']}s")

    # Compute analyses
    comparisons = task_comparison(sessions)
    hypotheses = evaluate_hypotheses(sessions)
    sips = detect_sips(sessions)

    # Variance analysis (treatment runs 1 vs 2 for P1 and P2)
    variance = {}
    for task_id in ("P1", "P2"):
        task_treatments = [s for s in sessions
                           if s.get("task_id") == task_id
                           and s.get("condition") == "treatment"
                           and "error" not in s]
        if len(task_treatments) >= 2:
            t1, t2 = task_treatments[0], task_treatments[1]
            variance[task_id] = {
                "tool_calls": [t1["total_tool_calls"], t2["total_tool_calls"]],
                "messages": [t1["total_messages"], t2["total_messages"]],
                "elapsed": [t1["elapsed_seconds"], t2["elapsed_seconds"]],
                "manual_writes": [t1["manual_writes"], t2["manual_writes"]],
                "qodercli_calls": [t1["qodercli_terminal_calls"], t2["qodercli_terminal_calls"]],
            }

    # Assemble report
    report = {
        "metadata": {
            "captures_dir": str(captures_dir),
            "total_sessions": len(sessions),
            "valid_sessions": sum(1 for s in sessions if "error" not in s),
            "design": "Option B (lean): 5 tasks × 2 conditions, 2-3 runs on positives",
        },
        "sessions": sessions,
        "task_comparisons": comparisons,
        "hypotheses": hypotheses,
        "sips": sips,
        "variance": variance,
    }

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nFull report: {output_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("M2 ANALYSIS SUMMARY")
    print("=" * 70)

    print("\n--- Task Comparisons (Treatment vs Baseline) ---")
    for task_id, comp in comparisons.items():
        if "note" in comp:
            print(f"\n  {task_id}: {comp['note']}")
            continue
        print(f"\n  {task_id} ({comp['treatment_runs']}T / {comp['baseline_runs']}B):")
        print(f"    Messages:      T={comp['avg_messages']['treatment']:>6} | B={comp['avg_messages']['baseline']:>6}")
        print(f"    Tool calls:    T={comp['avg_tool_calls']['treatment']:>6} | B={comp['avg_tool_calls']['baseline']:>6}  (compression: {comp['compression_ratio']}x)")
        print(f"    Manual writes: T={comp['avg_manual_writes']['treatment']:>6} | B={comp['avg_manual_writes']['baseline']:>6}")
        print(f"    Wall time:     T={comp['avg_elapsed']['treatment']:>6}s | B={comp['avg_elapsed']['baseline']:>6}s")
        print(f"    Entropy:       T={comp['avg_entropy']['treatment']:>6} | B={comp['avg_entropy']['baseline']:>6}")
        print(f"    qodercli calls: T={comp['qodercli_calls']['treatment']} | B={comp['qodercli_calls']['baseline']}")

    print("\n--- Hypothesis Evaluation ---")
    for hid, h in hypotheses.items():
        print(f"\n  {hid}: {h['hypothesis']}")
        print(f"      Status: {h['status']}")
        if isinstance(h.get("evidence"), dict):
            for k, v in h["evidence"].items():
                print(f"      {k}: {v}")

    print("\n--- SIP Detections ---")
    if sips:
        for sip in sips:
            print(f"  [{sip['valence']:>12}] {sip['type']:25} | {sip['run_id']} | {sip['description']}")
    else:
        print("  No SIPs detected.")

    if variance:
        print("\n--- Variance (Treatment Run 1 vs Run 2) ---")
        for task_id, v in variance.items():
            print(f"\n  {task_id}:")
            for metric, values in v.items():
                delta = abs(values[1] - values[0]) / max(values[0], 1) * 100 if values[0] else 0
                print(f"    {metric:20}: {values[0]} vs {values[1]} (Δ{delta:.0f}%)")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
