#!/usr/bin/env python3
"""Score a raw NDJSON stream for environment friction (Plan 8 §3.2).

Usage:
    python3 scripts/score_friction.py <raw.ndjson> [--window 50] [--json]

Computes the composite friction_index from three signals:
  S1: error_rate     — tool_use_result.exitCode != 0 or error text patterns
  S2: ctx_velocity   — context_usage_ratio growth rate (normalized to 0.02/event)
  S3: retry_density  — max repeated tool:key_input[:80] signature / total calls

Classification:
  < 0.15  → CLEAN (no display overhead)
  0.15-0.40 → MILD
  >= 0.40 → FRICTION (warning displayed)
"""

import json
import sys
from collections import Counter

ERROR_PATTERNS = (
    "Traceback (most recent call last)",
    "Error:",
    "error:",
    "FAILED",
    "Permission denied",
    "No such file or directory",
    "command not found",
    "ModuleNotFoundError",
    "ImportError",
    "ConnectionError",
    "kalloc",
)


def score_friction(output_buffer: str, window: int = 50) -> dict:
    lines = output_buffer.strip().split("\n")
    events = []
    for line in lines[-window:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        events.append(obj)

    if not events:
        return {"friction_index": 0.0, "classification": "EMPTY", "events": 0}

    error_count = 0
    tool_result_count = 0
    context_ratios = []
    tool_call_signatures = []

    for i, ev in enumerate(events):
        ev_type = ev.get("type", "")

        if ev_type == "assistant":
            msg = ev.get("message", {})
            if msg.get("stop_reason") is not None:
                usage = msg.get("usage", {})
                ratio = usage.get("context_usage_ratio")
                if ratio is not None:
                    context_ratios.append((i, float(ratio)))

            for block in msg.get("content", []):
                if block.get("type") != "tool_use":
                    continue
                name = block.get("name", "unknown")
                inp = block.get("input", {})
                sig_input = (
                    inp.get("command") or inp.get("file_path")
                    or inp.get("pattern") or inp.get("prompt")
                    or inp.get("url") or inp.get("description")
                    or (str(inp)[:80] if inp else "")
                )
                tool_call_signatures.append(f"{name}:{str(sig_input)[:80]}")

        elif ev_type == "user":
            tool_use_result = ev.get("tool_use_result", {})
            exit_code = tool_use_result.get("exitCode")

            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tool_result_count += 1
                if exit_code is not None and exit_code != 0:
                    error_count += 1
                    continue
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                if any(pat in content for pat in ERROR_PATTERNS):
                    error_count += 1

    # S1: Error rate
    error_rate = error_count / max(tool_result_count, 1)

    # S2: Context velocity (normalized)
    ctx_velocity = 0.0
    if len(context_ratios) >= 3:
        first_idx, first_ratio = context_ratios[0]
        last_idx, last_ratio = context_ratios[-1]
        span = last_idx - first_idx
        if span > 0:
            ctx_velocity = (last_ratio - first_ratio) / span
    ctx_velocity_norm = min(ctx_velocity / 0.02, 1.0)

    # S3: Retry density
    sig_counts = Counter(tool_call_signatures)
    retry_density = max(sig_counts.values(), default=0) / max(len(tool_call_signatures), 1)

    friction_index = (error_rate + ctx_velocity_norm + retry_density) / 3

    if friction_index >= 0.40:
        classification = "FRICTION"
    elif friction_index >= 0.15:
        classification = "MILD"
    else:
        classification = "CLEAN"

    # Signal breakdown for friction sessions
    signals = []
    if friction_index >= 0.40:
        if error_rate > 0.3:
            signals.append(f"HIGH-ERROR ({error_count}/{tool_result_count})")
        if ctx_velocity > 0.02:
            signals.append(f"CTX-VELOCITY +{ctx_velocity:.1%}/ev")
        if retry_density > 0.3:
            worst = max(sig_counts.items(), key=lambda x: x[1])
            tool_name = worst[0].split(":")[0]
            signals.append(f"RETRY {tool_name} x{worst[1]}")
        if context_ratios and context_ratios[-1][1] > 0.85:
            signals.append(f"CTX-FULL {context_ratios[-1][1]:.0%}")

    return {
        "friction_index": round(friction_index, 4),
        "classification": classification,
        "signals": signals,
        "events": len(events),
        "error_rate": round(error_rate, 4),
        "error_count": error_count,
        "tool_result_count": tool_result_count,
        "ctx_velocity": round(ctx_velocity, 6),
        "ctx_velocity_norm": round(ctx_velocity_norm, 4),
        "retry_density": round(retry_density, 4),
        "context_ratios": len(context_ratios),
        "tool_calls": len(tool_call_signatures),
        "top_retries": sig_counts.most_common(3),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    window = 50
    as_json = "--json" in sys.argv

    for i, arg in enumerate(sys.argv):
        if arg == "--window" and i + 1 < len(sys.argv):
            window = int(sys.argv[i + 1])

    with open(path) as f:
        content = f.read()

    result = score_friction(content, window=window)

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"File: {path}")
        print(f"Window: last {window} events ({result['events']} parsed)")
        print(f"")
        print(f"  friction_index = {result['friction_index']:.4f}  [{result['classification']}]")
        print(f"")
        print(f"  S1 error_rate:      {result['error_rate']:.4f}  ({result['error_count']}/{result['tool_result_count']})")
        print(f"  S2 ctx_velocity:    {result['ctx_velocity']:.6f}/ev  (norm: {result['ctx_velocity_norm']:.4f})")
        print(f"  S3 retry_density:   {result['retry_density']:.4f}  ({result['tool_calls']} calls, {result['context_ratios']} ctx samples)")
        if result["signals"]:
            print(f"")
            print(f"  ⚠ Friction: {' | '.join(result['signals'])}")
        if result["top_retries"]:
            print(f"")
            print(f"  Top retries:")
            for sig, count in result["top_retries"]:
                if count > 1:
                    print(f"    {sig[:60]}  x{count}")

    # Exit code: 0=clean, 1=mild, 2=friction
    sys.exit({"CLEAN": 0, "MILD": 1, "FRICTION": 2, "EMPTY": 0}[result["classification"]])


if __name__ == "__main__":
    main()
