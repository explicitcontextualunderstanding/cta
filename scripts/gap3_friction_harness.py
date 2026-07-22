#!/usr/bin/env python3
"""Gap 3 ±Adaptation Paired Experiment Harness.

Runs paired treatment/control sessions where BOTH arms have the qodercli skill
installed — the difference is WHICH variant:
  - Treatment: SKILL.md v2.5.1 (with friction/exit-42 guidance block)
  - Control:   SKILL.md v2.4.0 (without friction block)

The container image is the F1 friction image (flask+pyjwt removed), so both
arms encounter friction. The treatment arm's skill should guide remediation.

Usage:
    python scripts/gap3_friction_harness.py --run-num 1
    python scripts/gap3_friction_harness.py --condition treatment --dry-run
    python scripts/gap3_friction_harness.py --condition both --timeout 900
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m3_interactive_harness import (
    check_kalloc_headroom,
    load_secrets,
    preflight_api_check,
    classify_session,
    FIXTURE_DIR,
    OUTPUT_DIR,
    QODERCLI_VERSION,
    OPENCODE_GO_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    KALLOC_MIN_HEADROOM,
)

# §4.1 M1 isolation probe: pinned-commit hermes (overlay-compatible) WITH deps present,
# so exit-42 is the ONLY friction and the -p fallback completes cleanly. Base hermes:latest
# lacks the overlay's nous_tool_gateway_unavailable_message import (infra_failure), so we
# build hermes:m1probe = pinned commit a41d280 + no friction removals.
CONTAINER_IMAGE = "registry.rossollc.com/hermes:m1probe"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SKILL_TREATMENT = (
    PROJECT_ROOT / "data/m3_captures/P1-interactive-P8-phase3-bgmode-treatment-1"
    / "hermes_home/skills/autonomous-ai-agents/qodercli/SKILL.md"
)
SKILL_CONTROL = (
    PROJECT_ROOT / "data/m3_captures/P1-interactive-P8-phase3-friction-treatment-1"
    / "hermes_home/skills/autonomous-ai-agents/qodercli/SKILL.md"
)

GAP3_PROMPT = (
    "Use qodercli to implement a REST API authentication endpoint with JWT token "
    "validation in /root/workspace/src/routes/auth.py and middleware in "
    "/root/workspace/src/middleware/token.py. Use qodercli in BACKGROUND mode "
    "(background=true, pty=true) and monitor it with process(poll). Run pytest "
    "to verify the implementation."
)

DEFAULT_TIMEOUT = 900


def generate_gap3_run_script(
    condition: str,
    run_num: int,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
) -> str:
    """Generate run.sh for a Gap 3 session. Both arms install the skill."""
    run_label = f"P8-gap3-friction-{condition}-{run_num}"
    prompt_escaped = GAP3_PROMPT.replace("'", "'\\''")

    return f"""#!/bin/sh
set -e

echo '=== CTA Gap3 Run: {run_label} ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Hermes pre-installed in friction image (v0.19.0, pinned commit) ==='
hermes --version

echo '=== Applying tools overlay (NDJSON patch — site-packages, non-editable install) ==='
cp /root/tools_overlay/*.py /opt/hermes/.venv/lib/python3.13/site-packages/tools/

echo '=== Configuring model: {provider}/{model} ==='
mkdir -p /home/hermes/.hermes
cat > /home/hermes/.hermes/config.yaml << 'HERMESCFG'
model:
  default: {model}
  provider: {provider}
  base_url: {OPENCODE_GO_BASE_URL}
  api_mode: chat_completions
HERMESCFG
chown -R hermes:hermes /home/hermes/.hermes 2>/dev/null || true

echo '=== Installing qodercli {QODERCLI_VERSION} ==='
npm install -g @qoder-ai/qodercli@{QODERCLI_VERSION} 2>/dev/null
qodercli --version

echo '=== Installing qodercli skill ({condition} variant) ==='
mkdir -p /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli
cp /root/skill/SKILL.md /home/hermes/.hermes/skills/autonomous-ai-agents/qodercli/SKILL.md

echo '=== Setting up workspace ==='
cd /root/workspace
git status >/dev/null 2>&1 || {{ git init -q && git add -A && git commit -q -m "fixture baseline" --allow-empty 2>/dev/null || true; }}

echo '=== Running Gap3 friction task ==='
hermes chat -q '{prompt_escaped}' -Q --yolo -m {model} 2>&1 | tee /root/output/hermes_stdout.txt || true
HERMES_EXIT=$?

echo '=== Exporting workspace diff ==='
cd /root/workspace && git diff --stat > /root/output/git_diff.txt 2>/dev/null || true
cd /root/workspace && git diff > /root/output/git_diff_full.patch 2>/dev/null || true

echo '=== Exporting session ==='
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/hermes/.hermes/state.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
cp /home/hermes/.hermes/state.db /root/output/state.db
echo "hermes_exit=$HERMES_EXIT" >> /root/output/run_metadata.txt
echo "completed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /root/output/run_metadata.txt
echo "experiment=gap3" >> /root/output/run_metadata.txt
echo "adaptation={condition}" >> /root/output/run_metadata.txt
echo "run_num={run_num}" >> /root/output/run_metadata.txt
echo "model={model}" >> /root/output/run_metadata.txt
echo "provider={provider}" >> /root/output/run_metadata.txt
echo "container_image={CONTAINER_IMAGE}" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
"""


def run_gap3_arm(
    condition: str,
    run_num: int,
    secrets: dict,
    timeout: int,
    dry_run: bool,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
) -> bool:
    """Run a single Gap 3 arm (treatment or control)."""
    run_id = f"P8-gap3-friction-{condition}-{run_num}"
    container_name = f"cta-gap3-{run_id}"
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    classification = classify_session(run_dir)
    if classification["validity"] == "valid":
        print(f"[GAP3] SKIP {run_id}: valid session ({classification['msg_count']} msgs)")
        return True
    if classification["validity"] == "behavioral_failure":
        print(f"[GAP3] SKIP {run_id}: behavioral failure ({classification['reason']})")
        return False

    # Prepare workspace
    workspace_dir = run_dir / "workspace"
    if not (workspace_dir / ".git").exists():
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(FIXTURE_DIR, workspace_dir)
        subprocess.run(["git", "init", "-q"], cwd=workspace_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=workspace_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "fixture baseline", "--allow-empty"],
            cwd=workspace_dir, capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "CTA", "GIT_AUTHOR_EMAIL": "cta@local",
                 "GIT_COMMITTER_NAME": "CTA", "GIT_COMMITTER_EMAIL": "cta@local"},
        )

    hermes_home_dir = run_dir / "hermes_home"
    hermes_home_dir.mkdir(parents=True, exist_ok=True)
    for stale in hermes_home_dir.glob("state.db*"):
        stale.unlink()

    # Write run script
    script = generate_gap3_run_script(condition, run_num, model=model, provider=provider)
    script_path = run_dir / "run.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)

    # Determine which SKILL.md to mount
    skill_source = SKILL_TREATMENT if condition == "treatment" else SKILL_CONTROL
    if not skill_source.exists():
        print(f"[GAP3] ERROR: skill source not found: {skill_source}")
        return False

    # Build container command
    cmd = [
        "container", "run", "--name", container_name,
        "-c", "4", "-m", "2G",
        "-e", f"OPENCODE_GO_API_KEY={secrets['OPENCODE_API_KEY']}",
        "-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}",
        "--mount", f"type=bind,source={FIXTURE_DIR},target=/root/fixture,readonly",
        "--mount", f"type=bind,source={run_dir},target=/root/output",
        "--mount", f"type=bind,source={workspace_dir},target=/root/workspace",
        "--mount", f"type=bind,source={hermes_home_dir},target=/home/hermes/.hermes",
        "--mount", f"type=bind,source={skill_source.parent},target=/root/skill,readonly",
    ]

    # Tools overlay for NDJSON friction display
    tools_overlay_dir = PROJECT_ROOT / "data" / "ndjson_overlay"
    if tools_overlay_dir.exists():
        cmd += ["--mount", f"type=bind,source={tools_overlay_dir},target=/root/tools_overlay,readonly"]

    cmd += ["--entrypoint", "/bin/sh", CONTAINER_IMAGE, "/root/output/run.sh"]

    if dry_run:
        print(f"[DRY RUN] {run_id}")
        print(f"  container: {container_name}")
        print(f"  skill: {skill_source}")
        print(f"  output: {run_dir}")
        print(f"  command: {' '.join(cmd[:12])}...")
        return True

    # Clean up any stale container
    subprocess.run(["container", "stop", container_name], capture_output=True, timeout=30)
    subprocess.run(["container", "rm", container_name], capture_output=True, timeout=30)

    max_attempts = 2
    elapsed = 0.0
    exit_code = -1
    failure_type = None

    for attempt in range(1, max_attempts + 1):
        attempt_timeout = timeout if attempt == 1 else int(timeout * 1.5)
        print(f"[GAP3] Starting {run_id} (attempt {attempt}/{max_attempts}, timeout={attempt_timeout}s)...")
        start = time.time()

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=attempt_timeout)
            elapsed = time.time() - start
            exit_code = proc.returncode
            print(f"[GAP3] {run_id} finished in {elapsed:.1f}s (exit={exit_code})")
            if exit_code != 0:
                stderr_tail = proc.stderr[-500:] if proc.stderr else ""
                print(f"  stderr: {stderr_tail}")
                failure_type = "api_error" if any(c in stderr_tail for c in ("400", "402", "Upstream")) else "crash"
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            failure_type = "timeout"
            print(f"[GAP3] {run_id} TIMED OUT after {elapsed:.1f}s (attempt {attempt})")
            subprocess.run(["container", "stop", container_name], capture_output=True, timeout=30)
        finally:
            subprocess.run(["container", "rm", container_name], capture_output=True, timeout=30)

        if exit_code == 0:
            break
        if attempt < max_attempts and failure_type in ("timeout", "api_error"):
            print(f"[GAP3] {run_id} retrying ({failure_type})...")
            time.sleep(5)

    result = {
        "run_id": run_id,
        "experiment": "gap3",
        "adaptation": condition,
        "run_num": run_num,
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 1),
        "container_name": container_name,
        "container_image": CONTAINER_IMAGE,
        "failure_type": failure_type,
        "attempts": attempt,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))

    # Export workspace diff if the container didn't
    if workspace_dir.exists() and not (run_dir / "git_diff.txt").exists():
        diff_stat = subprocess.run(
            ["git", "diff", "--stat"], cwd=workspace_dir, capture_output=True, text=True
        )
        if diff_stat.stdout.strip():
            (run_dir / "git_diff.txt").write_text(diff_stat.stdout)
            diff_full = subprocess.run(
                ["git", "diff"], cwd=workspace_dir, capture_output=True, text=True
            )
            (run_dir / "git_diff_full.patch").write_text(diff_full.stdout)

    post_class = classify_session(run_dir)
    (run_dir / "classification.json").write_text(json.dumps(post_class, indent=2))
    print(f"[GAP3] {run_id} validity: {post_class['validity']} ({post_class['reason']})")

    return exit_code == 0 and post_class["validity"] == "valid"


def run_gap3_pair(
    run_num: int,
    secrets: dict,
    dry_run: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    condition: str = "both",
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
) -> dict:
    """Run the Gap 3 paired experiment (treatment + control)."""
    # Preflight checks
    elts, headroom = check_kalloc_headroom()
    if headroom >= 0 and headroom < KALLOC_MIN_HEADROOM:
        print(f"[GAP3] ABORT: kalloc.1024 headroom {headroom} < {KALLOC_MIN_HEADROOM} (reboot needed)")
        return {"error": "kalloc_headroom", "headroom": headroom}
    if headroom >= 0:
        print(f"[GAP3] kalloc.1024: {elts} elements, headroom {headroom}")

    if not dry_run:
        print("[GAP3] Checking provider connectivity...")
        ok, msg = preflight_api_check(secrets, model=model)
        print(f"[GAP3] {msg}")
        if not ok:
            return {"error": "preflight_failed", "detail": msg}

    conditions = ["treatment", "control"] if condition == "both" else [condition]
    results = {}

    for cond in conditions:
        success = run_gap3_arm(cond, run_num, secrets, timeout, dry_run, model=model, provider=provider)
        results[cond] = success

        # Re-check kalloc between arms
        if cond == "treatment" and "control" in conditions:
            elts, headroom = check_kalloc_headroom()
            if headroom >= 0 and headroom < KALLOC_MIN_HEADROOM:
                print(f"[GAP3] ABORT control arm: kalloc headroom {headroom} < {KALLOC_MIN_HEADROOM}")
                results["control"] = None
                break

    return results


def main():
    parser = argparse.ArgumentParser(description="Gap 3 ±Adaptation Paired Experiment")
    parser.add_argument("--run-num", type=int, default=1, help="Run number for this pair")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Per-session timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--condition", choices=["both", "treatment", "control"], default="both",
                        help="Which arm(s) to run")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets()

    print("Gap 3 ±Adaptation Paired Experiment")
    print(f"  Condition: {args.condition}")
    print(f"  Run number: {args.run_num}")
    print(f"  Model: {args.provider}/{args.model}")
    print(f"  Timeout: {args.timeout}s")
    print(f"  Container image: {CONTAINER_IMAGE}")
    print(f"  Treatment skill: {SKILL_TREATMENT}")
    print(f"  Control skill: {SKILL_CONTROL}")
    print(f"  Output: {OUTPUT_DIR}")
    print()

    # Validate skill sources exist
    for label, path in [("treatment", SKILL_TREATMENT), ("control", SKILL_CONTROL)]:
        if not path.exists():
            print(f"[GAP3] WARNING: {label} skill not found at {path}")
            if not args.dry_run:
                print(f"[GAP3] ABORT: cannot run without skill files")
                sys.exit(1)

    results = run_gap3_pair(
        run_num=args.run_num,
        secrets=secrets,
        dry_run=args.dry_run,
        timeout=args.timeout,
        condition=args.condition,
        model=args.model,
        provider=args.provider,
    )

    print(f"\n{'='*50}")
    print("GAP3 RESULTS")
    print(f"{'='*50}")
    if "error" in results:
        print(f"  ABORTED: {results['error']} — {results.get('detail', '')}")
        sys.exit(1)

    for cond, success in results.items():
        run_id = f"P8-gap3-friction-{cond}-{args.run_num}"
        run_dir = OUTPUT_DIR / run_id
        class_file = run_dir / "classification.json"
        validity = "?"
        if class_file.exists():
            validity = json.loads(class_file.read_text()).get("validity", "?")
        status = "VALID" if success else (validity.upper() if success is not None else "SKIPPED")
        print(f"  {run_id}: {status}")

    progress_file = OUTPUT_DIR / "gap3_progress.json"
    existing = []
    if progress_file.exists():
        existing = json.loads(progress_file.read_text())
    existing.append({
        "run_num": args.run_num,
        "condition": args.condition,
        "results": {k: v for k, v in results.items() if k != "error"},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    progress_file.write_text(json.dumps(existing, indent=2))


if __name__ == "__main__":
    main()
