# AGENT.md — CTA (Counterfactual Trace Auditing)

**⚠️ KALLOC WATCHDOG — MACOS WILL REBOOT WITHOUT WARNING.**
macOS 26.6 beta has a kernel memory leak in `data.kalloc.1024`. A watchdog daemon
(`/Library/LaunchDaemons/local.kalloc1024.watchdog.plist`) polls every 5 minutes and
triggers `shutdown -r +1` when elements exceed 3,000,000 (~2.86 GB). Each Apple Container
VM consumes kalloc elements. The harness checks headroom before each run
(`check_kalloc_headroom()`), but a reboot can still hit mid-session.
**All state must persist to disk after every session.** Never hold progress only in memory.

**⚠️ CONTAINER SERVICE DIES ON REBOOT.** After any reboot (kalloc or otherwise),
`container list` fails with "XPC connection error." Run `container system start` before
any container operation. The harness does NOT do this automatically.

**⚠️ WAL CHECKPOINT BEFORE COPY.** Hermes v0.19.0 uses SQLite WAL mode. `state.db` alone
is 4KB (empty); all session data lives in `state.db-wal`. The in-container run script
handles this (`PRAGMA wal_checkpoint(TRUNCATE)`), but if you ever copy a state.db manually,
checkpoint first or you get an empty database.

**⚠️ NEVER TRUST THE MODEL'S SELF-REPORT OF QODERCLI SUCCESS.** The #1 destructive SIP
discovered in this audit (P1-treatment-1: False Success Reporting). Always verify from
terminal output and exit codes. The skill now documents this (v2.1.0 Error Recovery section).

**⚠️ SECRETS LIVE IN THE ENCLAVE, NOT ENV VARS.** The harness reads secrets from disk:
- `~/.enclave/opencode_primary.txt` → OPENCODE_GO_API_KEY (opencode-go provider)
- `~/.enclave/qoder.txt` → QODER_PERSONAL_ACCESS_TOKEN (qodercli auth)
- `~/.hermes/profiles/coding/.env` → fallback for OPENCODE_API_KEY
Never echo these. Never pass them as inline command args. The harness injects them via
`-e` flags on `container run`.

## WHAT

Counterfactual Trace Auditing of the `qodercli` skill for Hermes Agent. Measures whether
the skill changed agent behavior for better or worse by diffing paired execution traces
(with-skill vs without-skill baseline) and labeling divergences as Skill Influence Patterns.

- **Language:** Python 3.14+ (`/opt/homebrew/bin/python3`)
- **Runtime:** Apple Container micro-VMs (4 CPU, 2GB RAM each)
- **Target:** NousResearch/hermes-agent PR #68314
- **Hardware:** M2 Mac (primary), Jetson Orin Nanos (fleet, not used for captures)

## KEY DOCUMENTS

| File | Purpose | Update frequency |
|------|---------|-----------------|
| `plans/1-hermes_cta_fork_plan.md` | Plan 1 — Master plan: all milestones, decisions, territory corrections, progress | Every session |
| `plans/2-cta_verification_layer_plan.md` | Plan 2 — CTA as grounded verification layer: taxonomy positioning, generalization, eval modules | Every session |
| `data/audit_report.md` | Formal audit report — hypotheses, SIPs, evidence, verdicts | After batch completion |
| `data/pr_writeup.md` | PR description for hermes-agent#68314 (synced with live GitHub PR body) | After batch completion |
| `tasks/pre_registration.json` | Locked task list + quantitative pass/fail thresholds (immutable) | Never (pre-registered) |

**Consistency rule:** When updating one document, check the other two for staleness.
The plan is the source of truth for progress; the audit report and PR writeup are
derived artifacts that lag behind during active capture.

## ENTRY POINTS

| Task | Command |
|------|---------|
| Start container service (post-reboot) | `container system start` |
| Check kalloc headroom | `zprint \| grep data.kalloc.1024` (field 7 = elements) |
| Run M3 batch (kimi, both conditions) | `python scripts/m3_interactive_harness.py --condition both --runs 3 --baseline-token --tag kimi --start-run N` |
| Validate a session (G1+) | `python scripts/validate_g1_plus.py data/m3_captures/<run-id>/state.db -v` |
| Run full audit (one-command, G6) | `python scripts/run_audit.py` |
| G1 corpus sweep | `python scripts/g1_probe.py "data/m2_captures/*/state.db"` |
| M4 PTY counterfactual | `python scripts/m4_harness.py` |
| Check batch progress | `cat data/m3_captures/progress.json` |
| List active containers | `container list` |
| Stop/rm a container | `container stop <name> && container rm <name>` |

## SKILLS

| Skill | Path | Use when |
|-------|------|----------|
| creating-updating-plans | `~/.hermes/profiles/coding/skills/creating-updating-plans` | Creating/iterating project plans, AGENT schema, plan-sizing |
| adversarial-review | `~/.hermes/profiles/coding/skills/adversarial-review` | Multi-agent finder/adversary/referee review of plans or code |
| applying-karpathy-guidelines | `~/.hermes/profiles/coding/skills/applying-karpathy-guidelines` | Assumption auditing, ambiguity surfacing, blast-radius discipline |
| rcf-weighted-planner | `~/workspace/nano2/.claude/skills/rcf-weighted-planner/SKILL.md` (v1.5) | Reference class forecasting, optimism bias correction, pre-mortem, calibration buffers |
| managing-hermes-honcho-containers | `~/.hermes/profiles/coding/skills/managing-hermes-honcho-containers` | Apple Container runtime debugging, container networking |

## CAPTURE INFRASTRUCTURE

### Container lifecycle (per run)

```
container system start (if post-reboot)
  → check_kalloc_headroom() (abort if < 200K)
  → container run --name cta-m3-<run-id> ... (fresh VM, ~20s startup)
    → in-container: git fetch hermes v0.19.0, install qodercli, configure model
    → in-container: hermes chat -q "..." -Q --yolo
    → in-container: WAL checkpoint + state.db copy to bind mount
  → container rm (cleanup)
  → result.json + progress.json written to disk
```

### Apple Container gotchas (learned from M2 captures)

- **Bind mount source must be a directory.** Cannot mount individual files.
- **Symlinks don't cross the VM boundary.** Mount `SKILL_PATH.resolve().parent`, not the symlink.
- **No `commit` or `build` command.** Image upgrades happen in-container via git fetch + pip install.
- **Container names must be unique.** Reusing a name without `rm` first causes "already exists" error.
- **Timeout for positive tasks:** 900s (qodercli multi-file delegation takes 300-600s).

### Session export structure

```
data/m3_captures/<run-id>/
├── state.db          # Hermes session (SQLite, WAL-checkpointed)
├── hermes_stdout.txt # Full terminal output
├── result.json       # Harness metadata (duration, exit code)
├── run.sh            # Generated in-container script (reproducible)
└── run_metadata.txt  # Timestamps, model, provider, condition
```

### Models & providers

| Model | Provider | Env var | Use |
|-------|----------|---------|-----|
| anthropic/claude-sonnet-4 | openrouter | OPENROUTER_API_KEY | M2 captures (exhausted) |
| kimi-k2.7-code | opencode-go | OPENCODE_GO_API_KEY | M3 volume expansion (active) |

Provider config is written in-container to `/home/hermes/.hermes/config.yaml`.
Hermes uses provider-specific env var naming (`OPENCODE_GO_API_KEY`, not `OPENCODE_API_KEY`).

## NEVER DO THIS

- **Never copy state.db without WAL checkpoint** — you get a 4KB empty file
- **Never run two containers simultaneously** — kalloc pressure exceeds threshold, triggers reboot
- **Never assume `container list` works after reboot** — always `container system start` first
- **Never re-run completed sessions** — harness has skip-if-complete (checks for state.db)
- **Never update audit_report.md or pr_writeup.md mid-batch** — wait for N=10 completion, then update with full statistics
- **Never use timestamps for event ordering** — Hermes DB timestamps are flush-time only; use `messages.id` AUTOINCREMENT
- **Never run the XGBoost SIP classifier on Hermes traces** — out-of-distribution inference (G3: heuristics only)

## HYPOTHESIS STATUS

| # | Hypothesis | Verdict |
|---|---|---|
| H1 | Delegation Efficiency | PARTIALLY CONFIRMED (8x write compression, not clean 1-call collapse) |
| H2 | PTY Stability | RECLASSIFIED → H2-revised CONFIRMED (print PTY-agnostic, interactive 100%) |
| H3 | Interactive Blockade | CONFIRMED (skill provides 2.5x efficiency, not binary enablement) |
| H4 | Binary Resolution | CONFIRMED (4/6 treatment + M3) |

## PYTHON

3.14+ only. `/opt/homebrew/bin/python3` on M2. No system Python.
Key deps: sqlite3 (stdlib), no external packages required for harness/validator.
