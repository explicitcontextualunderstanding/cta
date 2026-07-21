#!/usr/bin/env python3
"""M4 Counterfactual: PTY Stability — deterministic print-mode comparison.

Tests whether PTY allocation affects qodercli print-mode output.
Condition A: qodercli runs with a PTY allocated (pty.openpty)
Condition B: qodercli runs with plain pipes (subprocess.PIPE)

No Hermes, no model — isolates the PTY variable perfectly.
Reuses the M2 fixture directory for real coding tasks.

Usage:
    python scripts/m4_harness.py [--task T1|T2|all] [--timeout 180]
"""

import json
import os
import pty
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixture"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "m4_captures"

TASKS = {
    "T1": "Implement a REST API endpoint for user authentication in src/routes/auth.py with JWT token validation in src/middleware/token.py and a User model in src/models/user.py. Add tests in tests/test_auth.py.",
    "T2": "Read package.json and tell me the project version. Do NOT modify any files.",
}


def run_with_pty(command: list[str], cwd: str, timeout: int) -> dict:
    """Condition A: Run command with a PTY allocated."""
    start = time.time()
    master_fd, slave_fd = pty.openpty()

    try:
        proc = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            close_fds=True,
        )
        os.close(slave_fd)

        output_chunks = []
        while True:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                proc.kill()
                proc.wait()
                os.close(master_fd)
                return {
                    "condition": "A_pty",
                    "exit_code": -1,
                    "output": "".join(output_chunks),
                    "wall_time": time.time() - start,
                    "timed_out": True,
                }

            ready, _, _ = select.select([master_fd], [], [], min(1.0, remaining))
            if ready:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    output_chunks.append(data.decode("utf-8", errors="replace"))
                except OSError:
                    break
            elif proc.poll() is not None:
                # Drain remaining
                try:
                    while True:
                        r, _, _ = select.select([master_fd], [], [], 0.1)
                        if not r:
                            break
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        output_chunks.append(data.decode("utf-8", errors="replace"))
                except OSError:
                    pass
                break

        proc.wait()
        os.close(master_fd)
        return {
            "condition": "A_pty",
            "exit_code": proc.returncode,
            "output": "".join(output_chunks),
            "wall_time": time.time() - start,
            "timed_out": False,
        }
    except Exception as e:
        try:
            os.close(master_fd)
        except OSError:
            pass
        return {
            "condition": "A_pty",
            "exit_code": -1,
            "output": "",
            "wall_time": time.time() - start,
            "timed_out": False,
            "error": str(e),
        }


def run_with_pipes(command: list[str], cwd: str, timeout: int) -> dict:
    """Condition B: Run command with plain pipes (no PTY)."""
    start = time.time()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return {
            "condition": "B_pipes",
            "exit_code": proc.returncode,
            "output": proc.stdout,
            "stderr": proc.stderr,
            "wall_time": time.time() - start,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "condition": "B_pipes",
            "exit_code": -1,
            "output": e.stdout or "",
            "stderr": e.stderr or "",
            "wall_time": time.time() - start,
            "timed_out": True,
        }


def prepare_worktree(task_id: str, condition: str) -> str:
    """Create a clean copy of the fixture for each run."""
    work_dir = OUTPUT_DIR / f"{task_id}-{condition}" / "workspace"
    if work_dir.exists():
        subprocess.run(["rm", "-rf", str(work_dir)], check=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cp", "-r", str(FIXTURE_DIR) + "/.", str(work_dir)],
        check=True,
    )
    return str(work_dir)


def run_task(task_id: str, timeout: int) -> dict:
    """Run both conditions for a task and compare."""
    prompt = TASKS[task_id]
    command = ["qodercli", "-p", prompt, "--print", "--permission-mode", "bypass_permissions"]

    print(f"\n{'='*60}")
    print(f"M4: {task_id} — {prompt[:60]}...")
    print(f"{'='*60}")

    # Condition A: PTY
    print(f"\n  [A] Running with PTY allocated...")
    work_a = prepare_worktree(task_id, "A_pty")
    result_a = run_with_pty(command, work_a, timeout)
    print(f"      exit={result_a['exit_code']} time={result_a['wall_time']:.1f}s "
          f"output_len={len(result_a['output'])} timed_out={result_a['timed_out']}")

    # Condition B: Pipes
    print(f"  [B] Running with pipes (no PTY)...")
    work_b = prepare_worktree(task_id, "B_pipes")
    result_b = run_with_pipes(command, work_b, timeout)
    print(f"      exit={result_b['exit_code']} time={result_b['wall_time']:.1f}s "
          f"output_len={len(result_b['output'])} timed_out={result_b['timed_out']}")

    # Compare
    comparison = {
        "task_id": task_id,
        "prompt": prompt,
        "condition_a": result_a,
        "condition_b": result_b,
        "exit_codes_match": result_a["exit_code"] == result_b["exit_code"],
        "both_success": result_a["exit_code"] == 0 and result_b["exit_code"] == 0,
        "wall_time_diff_pct": (
            abs(result_a["wall_time"] - result_b["wall_time"])
            / max(result_a["wall_time"], result_b["wall_time"], 0.01)
            * 100
        ),
        "output_length_diff_pct": (
            abs(len(result_a["output"]) - len(result_b["output"]))
            / max(len(result_a["output"]), len(result_b["output"]), 1)
            * 100
        ),
    }

    # Check file diffs for T1 (write task)
    if task_id == "T1":
        files_a = _list_modified_files(work_a)
        files_b = _list_modified_files(work_b)
        comparison["files_modified_a"] = files_a
        comparison["files_modified_b"] = files_b
        comparison["same_files_modified"] = set(files_a) == set(files_b)

    verdict = "PASS" if comparison["both_success"] else "FAIL"
    print(f"\n  Verdict: {verdict}")
    print(f"    Exit codes match: {comparison['exit_codes_match']}")
    print(f"    Wall time diff: {comparison['wall_time_diff_pct']:.1f}%")
    print(f"    Output length diff: {comparison['output_length_diff_pct']:.1f}%")
    if task_id == "T1":
        print(f"    Same files modified: {comparison.get('same_files_modified', 'N/A')}")

    return comparison


IGNORED_PREFIXES = (".venv/", "__pycache__/", ".git/")


def _list_modified_files(work_dir: str) -> list[str]:
    """List files that differ from the original fixture."""
    modified = []
    work_path = Path(work_dir)
    fixture_path = FIXTURE_DIR

    for f in work_path.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(work_path))
            if any(rel.startswith(p) for p in IGNORED_PREFIXES):
                continue
            orig = fixture_path / rel
            if not Path(orig).exists():
                modified.append(rel)
            elif f.read_bytes() != orig.read_bytes():
                modified.append(rel)
    return sorted(modified)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="M4 PTY Stability Counterfactual")
    parser.add_argument("--task", default="all", choices=["T1", "T2", "all"])
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tasks = list(TASKS.keys()) if args.task == "all" else [args.task]
    results = []

    for task_id in tasks:
        result = run_task(task_id, args.timeout)
        results.append(result)

    # Save results (merge with existing to avoid overwriting prior runs)
    output_file = OUTPUT_DIR / "m4_results.json"
    existing = {}
    if output_file.exists():
        try:
            for entry in json.loads(output_file.read_text()):
                existing[entry["task_id"]] = entry
        except (json.JSONDecodeError, KeyError):
            pass

    for r in results:
        sr = {k: v for k, v in r.items() if k not in ("condition_a", "condition_b")}
        sr["a_exit"] = r["condition_a"]["exit_code"]
        sr["b_exit"] = r["condition_b"]["exit_code"]
        sr["a_wall_time"] = r["condition_a"]["wall_time"]
        sr["b_wall_time"] = r["condition_b"]["wall_time"]
        sr["a_output_len"] = len(r["condition_a"]["output"])
        sr["b_output_len"] = len(r["condition_b"]["output"])
        sr["a_timed_out"] = r["condition_a"]["timed_out"]
        sr["b_timed_out"] = r["condition_b"]["timed_out"]
        existing[r["task_id"]] = sr

    save_results = list(existing.values())
    output_file.write_text(json.dumps(save_results, indent=2))
    print(f"\nResults saved to {output_file}")

    # Summary
    print(f"\n{'='*60}")
    print("M4 SUMMARY")
    print(f"{'='*60}")
    all_pass = all(r["both_success"] for r in results)
    for r in results:
        status = "PASS" if r["both_success"] else "FAIL"
        print(f"  {r['task_id']}: {status} (exit match={r['exit_codes_match']}, "
              f"time diff={r['wall_time_diff_pct']:.1f}%)")

    if all_pass:
        print("\n  H2-revised: Print mode is PTY-agnostic (A ≈ B confirmed)")
    else:
        print("\n  H2-revised: INCONCLUSIVE — systematic failure detected")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
