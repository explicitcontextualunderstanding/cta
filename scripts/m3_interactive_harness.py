#!/usr/bin/env python3
"""M3 Interactive-Mode Capture Harness.

Tests H3 (Interactive Blockade Resolution): does the skill's folder-trust
guidance help the model handle qodercli's first-launch trust dialog?

Runs 2 sessions: treatment (with skill) and baseline (without skill).
The prompt forces interactive mode (-i, background=true, pty=true) which
triggers the folder trust prompt on first launch in a fresh directory.

Usage:
    python scripts/m3_interactive_harness.py --condition both
    python scripts/m3_interactive_harness.py --condition treatment --dry-run
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "fixture"
SKILL_PATH = Path.home() / ".hermes/skills/autonomous-ai-agents/qodercli/SKILL.md"
OUTPUT_DIR = PROJECT_ROOT / "data" / "m3_captures"

HERMES_COMMIT = "a41d280f95c69f67380358b305b62345934ecaf3"
QODERCLI_VERSION = "1.1.1"
CONTAINER_IMAGE = "registry.rossollc.com/hermes:latest"
ENCLAVE = Path.home() / ".enclave"

M3_PROMPT = (
    "Use qodercli in interactive mode to implement a REST API authentication "
    "endpoint in src/routes/auth.py with JWT token validation middleware in "
    "src/middleware/token.py. Launch qodercli with the -i flag using "
    "background=true and pty=true, then guide it through the implementation "
    "step by step using process commands (poll, write, log). After qodercli "
    "finishes, verify the implementation by running the test suite."
)


def load_secrets() -> dict:
    return {
        "OPENROUTER_API_KEY": (ENCLAVE / "openrouter_key.txt").read_text().strip(),
        "QODER_PERSONAL_ACCESS_TOKEN": (ENCLAVE / "qoder.txt").read_text().strip(),
    }


def generate_run_script(condition: str, run_num: int) -> str:
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

    prompt_escaped = M3_PROMPT.replace("'", "'\\''")

    return f"""#!/bin/sh
set -e

echo '=== CTA M3 Run: P1-interactive-{condition}-{run_num} ==='
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

echo '=== Running interactive-mode task ==='
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
echo "task_id=P1-interactive" >> /root/output/run_metadata.txt
echo "condition={condition}" >> /root/output/run_metadata.txt
echo "run_num={run_num}" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
"""


def run_container(condition: str, run_num: int, secrets: dict, timeout: int, dry_run: bool) -> bool:
    run_id = f"P1-interactive-{condition}-{run_num}"
    container_name = f"cta-m3-{run_id}"
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    script = generate_run_script(condition, run_num)
    script_path = run_dir / "run.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)

    cmd = [
        "container", "run", "--name", container_name,
        "-c", "4", "-m", "2G",
        "-e", f"OPENROUTER_API_KEY={secrets['OPENROUTER_API_KEY']}",
    ]
    if condition == "treatment":
        cmd += ["-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}"]

    cmd += [
        "--mount", f"type=bind,source={FIXTURE_DIR},target=/root/fixture,readonly",
        "--mount", f"type=bind,source={run_dir},target=/root/output",
    ]
    if condition == "treatment":
        resolved_skill = SKILL_PATH.resolve()
        cmd += ["--mount", f"type=bind,source={resolved_skill.parent},target=/root/skill,readonly"]

    cmd += ["--entrypoint", "/bin/sh", CONTAINER_IMAGE, "/root/output/run.sh"]

    if dry_run:
        print(f"[DRY RUN] {run_id}")
        print(f"  container: {container_name}")
        print(f"  output: {run_dir}")
        print(f"  command: {' '.join(cmd[:10])}...")
        return True

    print(f"[M3] Starting {run_id} (timeout={timeout}s)...")
    start = time.time()

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start
        print(f"[M3] {run_id} finished in {elapsed:.1f}s (exit={proc.returncode})")
        if proc.returncode != 0:
            print(f"  stderr: {proc.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"[M3] {run_id} TIMED OUT after {elapsed:.1f}s")
        subprocess.run(["container", "stop", container_name], capture_output=True)
    finally:
        subprocess.run(["container", "rm", container_name], capture_output=True)

    result = {
        "run_id": run_id,
        "task_id": "P1-interactive",
        "condition": condition,
        "run_num": run_num,
        "exit_code": proc.returncode if 'proc' in dir() else -1,
        "elapsed_seconds": round(elapsed, 1),
        "container_name": container_name,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result.get("exit_code", -1) == 0


def main():
    parser = argparse.ArgumentParser(description="M3 Interactive-Mode Capture")
    parser.add_argument("--condition", choices=["treatment", "baseline", "both"], default="both")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets()

    conditions = ["treatment", "baseline"] if args.condition == "both" else [args.condition]

    print(f"M3 Interactive-Mode Capture")
    print(f"  Conditions: {conditions}")
    print(f"  Runs per condition: {args.runs}")
    print(f"  Timeout: {args.timeout}s")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Prompt: {M3_PROMPT[:80]}...")
    print()

    results = []
    for condition in conditions:
        for run_num in range(1, args.runs + 1):
            ok = run_container(condition, run_num, secrets, args.timeout, args.dry_run)
            results.append({"condition": condition, "run": run_num, "success": ok})

    print(f"\n{'='*50}")
    print("M3 CAPTURE SUMMARY")
    print(f"{'='*50}")
    for r in results:
        status = "PASS" if r["success"] else "FAIL/TIMEOUT"
        print(f"  P1-interactive-{r['condition']}-{r['run']}: {status}")


if __name__ == "__main__":
    main()
