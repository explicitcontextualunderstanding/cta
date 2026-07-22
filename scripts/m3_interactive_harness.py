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
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
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


KALLOC_THRESHOLD = 3_000_000
KALLOC_MIN_HEADROOM = 200_000

# OpenCode Go: 1,350 req/5hr. Budget conservatively to leave headroom for
# retries, health checks, and unexpectedly chatty sessions.
RATE_LIMIT_BUDGET = 900


def check_kalloc_headroom() -> tuple[int, int]:
    """Return (current_elements, headroom) for data.kalloc.1024 zone."""
    try:
        out = subprocess.run(["zprint"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if line.startswith("data.kalloc.1024"):
                parts = line.split()
                if len(parts) >= 7:
                    elts = int(parts[6])
                    return elts, KALLOC_THRESHOLD - elts
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return -1, -1


def load_secrets() -> dict:
    hermes_env = Path.home() / ".hermes" / "profiles" / "coding" / ".env"
    opencode_key = ""
    if hermes_env.exists():
        for line in hermes_env.read_text().splitlines():
            if line.startswith("OPENCODE_API_KEY="):
                opencode_key = line.split("=", 1)[1].strip()
    if not opencode_key:
        opencode_key = (ENCLAVE / "opencode_primary.txt").read_text().strip()
    return {
        "OPENCODE_API_KEY": opencode_key,
        "QODER_PERSONAL_ACCESS_TOKEN": (ENCLAVE / "qoder.txt").read_text().strip(),
    }


DEFAULT_MODEL = "kimi-k2.7-code"
DEFAULT_PROVIDER = "opencode-go"
OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"

# Failure patterns in hermes stdout that indicate the session did not produce
# valid behavioral evidence (infrastructure failure, not skill effect).
STDOUT_FAILURE_PATTERNS = [
    (r"HTTP 40[02]", "api_error"),
    (r"HTTP 429", "rate_limited"),
    (r"Upstream request failed", "api_error"),
    (r"No usable credentials", "auth_failure"),
    (r"tool budget was exhausted", "budget_exhausted"),
    (r"ECONNREFUSED|ETIMEDOUT|ENOTFOUND", "network_error"),
]


def preflight_api_check(secrets: dict, model: str = DEFAULT_MODEL) -> tuple[bool, str]:
    """Hit the provider endpoint with a minimal request to verify connectivity
    and check rate limit headers before committing to a long batch.

    Returns (ok, message). If not ok, the caller should abort.
    """
    url = f"{OPENCODE_GO_BASE_URL}/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secrets['OPENCODE_API_KEY']}",
            "User-Agent": "cta-harness/1.0 (preflight health check)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            remaining = resp.headers.get("x-ratelimit-remaining-requests", "?")
            return True, f"Provider OK. Rate limit remaining: {remaining}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            reset = e.headers.get("x-ratelimit-reset", "unknown")
            return False, f"RATE LIMITED (429). Reset: {reset}. Do not run sessions."
        if e.code == 402:
            return False, "CREDITS EXHAUSTED (402). Do not run sessions."
        if e.code == 401:
            return False, "AUTH FAILED (401). Check OPENCODE_API_KEY."
        return False, f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"CONNECTIVITY FAILURE: {e}"


def classify_session(run_dir: Path) -> dict:
    """Classify a completed session's validity from its artifacts.

    Returns a dict with:
      validity: "valid" | "infra_failure" | "behavioral_failure" | "api_error" | "incomplete"
      reason: human-readable explanation
      msg_count: message count (from state.db or stdout estimate)
      recoverable: bool — whether stdout contains usable evidence
    """
    state_db = run_dir / "state.db"
    stdout_file = run_dir / "hermes_stdout.txt"
    result_file = run_dir / "result.json"

    result = {"validity": "incomplete", "reason": "", "msg_count": 0, "recoverable": False}

    # Check result.json for container-level failure
    if result_file.exists():
        try:
            r = json.loads(result_file.read_text())
            if r.get("exit_code") == 128:
                result["validity"] = "infra_failure"
                result["reason"] = f"Container crash (exit 128, {r.get('elapsed_seconds', '?')}s)"
                return result
        except (json.JSONDecodeError, KeyError):
            pass

    # Check state.db
    if state_db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(state_db))
            msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            conn.close()
            result["msg_count"] = msg_count
            if msg_count <= 2:
                result["validity"] = "infra_failure"
                result["reason"] = f"Degenerate session ({msg_count} messages)"
                return result
        except Exception as e:
            result["validity"] = "infra_failure"
            result["reason"] = f"state.db unreadable: {e}"
            return result

        # state.db exists — check stdout for mid-session failure patterns
        if stdout_file.exists():
            content = stdout_file.read_text()
            for pattern, failure_type in STDOUT_FAILURE_PATTERNS:
                if re.search(pattern, content):
                    if failure_type in ("api_error", "rate_limited", "network_error", "auth_failure"):
                        result["validity"] = "api_error"
                        result["reason"] = f"Session hit {failure_type} (pattern: {pattern})"
                        return result
                    if failure_type == "budget_exhausted":
                        result["validity"] = "behavioral_failure"
                        result["reason"] = "Model exhausted tool budget (infrastructure limit, not skill effect)"
                        return result

        result["validity"] = "valid"
        result["reason"] = f"{result['msg_count']} messages, no failure patterns"
        return result

    # No state.db — check if stdout has recoverable evidence
    if stdout_file.exists():
        content = stdout_file.read_text()
        if len(content) > 100:
            result["validity"] = "infra_failure"
            result["recoverable"] = True
            result["msg_count"] = _estimate_msgs_from_stdout(content)
            result["reason"] = f"No state.db but stdout recoverable (~{result['msg_count']} msgs estimated)"
            return result

    result["validity"] = "infra_failure"
    result["reason"] = "No state.db, no recoverable stdout"
    return result


def _estimate_msgs_from_stdout(content: str) -> int:
    """Rough estimate of message count from stdout content length and structure."""
    session_match = re.search(r"session_id:\s*\S+", content)
    lines = content.strip().splitlines()
    return len([l for l in lines if l.strip()]) // 2


def recover_from_stdout(run_dir: Path) -> dict | None:
    """Extract structured evidence from hermes_stdout.txt when state.db is missing.

    Returns a dict with parsed session info, or None if unrecoverable.
    """
    stdout_file = run_dir / "hermes_stdout.txt"
    if not stdout_file.exists():
        return None
    content = stdout_file.read_text()
    if len(content) < 100:
        return None

    recovered = {
        "source": "stdout_recovery",
        "session_id": None,
        "line_count": len(content.strip().splitlines()),
        "has_qodercli_launch": "qodercli -i" in content or "qodercli -i" in content.replace("\u2019", "'"),
        "has_trust_dialog": "trust" in content.lower() or "folder trust" in content.lower(),
        "has_test_results": bool(re.search(r"\d+ passed", content)),
        "failure_patterns": [],
    }

    session_match = re.search(r"session_id:\s*(\S+)", content)
    if session_match:
        recovered["session_id"] = session_match.group(1)

    for pattern, failure_type in STDOUT_FAILURE_PATTERNS:
        if re.search(pattern, content):
            recovered["failure_patterns"].append(failure_type)

    return recovered


def generate_run_script(condition: str, run_num: int, model: str = DEFAULT_MODEL, provider: str = DEFAULT_PROVIDER, tag: str = "", prompt: str = "", tools_overlay: bool = False) -> str:
    run_label = f"P1-interactive-{tag}-{condition}-{run_num}" if tag else f"P1-interactive-{condition}-{run_num}"
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

    overlay_step = ""
    if tools_overlay:
        overlay_step = """
echo '=== Applying tools overlay (NDJSON patch) ==='
cp /root/tools_overlay/*.py /opt/hermes/tools/
"""

    effective_prompt = prompt or M3_PROMPT
    prompt_escaped = effective_prompt.replace("'", "'\\''")

    return f"""#!/bin/sh
set -e

echo '=== CTA M3 Run: {run_label} ==='
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /root/output/run_metadata.txt

echo '=== Upgrading hermes to v0.19.0 ==='
cd /opt/hermes
git fetch origin {HERMES_COMMIT} --depth=1 2>/dev/null
git checkout -f {HERMES_COMMIT} 2>/dev/null
{overlay_step}uv pip install . --python /opt/hermes/.venv/bin/python3 --quiet 2>/dev/null
hermes --version

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

{skill_setup}

echo '=== Setting up workspace ==='
cd /root/workspace
git status >/dev/null 2>&1 || {{ git init -q && git add -A && git commit -q -m "fixture baseline" --allow-empty 2>/dev/null || true; }}

echo '=== Running interactive-mode task ==='
hermes chat -q '{prompt_escaped}' -Q --yolo --provider {provider} -m {model} 2>&1 | tee /root/output/hermes_stdout.txt || true
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
echo "task_id=P1-interactive" >> /root/output/run_metadata.txt
echo "condition={condition}" >> /root/output/run_metadata.txt
echo "run_num={run_num}" >> /root/output/run_metadata.txt
echo "model={model}" >> /root/output/run_metadata.txt
echo "provider={provider}" >> /root/output/run_metadata.txt
echo '=== RUN COMPLETE ==='
"""


def run_container(condition: str, run_num: int, secrets: dict, timeout: int, dry_run: bool, provide_token: bool = True, model: str = DEFAULT_MODEL, provider: str = DEFAULT_PROVIDER, tag: str = "", prompt: str = "", tools_overlay: str = "") -> bool:
    run_id = f"P1-interactive-{tag}-{condition}-{run_num}" if tag else f"P1-interactive-{condition}-{run_num}"
    container_name = f"cta-m3-{run_id}"
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    classification = classify_session(run_dir)
    if classification["validity"] == "valid":
        print(f"[M3] SKIP {run_id}: valid session ({classification['msg_count']} msgs)")
        return True
    if classification["validity"] == "behavioral_failure":
        print(f"[M3] SKIP {run_id}: behavioral failure, not re-runnable ({classification['reason']})")
        return False
    if classification["validity"] in ("infra_failure", "api_error", "incomplete"):
        if classification["recoverable"]:
            recovered = recover_from_stdout(run_dir)
            (run_dir / "recovered_evidence.json").write_text(json.dumps(recovered, indent=2))
            print(f"[M3] {run_id}: recovered stdout evidence → recovered_evidence.json")
        if (run_dir / "state.db").exists() and classification["validity"] == "api_error":
            print(f"[M3] SKIP {run_id}: has state.db but hit API error ({classification['reason']})")
            return False
        print(f"[M3] {run_id}: eligible for re-run ({classification['reason']})")

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

    script = generate_run_script(condition, run_num, model=model, provider=provider, tag=tag, prompt=prompt, tools_overlay=bool(tools_overlay))
    script_path = run_dir / "run.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)

    cmd = [
        "container", "run", "--name", container_name,
        "-c", "4", "-m", "2G",
        "-e", f"OPENCODE_GO_API_KEY={secrets['OPENCODE_API_KEY']}",
    ]
    if provide_token:
        cmd += ["-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}"]

    cmd += [
        "--mount", f"type=bind,source={FIXTURE_DIR},target=/root/fixture,readonly",
        "--mount", f"type=bind,source={run_dir},target=/root/output",
        "--mount", f"type=bind,source={workspace_dir},target=/root/workspace",
    ]
    if condition == "treatment":
        resolved_skill = SKILL_PATH.resolve()
        cmd += ["--mount", f"type=bind,source={resolved_skill.parent},target=/root/skill,readonly"]
    if tools_overlay:
        cmd += ["--mount", f"type=bind,source={Path(tools_overlay).resolve()},target=/root/tools_overlay,readonly"]

    cmd += ["--entrypoint", "/bin/sh", CONTAINER_IMAGE, "/root/output/run.sh"]

    if dry_run:
        print(f"[DRY RUN] {run_id}")
        print(f"  container: {container_name}")
        print(f"  output: {run_dir}")
        print(f"  command: {' '.join(cmd[:10])}...")
        return True

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from cta.preflight import run_preflight
    preflight = run_preflight(run_dir)
    if not preflight.all_passed:
        print(f"[M3] ABORT {run_id}: preflight pollution check failed:")
        for c in preflight.failures:
            print(f"  - {c.name}: {c.detail}")
        return False

    elts, headroom = check_kalloc_headroom()
    if headroom >= 0 and headroom < KALLOC_MIN_HEADROOM:
        print(f"[M3] ABORT {run_id}: kalloc.1024 headroom {headroom} < {KALLOC_MIN_HEADROOM} (reboot imminent)")
        return False
    if headroom >= 0:
        print(f"[M3] kalloc.1024: {elts} elements, headroom {headroom}")

    max_attempts = 2
    subprocess.run(["container", "stop", container_name], capture_output=True, timeout=30)
    subprocess.run(["container", "rm", container_name], capture_output=True, timeout=30)
    for attempt in range(1, max_attempts + 1):
        attempt_timeout = timeout if attempt == 1 else int(timeout * 1.5)
        print(f"[M3] Starting {run_id} (attempt {attempt}/{max_attempts}, timeout={attempt_timeout}s)...")
        start = time.time()
        exit_code = -1
        failure_type = None

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=attempt_timeout)
            elapsed = time.time() - start
            exit_code = proc.returncode
            print(f"[M3] {run_id} finished in {elapsed:.1f}s (exit={exit_code})")
            if exit_code != 0:
                stderr_tail = proc.stderr[-500:] if proc.stderr else ""
                print(f"  stderr: {stderr_tail}")
                if "400" in stderr_tail or "402" in stderr_tail or "Upstream" in stderr_tail:
                    failure_type = "api_error"
                else:
                    failure_type = "crash"
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            failure_type = "timeout"
            print(f"[M3] {run_id} TIMED OUT after {elapsed:.1f}s (attempt {attempt})")
            subprocess.run(["container", "stop", container_name], capture_output=True, timeout=30)
        finally:
            subprocess.run(["container", "rm", container_name], capture_output=True, timeout=30)

        if exit_code == 0:
            break
        if attempt < max_attempts and failure_type in ("timeout", "api_error"):
            print(f"[M3] {run_id} retrying ({failure_type})...")
            time.sleep(5)

    result = {
        "run_id": run_id,
        "task_id": "P1-interactive",
        "condition": condition,
        "run_num": run_num,
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 1),
        "container_name": container_name,
        "failure_type": failure_type,
        "attempts": attempt,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))

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
    print(f"[M3] {run_id} validity: {post_class['validity']} ({post_class['reason']})")

    return exit_code == 0 and post_class["validity"] == "valid"


def main():
    global OUTPUT_DIR
    parser = argparse.ArgumentParser(description="M3 Interactive-Mode Capture")
    parser.add_argument("--condition", choices=["treatment", "baseline", "both"], default="both")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--baseline-token", action="store_true",
                        help="Provide QODER token to baseline (Option B: isolates skill as only variable)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Inference model (default: {DEFAULT_MODEL})")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER,
                        help=f"Inference provider (default: {DEFAULT_PROVIDER})")
    parser.add_argument("--tag", default="",
                        help="Tag for run IDs to distinguish model batches (e.g. 'kimi')")
    parser.add_argument("--start-run", type=int, default=1,
                        help="Starting run number (for resuming after interruption)")
    parser.add_argument("--max-batch", type=int, default=3,
                        help="Max sessions per invocation before forcing a health check pause (default: 3)")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip the API preflight check (for dry runs or when provider is known-good)")
    parser.add_argument("--config", type=str, default="",
                        help="Path to YAML/JSON audit config (pulls task prompts from tasks: block)")
    parser.add_argument("--task", type=str, default="",
                        help="Task ID from config tasks: block to use as the prompt (e.g. P1, N1)")
    parser.add_argument("--tools-overlay", type=str, default="",
                        help="Directory containing patched Hermes tool .py files to overlay into the container (e.g. NDJSON-modified terminal_tool.py + process_registry.py)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    secrets = load_secrets()

    config_prompt = ""
    if args.config:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))
        from cta.audit_config import load_config
        cfg = load_config(Path(args.config))
        OUTPUT_DIR = PROJECT_ROOT / cfg.captures_dir
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if args.task:
            match = [t for t in cfg.tasks if t.id == args.task]
            if not match:
                print(f"[ERROR] Task '{args.task}' not found in {args.config}")
                print(f"  Available: {[t.id for t in cfg.tasks]}")
                sys.exit(1)
            config_prompt = match[0].prompt.replace("{skill}", cfg.skill_name)
            print(f"[CONFIG] Using task {args.task} from {args.config}")
        elif cfg.tasks:
            config_prompt = cfg.tasks[0].prompt.replace("{skill}", cfg.skill_name)
            print(f"[CONFIG] Using first task ({cfg.tasks[0].id}) from {args.config}")

    effective_prompt = config_prompt or M3_PROMPT
    conditions = ["treatment", "baseline"] if args.condition == "both" else [args.condition]

    print(f"M3 Interactive-Mode Capture")
    print(f"  Conditions: {conditions}")
    print(f"  Model: {args.provider}/{args.model}")
    print(f"  Runs per condition: {args.runs}")
    print(f"  Timeout: {args.timeout}s")
    print(f"  Max batch: {args.max_batch}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Tag: {args.tag or '(none)'}")
    print(f"  Baseline token: {'YES (Option B)' if args.baseline_token else 'NO (Option A)'}")
    print(f"  Prompt: {effective_prompt[:80]}...")
    print()

    # GUARDRAIL: Pre-flight API health check
    if not args.dry_run and not args.skip_preflight:
        print("[PREFLIGHT] Checking provider connectivity and rate limits...")
        ok, msg = preflight_api_check(secrets, model=args.model)
        print(f"[PREFLIGHT] {msg}")
        if not ok:
            print("[PREFLIGHT] ABORTING. Fix the provider issue before running sessions.")
            sys.exit(1)
        print()

    results = []
    progress_file = OUTPUT_DIR / "progress.json"
    end_run = args.start_run + args.runs - 1
    sessions_this_batch = 0
    estimated_api_calls = 0

    for condition in conditions:
        for run_num in range(args.start_run, end_run + 1):
            # GUARDRAIL: Inter-session health gate every max_batch sessions
            if sessions_this_batch > 0 and sessions_this_batch % args.max_batch == 0:
                print(f"\n[HEALTH GATE] {sessions_this_batch} sessions completed. Checking system health...")
                print(f"[HEALTH GATE] Estimated API calls this batch: {estimated_api_calls}/{RATE_LIMIT_BUDGET}")
                if estimated_api_calls >= RATE_LIMIT_BUDGET:
                    print(f"[HEALTH GATE] ABORT: API budget exhausted ({estimated_api_calls} >= {RATE_LIMIT_BUDGET}).")
                    print(f"[HEALTH GATE] Wait for the 5hr rate limit window to reset before continuing.")
                    break
                elts, headroom = check_kalloc_headroom()
                if headroom >= 0 and headroom < KALLOC_MIN_HEADROOM:
                    print(f"[HEALTH GATE] ABORT: kalloc headroom {headroom} < {KALLOC_MIN_HEADROOM}. Reboot needed.")
                    break
                if headroom >= 0:
                    print(f"[HEALTH GATE] kalloc OK (headroom {headroom})")
                if not args.skip_preflight:
                    ok, msg = preflight_api_check(secrets, model=args.model)
                    if not ok:
                        print(f"[HEALTH GATE] ABORT: {msg}")
                        break
                    print(f"[HEALTH GATE] {msg}")
                print()

            provide_token = True if condition == "treatment" else args.baseline_token
            ok = run_container(condition, run_num, secrets, args.timeout, args.dry_run, provide_token,
                               model=args.model, provider=args.provider, tag=args.tag, prompt=effective_prompt,
                               tools_overlay=args.tools_overlay)
            results.append({"condition": condition, "run": run_num, "success": ok})
            progress_file.write_text(json.dumps(results, indent=2))
            sessions_this_batch += 1

            # Track API consumption: message count ≈ API calls for the session
            tag_prefix = f"{args.tag}-" if args.tag else ""
            run_id = f"P1-interactive-{tag_prefix}{condition}-{run_num}"
            class_file = OUTPUT_DIR / run_id / "classification.json"
            if class_file.exists():
                msg_count = json.loads(class_file.read_text()).get("msg_count", 0)
                estimated_api_calls += msg_count

    print(f"\n{'='*50}")
    print("M3 CAPTURE SUMMARY")
    print(f"{'='*50}")
    failures = []
    for r in results:
        tag_prefix = f"{args.tag}-" if args.tag else ""
        run_id = f"P1-interactive-{tag_prefix}{r['condition']}-{r['run']}"
        run_dir = OUTPUT_DIR / run_id
        class_file = run_dir / "classification.json"
        validity = "?"
        if class_file.exists():
            validity = json.loads(class_file.read_text()).get("validity", "?")
        status = "VALID" if r["success"] else validity.upper()
        print(f"  {run_id}: {status}")
        if not r["success"]:
            failures.append(r)

    if failures:
        print(f"\n  FAILED/INVALID SESSIONS ({len(failures)}):")
        for f in failures:
            tag_prefix = f"{args.tag}-" if args.tag else ""
            run_id = f"P1-interactive-{tag_prefix}{f['condition']}-{f['run']}"
            run_dir = OUTPUT_DIR / run_id
            class_file = run_dir / "classification.json"
            reason = ""
            if class_file.exists():
                reason = json.loads(class_file.read_text()).get("reason", "")
            print(f"    {run_id}: {reason}")
        print(f"\n  Re-run eligible sessions with:")
        for f in failures:
            print(f"    python scripts/m3_interactive_harness.py --condition {f['condition']} --runs 1 --baseline-token --tag {args.tag} --start-run {f['run']}")


if __name__ == "__main__":
    main()
