# Container Mounts & Secrets Reference

How CTA harnesses inject secrets and mount volumes into Apple Container VMs.
Includes the crash-resilience evolution from M2 (ephemeral) to M3 (persistent).

---

## Quick Reference: What Survives a Crash?

| Evidence | Host location | Harness | Survives kalloc crash? | Recovery mechanism |
|----------|--------------|---------|----------------------|-------------------|
| File modifications (git diff) | `run_dir/workspace/` | M3 | **Yes** | `git diff` on host |
| Session record (state.db + WAL) | `run_dir/hermes_home/` | M3 | **Yes** | `classify_session()` auto-checkpoints |
| Hermes stdout (rendered) | `run_dir/hermes_stdout.txt` | M2+M3 | **Yes** | `recover_from_stdout()` |
| NDJSON stream (structured) | `run_dir/raw.ndjson` or standalone | P8 | **Yes** | Line-by-line, always valid |
| Clean-exit state.db copy | `run_dir/state.db` | M2+M3 | No (export step) | M2: only path (lost on crash). M3: convenience; hermes_home is canonical |
| Workspace (in-container) | VM disk | M2 | **No** | Lost — use M3 |
| Config + skills | `run_dir/hermes_home/` | M3 | **Yes** | Reproducible from run.sh anyway |
| API keys | Process env only | All | N/A | Never on disk; re-injected per run |

**Rule of thumb:** If it's on a virtiofs bind mount, it survives. If it's on the
VM disk image, it dies with the container. M3 mounts everything that matters.

---

## The macOS Crash Problem

Apple Container on macOS has a kernel memory leak: each container start/stop
cycle leaks ~100k elements in the `data.kalloc.1024` zone. After ~20 containers,
the zone fills (threshold: 3M elements) and the next container crashes with exit
128. The only fix is a host reboot.

This means any batch of >15-20 container runs WILL hit a crash. The harness must
treat crashes as expected, not exceptional.

**Evidence:** 8/20 kimi-k2.7-code sessions failed kalloc.1024 (Plan 2 Phase 0).
Failure was random w.r.t. condition (5 treatment, 3 baseline) — no selection bias.

---

## Crash-Resilience Evolution

### M2 (capture_harness.py) — Ephemeral, No Recovery

- Workspace created IN container (`cp -r /root/fixture /root/workspace`)
- If container crashes before run.sh completes: **all evidence lost**
- No retry, no preflight, no skip logic
- WAL checkpoint only runs if hermes exits cleanly
- Result: any crash = wasted API spend with zero evidence

### M3 (m3_interactive_harness.py) — Persistent, Crash-Tolerant

Key design changes driven by the kalloc.1024 experience:

| Mechanism | What it does | Plan reference |
|-----------|-------------|----------------|
| **Workspace bind mount** | `data/m3_captures/<run_id>/workspace/` pre-created on host, mounted rw. File modifications survive ANY exit path (crash, timeout, kill). | Plan 1 §Known Caveats #8 |
| **Hermes home bind mount** | `data/m3_captures/<run_id>/hermes_home/` mounted at `/home/hermes/.hermes`. state.db + WAL persist on host in real-time — no export step needed for crash survival. `classify_session()` auto-checkpoints on recovery. | Added 2026-07-21 |
| **WAL checkpoint** | `PRAGMA wal_checkpoint(TRUNCATE)` before copying state.db. Hermes uses SQLite WAL mode — without this, state.db is 4KB (empty) and data lives in state.db-wal. | Plan 1 §M2 Infrastructure |
| **kalloc headroom check** | `zprint` → parse `data.kalloc.1024` element count. Abort if headroom < 200k. Prevents launching into a guaranteed crash. | Plan 2 Phase 0 hardening |
| **Session classification** | `classify_session()` inspects output dir artifacts → valid / infra_failure / behavioral_failure / api_error / incomplete. | m3_interactive_harness.py:141 |
| **Skip logic** | Valid sessions are NEVER re-run. Behavioral failures are never re-run. Only infra_failure/incomplete are eligible for retry. | m3_interactive_harness.py:349-364 |
| **stdout recovery** | `recover_from_stdout()` extracts structured evidence from hermes_stdout.txt when state.db is missing (tool calls, timing, errors). | m3_interactive_harness.py:224 |
| **2-attempt retry** | First attempt at normal timeout; retry at 1.5x timeout. Handles transient API errors. | m3_interactive_harness.py:429-433 |
| **Preflight pollution check** | `cta.preflight` module: 5 checks (state_db_absent, wal_absent, workspace_clean, no_result_json, no_skill_memory). Aborts if prior run left artifacts. | src/cta/preflight.py |
| **API preflight health check** | `preflight_api_check()` hits the provider's `/chat/completions` endpoint with a 1-token request before spending a full session. Catches 401/402/429 early. | m3_interactive_harness.py:102 |
| **Batch splitting** | Runs split into batches of 3-4 with reboot cycles between. `--start-run` flag namespaces runs to avoid overwriting. | Plan 1 §N=10 batch plan |

### P8 (Plan 8) — NDJSON Stream Persistence

Newest pattern: bypass state.db entirely for progress observation.

- `P8-phase2-prospective/`: 6 NDJSON session files (14-30KB each) captured from
  direct `qodercli --output-format stream-json` runs
- Plan 8 §Phase 1 proposes `_dump_raw_ndjson()` in process_registry.py to persist
  the raw stream to `/root/output/raw.ndjson` at session end
- NDJSON files are self-contained evidence — no WAL checkpoint needed, no SQLite
  dependency, crash-safe (written incrementally)

---

## Secret Sources (host-side)

| Secret | File | Used by | Env var in container |
|--------|------|---------|---------------------|
| OpenRouter API key | `~/.enclave/openrouter_key.txt` | `capture_harness.py` (M2) | `OPENROUTER_API_KEY` |
| OpenCode Go API key | `~/.enclave/opencode_primary.txt` (fallback: `~/.hermes/profiles/coding/.env` → `OPENCODE_API_KEY=`) | `m3_interactive_harness.py` (M3) | `OPENCODE_GO_API_KEY` |
| Qoder PAT | `~/.enclave/qoder.txt` | Both harnesses (treatment always; baseline only with `--baseline-token`) | `QODER_PERSONAL_ACCESS_TOKEN` |

Secrets are passed via `container run -e KEY=VALUE`. They exist only in the VM's
process environment — never written to disk inside the container.

**Provider status (2026-07-21):**
- OpenRouter: **EXHAUSTED** (HTTP 402 since M3 baseline attempts)
- OpenCode Go: **FUNDED** (kimi-k2.7-code, 1350 req/5hr)
- Qoder PAT: **ACTIVE** (starts `pt-5RI5...`)

---

## Secret Injection Logic

### capture_harness.py (M2, print-mode, OpenRouter)

```python
cmd = ["container", "run", "--name", name, "-c", "4", "-m", "2G",
       "-e", f"OPENROUTER_API_KEY={secrets['OPENROUTER_API_KEY']}"]
if condition == "treatment":
    cmd += ["-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}"]
```

### m3_interactive_harness.py (M3, interactive, OpenCode Go)

```python
cmd = ["container", "run", "--name", name, "-c", "4", "-m", "2G",
       "-e", f"OPENCODE_GO_API_KEY={secrets['OPENCODE_API_KEY']}"]
if provide_token:  # --baseline-token flag or treatment
    cmd += ["-e", f"QODER_PERSONAL_ACCESS_TOKEN={secrets['QODER_PERSONAL_ACCESS_TOKEN']}"]
```

### Secret loading (m3_interactive_harness.py:71-83)

```python
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
```

---

## Bind Mounts

### capture_harness.py (M2)

| Host path | Container path | Mode | Purpose |
|-----------|---------------|------|---------|
| `fixture/` | `/root/fixture` | readonly | Pristine task fixture (copied to /root/workspace in-container) |
| `data/m2_captures/<run_id>/` | `/root/output` | rw | state.db, hermes_stdout.txt, run_metadata.txt, result.json |
| Skill dir (treatment only) | `/root/skill` | readonly | SKILL.md parent dir (symlink-resolved) |

**M2 weakness:** workspace is created in-container from fixture. If the container
crashes before run.sh's export step, file modifications are lost.

### m3_interactive_harness.py (M3)

| Host path | Container path | Mode | Purpose |
|-----------|---------------|------|---------|
| `fixture/` | `/root/fixture` | readonly | Pristine task fixture |
| `data/m3_captures/<run_id>/` | `/root/output` | rw | state.db (clean-exit copy), hermes_stdout.txt, run_metadata.txt, run.sh |
| `data/m3_captures/<run_id>/workspace/` | `/root/workspace` | rw | Git-tracked working copy (**survives crashes**) |
| `data/m3_captures/<run_id>/hermes_home/` | `/home/hermes/.hermes` | rw | **Persistent Hermes state** — config.yaml, skills/, state.db + WAL (**survives crashes**) |
| Skill dir (treatment only) | `/root/skill` | readonly | SKILL.md parent dir (symlink-resolved) |
| `data/ndjson_overlay/` (optional) | `/root/tools_overlay` | readonly | NDJSON-patched terminal_tool.py + process_registry.py |

**M3 fix:** workspace is pre-created on host (`shutil.copytree` + `git init` +
`git commit`) BEFORE container launch. Bind-mounted rw. File modifications are
on the host filesystem at all times — a container crash loses nothing.

**hermes_home persistence (added 2026-07-21):** The `/home/hermes/.hermes`
directory (config, skills, and critically `state.db` + `state.db-wal`) is now
bind-mounted to `run_dir/hermes_home/` on the host. Previously, a kalloc crash
before run.sh's export step lost the canonical session record — the WAL
checkpoint + copy only runs on clean exit. Now `state.db` and its WAL are
written to the host filesystem in real-time by SQLite. On crash recovery,
`classify_session()` auto-detects `hermes_home/state.db`, checkpoints the WAL
in-place, and copies to `run_dir/state.db` for downstream analysis. No manual
`container export` + tar extraction needed.

### m4_harness.py (M4)

No containers. Runs qodercli locally via `pty.openpty()` (condition A) or
`subprocess.PIPE` (condition B). Uses `QODER_PERSONAL_ACCESS_TOKEN` from the
host environment directly.

---

## In-Container Setup Sequence (run.sh)

Both M2 and M3 follow this order:

1. Upgrade hermes: `git fetch origin <sha> --depth=1 && git checkout -f <sha> && uv pip install .`
2. (M3 only) Apply tools overlay: `cp /root/tools_overlay/*.py /opt/hermes/tools/`
3. Write `config.yaml` to `/home/hermes/.hermes/` (model, provider, base_url)
4. Install qodercli: `npm install -g @qoder-ai/qodercli@<version>`
5. Install/remove skill: `cp /root/skill/SKILL.md` (treatment) or `rm -rf` (baseline)
6. Init workspace: git init + commit fixture baseline (M2) or verify existing git (M3)
7. Run hermes: `hermes chat -q '<prompt>' -Q --yolo --provider <p> -m <m>`
8. Export: WAL checkpoint → `cp state.db /root/output/`
9. Export: `git diff --stat > /root/output/git_diff.txt`

**Critical:** Steps 8-9 only run if step 7 exits (cleanly or with error). A
kernel-level crash (kalloc.1024, exit 128) kills the VM before these steps
execute. With the hermes_home bind mount, `state.db` + WAL already persist on
the host — the export step (8) is now a convenience (produces a clean
checkpointed copy at `run_dir/state.db`), not the only survival path. The
workspace bind mount ensures git diff (step 9) can always run on the host.

---

## Key Differences: M2 vs M3

| Aspect | M2 (capture_harness) | M3 (m3_interactive_harness) |
|--------|---------------------|----------------------------|
| LLM provider | OpenRouter (claude-sonnet-4) | OpenCode Go (kimi-k2.7-code) |
| Workspace persistence | In-container (lost on crash) | Host bind mount (survives crash) |
| Hermes state (state.db) | In-container WAL, exported on clean exit only | Host bind mount (`hermes_home/`), real-time persistence, auto-recovery |
| Tools overlay | No | Optional (NDJSON patch) |
| Baseline token | Never provided | Optional (`--baseline-token`) |
| Preflight pollution | No | Yes (5 checks via cta.preflight) |
| API health check | No | Yes (1-token probe before full run) |
| kalloc check | No | Yes (aborts if headroom < 200k) |
| Retry | No | 2 attempts (1.5x timeout on retry) |
| Skip logic | No | Yes (classify → skip valid/behavioral_failure) |
| stdout recovery | No | Yes (extract evidence from hermes_stdout.txt) |
| Batch splitting | No | Yes (--start-run, reboot between batches) |

### Crash Recovery Paths

```
kalloc.1024 crash (exit 128) — VM destroyed
│
├── M2 (capture_harness.py)
│   │
│   ├── /root/workspace (VM disk) ............ LOST
│   ├── /home/hermes/.hermes/state.db ........ LOST
│   ├── /root/output/hermes_stdout.txt ....... SURVIVES (bind mount)
│   └── /root/output/state.db ................ LOST (export never ran)
│
│   Result: stdout scraping only. ~30% information recovery.
│   Action: re-run from scratch (wasted API spend).
│
└── M3 (m3_interactive_harness.py)
    │
    ├── /root/workspace → run_dir/workspace/ .. SURVIVES (bind mount)
    ├── /home/hermes/.hermes → run_dir/hermes_home/
    │   ├── state.db .......................... SURVIVES (bind mount)
    │   ├── state.db-wal ...................... SURVIVES (bind mount)
    │   ├── config.yaml ....................... SURVIVES
    │   └── skills/ ........................... SURVIVES
    ├── /root/output → run_dir/
    │   ├── hermes_stdout.txt ................. SURVIVES (tee'd during run)
    │   └── run.sh, run_metadata.txt .......... SURVIVES
    └── /root/output/state.db ................. NOT WRITTEN (export skipped)
         │
         ▼
    classify_session(run_dir):
      1. Detect hermes_home/state.db exists
      2. PRAGMA wal_checkpoint(TRUNCATE) on host
      3. Copy → run_dir/state.db
      4. Classify: valid / infra_failure / api_error
      5. If valid → SKIP (never re-run)
      6. If infra_failure → eligible for retry

    Result: 100% session record recovery. Zero manual intervention.
```

---

## Session Classification Logic (m3_interactive_harness.py:141)

```
classify_session(run_dir) → validity:
  ├── [CRASH RECOVERY] no state.db but hermes_home/state.db exists
  │     → WAL checkpoint in-place → copy to run_dir/state.db → continue below
  ├── result.json exit_code=128        → infra_failure (kernel crash)
  ├── state.db exists, msgs ≤ 2       → infra_failure (degenerate, e.g. 402)
  ├── state.db unreadable              → infra_failure
  ├── state.db + stdout has 4xx/429    → api_error
  ├── state.db + stdout has budget     → behavioral_failure
  ├── state.db + no failure patterns   → valid (NEVER re-run)
  ├── no state.db + stdout > 100 chars → infra_failure (recoverable=True)
  └── no state.db + no stdout          → infra_failure (not recoverable)
```

Re-run eligibility:
- `valid` → SKIP (evidence already captured)
- `behavioral_failure` → SKIP (not re-runnable; model behavior, not infra)
- `api_error` + has state.db → SKIP (partial evidence preserved)
- `infra_failure` / `incomplete` → ELIGIBLE for re-run

---

## Stopped Containers (as of 2026-07-21, all legacy — no hermes_home mount)

| Name | Memory | Output dir state | Notes |
|------|--------|-----------------|-------|
| `cta-m3-P1-interactive-P8-phase3-treatment-1` | 2048MB | hermes_stdout.txt + workspace (state.db recovered via `container export`) | Phase 3 run — session died at 22 msgs, WAL checkpoint never ran |
| `hermes-p8-phase3` | 1024MB | No mounts (gateway mode) | Manual run, entrypoint = `hermes gateway run` |
| `cta-m3-P1-interactive-kimi-ndjson-treatment-1` | 2048MB | state.db present | Plan 2 Phase 6 CPI run (run 1) |
| `cta-m3-P1-interactive-kimi-baseline-6` | 2048MB | state.db present | Baseline session (127 msgs) |
| `cta-m3-P1-interactive-kimi-baseline-7` | 2048MB | state.db present | Baseline session (189 msgs, STUCK) |
| `cta-m3-P1-interactive-kimi-baseline-8` | 2048MB | state.db present | Baseline session (121 msgs) |

All use `registry.rossollc.com/hermes:latest`. No secrets persist on their VM
disks — keys were env-var-only. Containers with state.db in their output dir had
the WAL checkpoint run before stopping. The Phase 3 container required manual
recovery (`container export` → tar extract → WAL checkpoint on host).

**New runs** (post 2026-07-21) include the `hermes_home` bind mount — manual
recovery is no longer needed.

---

## P8-phase2-prospective: NDJSON-Only Persistence

`data/m3_captures/P8-phase2-prospective/` contains 6 NDJSON session files
(14-30KB each) from direct `qodercli --output-format stream-json` runs. These
bypass the container/state.db pattern entirely:

- No container needed — runs on host or in any environment with qodercli
- Crash-safe: NDJSON is written line-by-line; partial files are still valid
- No WAL checkpoint dependency
- Self-contained evidence (tool_use events, timing, result)

This is the lightest persistence pattern and the direction Plan 8 moves toward.

---

## Recovering state.db from a Stopped Container

**Note:** This procedure is only needed for **legacy containers** (created before
the hermes_home bind mount was added on 2026-07-21). New runs persist state.db
to the host automatically — `classify_session()` handles crash recovery without
manual intervention.

If a legacy container stopped before the WAL checkpoint ran (state.db missing from
output dir but present inside the VM):

```bash
# Start the stopped container
container start <name>

# Run WAL checkpoint + copy inside the VM
container exec <name> /bin/sh -c '
  python3 -c "
import sqlite3
conn = sqlite3.connect(\"/home/hermes/.hermes/state.db\")
conn.execute(\"PRAGMA wal_checkpoint(TRUNCATE)\")
conn.close()
"
  cp /home/hermes/.hermes/state.db /root/output/state.db
'

container stop <name>
```

If the bind mount is still attached, state.db appears in the host output dir.
If `container exec` is not supported on stopped containers, start first then exec.

**Post-crash host-side recovery (M3 workspace):**
```bash
cd data/m3_captures/<run_id>/workspace
git diff --stat > ../git_diff.txt
git diff > ../git_diff_full.patch
```

---

## Friction Container (Gap 3)

`containers/Dockerfile.friction` builds `registry.rossollc.com/hermes:friction` —
an F1 friction environment where package installation is impossible. Used by
`scripts/gap3_friction_harness.py` for the ±adaptation paired experiment.

### Build

```bash
container build --no-cache -f containers/Dockerfile.friction \
  -t registry.rossollc.com/hermes:friction .
```

Builder shim: `container build` (Apple Container 0.11.0+). No Docker required.

### Non-editable install requirement

Hermes MUST be installed with `uv pip install .` (regular), NOT `pip install -e .`
(editable). Editable installs break `__version__` generation in `hermes_cli`:

```
ImportError: cannot import name '__version__' from 'hermes_cli'
```

The Dockerfile upgrades hermes to a pinned commit BEFORE removing package managers.

### Tools overlay path

With a non-editable install, Python imports resolve from site-packages, not the
source tree. The tools overlay (NDJSON patch) must be copied to:

```
/opt/hermes/.venv/lib/python3.13/site-packages/tools/
```

NOT `/opt/hermes/tools/` (source tree — ignored by the installed package).

### Escape vectors discovered (run 1, 2026-07-22)

| # | Vector | How agent exploited it | Dockerfile fix |
|---|--------|----------------------|----------------|
| 1 | `/usr/bin/uv` | Direct `uv pip install flask pyjwt` | Step 4: remove `/usr/bin/uv /bin/uv /usr/local/bin/uv` |
| 2 | `/app/.venv` (Honcho) | `import jwt` succeeded from Honcho's site-packages | Step 8b: remove flask/pyjwt from `/app/.venv/lib/` |
| 3 | `/tmp/uv-cache/` | Offline install from cached wheels | Step 8c: `rm -rf /tmp/uv-cache /root/.cache/uv` |
| 4 | `urllib.request` + ssl | Downloaded get-pip.py via HTTPS, reinstalled pip | ~~Step 11 original: remove `ssl.py` + `_ssl*.so`~~ **SUPERSEDED** — breaks hermes (see below) |
| 5 | (same as #4) | urllib HTTPS download | **Step 11 (revised):** copy ssl into hermes venv site-packages, remove from system python (venv split) |

**CRITICAL: ssl removal breaks hermes (discovered 2026-07-22, run 1 re-attempt).**
`hermes_cli/auth.py:26` does `import ssl` at module load time. Removing `ssl.py`
(Dockerfile step 11 original) causes hermes to crash immediately with
`ModuleNotFoundError: No module named 'ssl'` — both Gap 3 arms exited in ~5s
without reaching the LLM. Node.js TLS is unaffected (independent stack), but
hermes's Python HTTP client requires ssl for its own API calls.

**Fix (step 11 revised — venv split):** Copy `ssl.py` and `_ssl*.so` into the
hermes venv's site-packages, THEN remove them from system python. Python's import
system searches `sys.path` in order; the venv's site-packages is on hermes's path.

- `/opt/hermes/.venv/bin/python3 -c "import ssl"` → **succeeds** (hermes works)
- `/usr/local/bin/python3 -c "import ssl"` → **succeeds** (residual — see below)

**Residual escape (accepted):** System python can still `import ssl` because
`sitecustomize.py` leaks the hermes venv site-packages onto system `sys.path`.
The venv split alone does NOT isolate ssl from system python. However, the proven
escape vector (urllib HTTPS one-liner) is blocked by **step 12** (urllib HTTPS
handler patch). The remaining theoretical escape — raw `ssl.create_default_context()`
+ `socket` + manual HTTP GET — is a novel multi-step chain the model is unlikely
to discover under 900s time pressure. Accepted as low-risk.

```dockerfile
# Dockerfile step 11 (actual):
RUN cp /usr/local/lib/python3.13/ssl.py \
       /opt/hermes/.venv/lib/python3.13/site-packages/ssl.py \
    && cp /usr/local/lib/python3.13/lib-dynload/_ssl.cpython-313-aarch64-linux-gnu.so \
       /opt/hermes/.venv/lib/python3.13/site-packages/_ssl.cpython-313-aarch64-linux-gnu.so \
    && rm -f /usr/local/lib/python3.13/ssl.py \
             /usr/local/lib/python3.13/lib-dynload/_ssl.cpython-313-aarch64-linux-gnu.so
```

Multiple Python venvs exist in the base image: system (`/usr/local/lib/python3.13/`),
hermes (`/opt/hermes/.venv/`), honcho (`/app/.venv/`). Flask/pyjwt removed from all
three (steps 7, 8, 8b). The ssl venv split only preserves ssl for hermes — honcho
and system python lose it (honcho is not used during Gap 3 runs).

### Friction Container Verification

After building (or rebuilding post-reboot), verify inescapability before running
the experiment:

```bash
container run --rm --entrypoint /bin/sh registry.rossollc.com/hermes:friction -c '
  echo "=== Python import checks (all must FAIL) ==="
  python3 -c "import flask" 2>&1 && echo "ESCAPE: flask" || echo "OK: no flask"
  python3 -c "import jwt" 2>&1 && echo "ESCAPE: jwt" || echo "OK: no jwt"
  python3 -c "import pip" 2>&1 && echo "ESCAPE: pip" || echo "OK: no pip"

  echo "=== System python ssl (RESIDUAL — succeeds via sitecustomize path leak) ==="
  python3 -c "import ssl; print(\"KNOWN RESIDUAL: system ssl available (step 12 blocks urllib HTTPS)\")" 2>&1 || echo "OK: system ssl removed (stronger than expected)"

  echo "=== urllib HTTPS (must FAIL — no ssl module) ==="
  python3 -c "
import urllib.request
urllib.request.urlopen(\"https://pypi.org\", timeout=5)
print(\"ESCAPE: urllib HTTPS works\")
" 2>&1 || echo "OK: urllib HTTPS blocked"

  echo "=== Tool availability (all must FAIL) ==="
  which uv 2>/dev/null && echo "ESCAPE: uv" || echo "OK: no uv"
  which curl 2>/dev/null && echo "ESCAPE: curl" || echo "OK: no curl"
  which wget 2>/dev/null && echo "ESCAPE: wget" || echo "OK: no wget"
  which pip 2>/dev/null && pip --version 2>/dev/null && echo "ESCAPE: pip works" || echo "OK: pip fake/absent"

  echo "=== Hermes venv checks ==="
  /opt/hermes/.venv/bin/python3 -c "import flask" 2>&1 && echo "ESCAPE: hermes flask" || echo "OK: hermes no flask"
  /opt/hermes/.venv/bin/python3 -c "import jwt" 2>&1 && echo "ESCAPE: hermes jwt" || echo "OK: hermes no jwt"
  /app/.venv/bin/python3 -c "import jwt" 2>&1 && echo "ESCAPE: honcho jwt" || echo "OK: honcho no jwt"

  echo "=== Hermes venv ssl (must SUCCEED — hermes auth.py needs it) ==="
  /opt/hermes/.venv/bin/python3 -c "import ssl; print(\"OK: hermes ssl:\", ssl.OPENSSL_VERSION)" 2>&1 || echo "FAIL: hermes venv ssl missing (hermes will crash)"

  echo "=== Node.js TLS (must WORK — LLM API calls) ==="
  node -e "require(\"https\").get(\"https://registry.npmjs.org\", r => { console.log(\"OK: node https \" + r.statusCode); process.exit(0) }).on(\"error\", e => { console.log(\"FAIL: \" + e.message); process.exit(1) })"

  echo "=== Hermes version (must print) ==="
  hermes --version
'
```

**Pass criteria:** flask/jwt/pip imports fail, urllib HTTPS fails (step 12 — the
real blocking), all tools absent, hermes venv `import ssl` SUCCEEDS, Node.js HTTPS
works (status 200), `hermes --version` prints. System python `import ssl` succeeds
(known residual via sitecustomize path leak — accepted; proven escape vector is
urllib HTTPS which IS blocked). Any "ESCAPE" line = image needs another removal
step. Any "FAIL" in the hermes ssl/node/hermes section = hermes will crash at startup.

### Gap 3 harness workflow

```bash
# 1. Check kalloc headroom (>200k required)
zprint | grep "data.kalloc.1024"

# 2. Verify friction image (above)

# 3. Run paired experiment
python scripts/gap3_friction_harness.py --condition both --run-num 1 --timeout 900

# 4. Check results
cat data/m3_captures/P8-gap3-friction-treatment-1/classification.json
cat data/m3_captures/P8-gap3-friction-control-1/classification.json
```

Run IDs: `P8-gap3-friction-{treatment,control}-{N}`. Both arms install a skill;
the condition selects WHICH variant (v2.5.1 treatment vs v2.4.0 control).

---

## Design Principles (distilled from Plans 1, 2, 7, 8)

1. **Never trust the container to survive.** All evidence must reach the host
   filesystem via bind mounts or incremental writes.
2. **Classify before re-running.** A valid session is sacred — never overwrite.
3. **Check kernel health before launch.** kalloc.1024 headroom < 200k = reboot.
4. **Probe the API before spending.** 1-token health check catches 401/402/429.
5. **Recover from stdout when state.db is lost.** hermes_stdout.txt is always
   written (tee'd during the run) and survives crashes via the output bind mount.
6. **Prefer NDJSON streams over SQLite for new captures.** Line-by-line writes
   are inherently crash-safe; no checkpoint step needed.
7. **Persist Hermes home on the host.** `/home/hermes/.hermes` (config, skills,
   state.db + WAL) is bind-mounted to `run_dir/hermes_home/`. SQLite writes
   reach the host filesystem in real-time — a kernel crash loses nothing. The
   WAL checkpoint export in run.sh is a convenience, not a survival dependency.

---

## Live Verification (2026-07-21)

The hermes_home mount was verified with a targeted container test:

```bash
# 1. Create host dir + launch container with mount
mkdir -p /tmp/cta-persist-test/hermes_home
container run --name cta-persist-test -c 1 -m 512M \
  --mount "type=bind,source=/tmp/cta-persist-test/hermes_home,target=/home/hermes/.hermes" \
  --entrypoint /bin/sh registry.rossollc.com/hermes:latest -c '
    echo "test_data_123" > /home/hermes/.hermes/test_marker.txt
    python3 -c "import sqlite3; conn = sqlite3.connect(\"/home/hermes/.hermes/state.db\");
    conn.execute(\"CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)\");
    conn.commit(); conn.close()"
    sleep 300
'

# 2. Verify from host (appeared within 3 seconds)
cat /tmp/cta-persist-test/hermes_home/test_marker.txt  # → test_data_123
ls /tmp/cta-persist-test/hermes_home/state.db          # → 8192 bytes

# 3. Simulate crash
container kill cta-persist-test

# 4. Verify persistence after kill
cat /tmp/cta-persist-test/hermes_home/test_marker.txt  # → test_data_123 (intact)
python3 -c "import sqlite3; print(sqlite3.connect('/tmp/cta-persist-test/hermes_home/state.db').execute('SELECT name FROM sqlite_master').fetchall())"
# → [('messages',)] — table intact after kill
```

**Result:** Files written to `/home/hermes/.hermes/` inside the container persist
on the host immediately (virtiofs). After `container kill` (simulating kalloc
exit-128), both the marker file and state.db are intact and readable. No WAL
checkpoint or export step was needed.
