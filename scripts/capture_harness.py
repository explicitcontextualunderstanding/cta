#!/usr/bin/env python3
"""M2 Counterfactual Capture Harness.

Orchestrates treatment (with skill) and baseline (without skill) container runs
for the qodercli CTA audit. Each run is a fresh Apple Container micro-VM.

Usage:
    python scripts/capture_harness.py --task P1 --condition treatment --run 1
    python scripts/capture_harness.py --task all --condition both --runs 3
    python scripts/capture_harness.py --smoke  # single quick validation run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "fixture"
SKILL_PATH = Path.home() / ".hermes/skills/autonomous-ai-agents/qodercli/SKILL.md"
OUTPUT_DIR = PROJECT_ROOT / "data" / "m2_captures"
PRE_REG_PATH = PROJECT_ROOT / "tasks" / "pre_registration.json"

HERMES_COMMIT = "a41d280f95c69f67380358b305b62345934ecaf3"
QODERCLI_VERSION = "1.1.1"
CONTAINER_IMAGE = "registry.rossollc.com/hermes:latest"

ENCLAVE = Path.home() / ".enclave"


def load_secrets() -> dict:
    return {
        "OPENROUTER_API_KEY": (ENCLAVE / "openrouter_key.txt").read_text().strip(),
        "QODER_PERSONAL_ACCESS_TOKEN": (ENCLAVE / "qoder.txt").read_text().strip(),
    }


def load_pre_reg() -> dict:
    return json.loads(PRE_REG_PATH.read_text())


def get_task(pre_reg: dict, task_id: str) -> dict:
    for t in pre_reg["tasks"]:
        if t["id"] == task_id:
            return t
    raise ValueError(f"Unknown task: {task_id}")


def generate_run_script(task: dict, condition: str, run_num: int) -> str:
    """Generate the shell script that runs inside the container."""
    skill_setup = ""
    if condition == "treatment":
        skill_setup = """
echo '=== Installing qodercli skill ==='
mkdir -p /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli
cp /root/skill/SKILL.md /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli/SKILL.md
"""
    else:
        skill_setup = """
echo '=== Baseline: no skill installed ==='
rm -rf /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli 2>/dev/null || true
"""

    prompt_escaped = task["prompt"].replace("'", "'\\''")

    script = f"""#!/bin/sh
set -e

echo '=== CTA M2 Run: {task["id"]}-{condition}-{run_num} ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Upgrading hermes to v0.19.0 ==='
cd /opt/hermes
git fetch origin {HERMES_COMMIT} --depth=1 2>/dev/null
git checkout -f {HERMES_COMMIT} 2>/dev/null
uv pip install . --python /opt/hermes/.venv/bin/python3 --quiet 2>/dev/null
hermes --version

echo '=== Installing qodercli {QODERCLI_VERSION} ==='
npm install -g @qoder-ai/qodercli@{QODERCLI_VERSION} 2>/dev/null
qodercli --version

{skill_setup}

echo '=== Setting up workspace ==='
cp -r /root/fixture /root/workspace
cd /root/workspace
git init -q
git add -A
git commit -q -m "fixture baseline" --allow-empty 2>/dev/null || true

echo '=== Running task ==='
hermes chat -q '{prompt_escaped}' -Q --yolo --provider openrouter -m anthropic/claude-sonnet-4 2>&1 | tee /root/output/hermes_stdout.txt

echo '=== Exporting session ==='
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/hermes/.hermes/state.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
cp /home/hermes/.hermes/state.db /root/output/state.db
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/output/run_metadata.txt
echo "task_id={task["id"]}" >> /root/output/run_metadata.txt
echo "condition={condition}" >> /root/output/run_metadata.txt
echo "run_num={run_num}" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
"""
    return script


def run_container(task_id: str, condition: str, run_num: int, task: dict, secrets: dict, timeout: int = 600) -> bool:
    """Execute a single container run."""
    run_id = f"{task_id}-{condition}-{run_num}"
    container_name = f"cta-m2-{run_id}"
    run_output_dir = OUTPUT_DIR / run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

    # Generate and write the run script
    run_script = generate_run_script(task, condition, run_num)
    script_path = run_output_dir / "run.sh"
    script_path.write_text(run_script)
    script_path.chmod(0o755)

    # Build container command
    cmd = [
        "container", "run",
        "--name", container_name,
        "-c", "4",
        "-m", "2G",
        "-e", f"OPENROUTER_API_KEY={secrets['OPENROUTER_API_KEY']}",
    ]

    if condition == "treatment":
        cmd += ["-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}"]

    cmd += [
        "--mount", f"type=bind,source={FIXTURE_DIR},target=/root/fixture,readonly",
        "--mount", f"type=bind,source={run_output_dir},target=/root/output",
    ]

    if condition == "treatment":
        resolved_skill = SKILL_PATH.resolve()
        cmd += ["--mount", f"type=bind,source={resolved_skill.parent},target=/root/skill,readonly"]

    cmd += [
        "--entrypoint", "/bin/sh",
        CONTAINER_IMAGE,
        "/root/output/run.sh",
    ]

    print(f"\n{'='*60}")
    print(f"RUN: {run_id}")
    print(f"Container: {container_name}")
    print(f"Task: {task['prompt'][:80]}...")
    print(f"{'='*60}")

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start

        # Write result metadata
        meta = {
            "run_id": run_id,
            "task_id": task_id,
            "condition": condition,
            "run_num": run_num,
            "exit_code": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "container_name": container_name,
        }
        (run_output_dir / "result.json").write_text(json.dumps(meta, indent=2))

        if result.returncode == 0:
            print(f"  PASS ({elapsed:.1f}s)")
            return True
        else:
            print(f"  FAIL (exit {result.returncode}, {elapsed:.1f}s)")
            print(f"  stderr: {result.stderr[-500:]}" if result.stderr else "")
            (run_output_dir / "stderr.txt").write_text(result.stderr or "")
            return False

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"  TIMEOUT ({elapsed:.1f}s)")
        subprocess.run(["container", "stop", container_name], capture_output=True)
        meta = {"run_id": run_id, "exit_code": -1, "elapsed_seconds": round(elapsed, 1), "error": "timeout"}
        (run_output_dir / "result.json").write_text(json.dumps(meta, indent=2))
        return False
    finally:
        subprocess.run(["container", "rm", container_name], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description="CTA M2 Capture Harness")
    parser.add_argument("--task", default="all", help="Task ID (P1/P2/P3/N1/E1) or 'all'")
    parser.add_argument("--condition", default="both", choices=["treatment", "baseline", "both"])
    parser.add_argument("--runs", type=int, default=3, help="Runs per condition per task")
    parser.add_argument("--smoke", action="store_true", help="Single quick smoke test (E1 baseline)")
    parser.add_argument("--timeout", type=int, default=900, help="Per-run timeout in seconds")
    parser.add_argument("--start-run", type=int, default=1, help="Starting run number (for variance runs)")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    secrets = load_secrets()
    pre_reg = load_pre_reg()

    if args.smoke:
        tasks = [get_task(pre_reg, "E1")]
        conditions = ["baseline"]
        runs = 1
    else:
        if args.task == "all":
            tasks = pre_reg["tasks"]
        else:
            tasks = [get_task(pre_reg, args.task)]

        if args.condition == "both":
            conditions = ["treatment", "baseline"]
        else:
            conditions = [args.condition]
        runs = args.runs

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = len(tasks) * len(conditions) * runs
    print(f"CTA M2 Capture: {len(tasks)} tasks x {len(conditions)} conditions x {runs} runs = {total} sessions")

    if args.dry_run:
        for task in tasks:
            for cond in conditions:
                for r in range(args.start_run, runs + 1):
                    print(f"  {task['id']}-{cond}-{r}: {task['prompt'][:60]}...")
        return

    results = []
    for task in tasks:
        for cond in conditions:
            for r in range(args.start_run, runs + 1):
                ok = run_container(task["id"], cond, r, task, secrets, timeout=args.timeout)
                results.append({"run_id": f"{task['id']}-{cond}-{r}", "success": ok})

    # Summary
    passed = sum(1 for r in results if r["success"])
    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed}/{len(results)} runs completed successfully")
    print(f"Output: {OUTPUT_DIR}")
    print(f"{'='*60}")

    summary_path = OUTPUT_DIR / "capture_summary.json"
    summary_path.write_text(json.dumps({
        "total_runs": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }, indent=2))

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
