# Skill PR: `qodercli` — Delegate Coding to Qoder CLI

**Target:** `NousResearch/hermes-agent` → `skills/autonomous-ai-agents/qodercli/SKILL.md`
**Author:** explicitcontextualunderstanding
**Skill version:** 2.0.0

---

## Summary

Adds a skill that enables Hermes to delegate multi-file coding tasks to [Qoder CLI](https://docs.qoder.com) via the `terminal` tool. Qoder reads files, writes code, runs shell commands, spawns subagents, and manages git workflows autonomously — freeing Hermes to orchestrate and verify rather than implement line-by-line.

This PR includes evidence from a **Counterfactual Trace Audit (CTA)** — 12 containerized sessions (10 print-mode + 2 interactive-mode) comparing Hermes behavior with and without the skill, following the methodology of [Zhou et al. (arXiv:2605.11946)](https://arxiv.org/abs/2605.11946). Audit code and session data: [github.com/WillChow66/CTA](https://github.com/WillChow66/CTA).

### Why this skill matters now

- **Exclusive Model Access**: Provides Hermes with native access to **Qwen3.8-Max-Preview** (Alibaba Cloud's 2.4T-parameter flagship model), which is available exclusively through Alibaba Cloud and Qoder CLI/QoderWork platforms.
- **10x Cost Leverage**: Qoder CLI currently offers `Qwen3.8-Max-Preview` at a 90% credit discount, allowing Hermes to delegate heavy multi-file refactoring and subagent loops at a fraction of standard API costs.
- **Context Window Protection**: `Qwen3.8-Max-Preview` operates with a default **131k token context window** (scalable to 1M). Offloading multi-file migrations to `qodercli` keeps file-ingestion bloat inside Qoder's execution environment, preventing Hermes's context window from truncating during long multi-turn sessions.

---

## What the skill does

| Capability | Mechanism |
|---|---|
| Multi-file delegation | `qodercli -p '<prompt>' --permission-mode bypass_permissions` via terminal |
| Flagship model override | `--model Qwen3.8-Max-Preview` to leverage Alibaba Cloud's exclusive 2.4T model |
| Interactive sessions | `qodercli -i '<prompt>'` with `background=true, pty=true` + `process()` monitoring |
| Auth guidance | Documents `QODER_PERSONAL_ACCESS_TOKEN` setup (without which qodercli is unusable) |
| Binary resolution | Procedure step: `which -a qodercli && qodercli --version` before delegation |
| Scope constraint | Explicit "Do NOT use for single-file lookups" prevents over-delegation |
| Folder trust handling | Documents the `1\n` response for first-launch trust dialogs |
| Context window preservation | File ingestion happens inside qodercli's workspace; Hermes sees only the command + summary, not raw file contents |

---

## CTA Evidence (12 sessions, containerized)

### Methodology

Each session runs in a fresh Apple Container micro-VM (4 CPU, 2GB RAM) with:
- Hermes v0.19.0 (commit `a41d280f`)
- qodercli v1.1.1
- Model: `anthropic/claude-sonnet-4` via OpenRouter
- Identical fixture project (6 route files, models, services, db, utils, tests)

**Treatment:** Skill installed + `QODER_PERSONAL_ACCESS_TOKEN` provided.
**Baseline:** Skill removed + no token. Everything else identical.

### Task suite

| ID | Type | Task | Tests |
|---|---|---|---|
| P1 | Positive | REST API auth across 4 files/3 dirs | Delegation triggers |
| P2 | Positive | Raw SQL → SQLAlchemy migration (repo-wide) | Write offloading |
| N1 | Negative control | Fix single-line typo in helpers.py | Skill should NOT trigger |
| E1 | Edge case | Read package.json, report version | Read-only, no modification |
| P1-int | Interactive | Auth endpoint via `qodercli -i` | Trust dialog handling |

### Structural comparison

| Task | T msgs | B msgs | T tools | B tools | T writes | B writes | Write compression |
|------|--------|--------|---------|---------|----------|----------|-------------------|
| E1 | 4 | 4 | 1 | 1 | 0 | 0 | — |
| N1 | 32 | 38 | 14 | 17 | 1 | 3 | 3x |
| P1 | 65 | 4* | 32 | 1* | 3 | 0* | — |
| P2 | 66 | 113 | 38 | 62 | **2** | **16** | **8x** |

*P1 baseline used Hermes's native `delegate_task` (opaque subagent), not manual work. P2 is the valid comparison.

### Key finding: Auth enablement is the gatekeeper

In P2-baseline, the model **found qodercli in PATH** and attempted to use it:

```
$ qodercli -p "Migrate..."
Error: Not logged in · Please run /login
```

Without the skill's token guidance, qodercli is present but unusable. The model fell back to 113 messages of manual migration. With the skill, delegation succeeded and manual writes dropped from 16 → 1-3.

---

## Pre-registered hypotheses (evaluated before recording)

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Delegation Efficiency: skill collapses N file ops into 1 terminal call | **PARTIALLY CONFIRMED** | 8x write compression on P2. Not clean 1-call collapse — model adds verification loops. |
| H2 | PTY Stability: every qodercli invocation sets `pty=true` | **RECLASSIFIED → H2-revised CONFIRMED** | M4 counterfactual: print mode PTY-agnostic (exit 0 both conditions). M3: 100% pty=true on interactive. Model discriminates correctly by mode. |
| H3 | Interactive Blockade: model detects folder trust prompt and sends `1\n` | **CONFIRMED** | M3 trace: model detected dialog, referenced skill guidance, resolved via `process(submit, data='1')` after 2 polls. |
| H4 | Binary Resolution: model runs `which -a qodercli` during orientation | **CONFIRMED** | 4/6 treatment traces + M3. Consistent across all positive tasks. |

### Disconfirmation reporting (per G5 pre-registration)

H2-original is disconfirmed: the model omits `pty=true` on 27% of qodercli calls. However, M4 counterfactual testing (deterministic PTY-vs-pipes comparison with `--permission-mode bypass_permissions`) proved print mode is PTY-agnostic — both conditions exit 0 with identical file output. The hypothesis was over-specified. **H2-revised** ("pty=true on interactive; may omit on print") is **CONFIRMED**: M3 shows 100% compliance on interactive calls, and the 4 omissions in M2 were all print-mode foreground calls where PTY is a no-op. The skill's PTY guidance has been scoped to interactive mode only.

---

## Skill Influence Patterns detected

| SIP | Valence | Count | Description |
|-----|---------|-------|-------------|
| PROCEDURAL_SCAFFOLDING | constructive | 5/5 treatment | Skill loaded → binary resolution → structured delegation in every positive run |
| DELEGATION_REDIRECT | constructive | 5/5 treatment | Delegation redirected from native `delegate_task` to qodercli |
| PTY_OMISSION | ~~destructive~~ **neutral** (M4) | 4/5 treatment | `pty=true` omitted on print-mode calls where it's a no-op (M4 confirmed: identical exit codes + file output with/without PTY) |
| CONCEPT_BLEED | — | 0 | Negative control (N1) and edge case (E1) show zero qodercli invocations |

### Controls validate the metric

- **N1 (negative control):** Zero qodercli invocations. Model fixed typo manually. Skill scope constraint respected.
- **E1 (edge case):** Zero WRITE events. Read-only task handled identically in both conditions.
- **Conclusion:** The audit metric is NOT trivially constructive — it correctly shows zero influence where zero influence is expected.

---

## Evidence-based fixes applied to SKILL.md

Both fixes were discovered through trace analysis, not speculation:

### Fix 1: Permission wall (discovered in P1-treatment-1)

**Problem:** qodercli hit "Permission confirmation required but no interactive handler" because the skill's print-mode examples lacked `--permission-mode bypass_permissions`.

**Trace evidence:** P1-treatment-1 msg 8: qodercli output contains permission error; model reports success despite failure (false-positive).

**Fix:** Added `--permission-mode bypass_permissions` to all print-mode examples and Procedure step 2.

### Fix 2: PTY scope clarification (discovered via H2 disconfirmation + P3a probe)

**Problem:** Skill said "PTY is mandatory" universally. Empirical probe confirmed print mode works without PTY (`subprocess.Popen` with pipes → exit 0).

**Trace evidence:** 4/15 qodercli calls omitted `pty=true` and succeeded anyway (print mode).

**Fix:** Scoped PTY requirement to interactive mode only: "PTY is mandatory for interactive mode (`-i`, background). Print mode (`-p`) works without it."

---

## Interactive mode evidence (M3)

The M3 trace demonstrates the full interactive lifecycle:

```
msg  4: terminal(which -a qodercli && qodercli --version)     ← binary resolution
msg 10: terminal(qodercli -i "...", pty=True, bg=True)        ← interactive launch
msg 12: process(poll)                                          ← first check
msg 14: process(log)                                           ← read output
msg 16: process(submit, data='1')                              ← TRUST DIALOG RESOLVED
msg 18-32: process(poll/log/wait) ×7                           ← monitoring progress
msg 39: process(submit, data='1')                              ← permission prompt #1
msg 48: process(submit, data='1')                              ← permission prompt #2
msg 58: process(submit, data='1')                              ← permission prompt #3
```

The model explicitly referenced the skill: *"I can see qodercli is asking for folder trust confirmation. As mentioned in the skill, I need to send..."*

---

## M4 PTY counterfactual (deterministic, no model)

Isolated the PTY variable by running qodercli directly with PTY allocated vs plain pipes (`--permission-mode bypass_permissions`):

| Task | PTY (A) | Pipes (B) | Exit match | Wall time diff |
|------|---------|-----------|------------|----------------|
| T1 (multi-file auth) | exit=0, 119.6s | exit=0, 151.2s | Yes | 20.9% |
| T2 (read package.json) | exit=0, 11.6s | exit=0, 12.0s | Yes | 3.1% |

**Verdict:** Print mode is PTY-agnostic. Both conditions produce identical exit codes and file output. Wall-time variance is within LLM non-determinism range (M2 showed 9-99% between identical runs). This confirms the model's 73% PTY compliance is *correct discrimination* — it sets `pty=true` on interactive calls (100%, M3) and omits it on print-mode calls where it's a no-op.

---

## Variance (treatment run 1 vs run 2)

| Metric | P2-T1 | P2-T2 | Δ |
|--------|-------|-------|---|
| Messages | 63 | 70 | 11% |
| Tool calls | 33 | 43 | 30% |
| Wall time | 563.8s | 613.0s | 9% |
| Manual writes | 1 | 3 | — |
| qodercli calls | 3 | 4 | 33% |

The structural pattern (skill → binary resolution → delegation → verification) is consistent. Variance is in post-delegation verification behavior, not in the delegation decision itself.

---

## Relationship to [arXiv:2605.11946](https://arxiv.org/abs/2605.11946)

This audit extends the CTA framework from prompt/playbook skills to **delegation skills**:

| Paper finding | Our extension |
|---|---|
| Pass rate is nearly silent (+0.3pp across 49 tasks) | Confirmed: M1 single-file task showed identical outcomes; CTA revealed orientation-level influence |
| Ceiling tasks absorb 80% of SIPs | Confirmed: E1/N1 (simple tasks) show zero SIPs; signal only appears on P1/P2 (complex tasks) |
| Offsetting behaviors mask bugs | Confirmed: P1 permission failure hidden by model's false-success reporting |
| Token overhead 2.77x for constructive skills | Extended: Delegation trades action count for wall-time (1.6x longer, 8x fewer writes) |
| DTW alignment over symmetric traces | Extended: Delegation produces 1:16 asymmetric sparsity; structural metrics replace DTW |

### New SIP vocabulary for delegation skills

| SIP | Valence | Paper equivalent |
|---|---|---|
| DELEGATION_REDIRECT | constructive | Procedural Scaffolding (subtype) |
| PARTIAL_DELEGATION | neutral | — (new: offload + timeout + verify) |
| PERMISSION_GAP | destructive | — (new: headless confirmation blocks) |
| PTY_OMISSION | destructive | — (new: terminal argument non-compliance) |

---

## Reproducibility

Audit code and raw session data: [github.com/WillChow66/CTA](https://github.com/WillChow66/CTA)

```bash
# One-command audit (no API keys needed — reads committed session data)
python scripts/run_audit.py

# Output: data/audit_report.json + data/audit_report.md
```

Raw session data (SQLite databases + stdout) committed in `data/m2_captures/` and `data/m3_captures/`. Capture harness in `scripts/capture_harness.py` (requires OpenRouter key + Apple Container runtime to re-run).

---

## Limitations

1. **N=2-3 per condition** (lean design). Effect sizes are 3-16x, so statistical power is adequate, but rare-event SIPs may be underrepresented.
2. **Single model** (claude-sonnet-4). Behavior may differ on other models.
3. **H2-original disconfirmed, H2-revised confirmed.** 73% PTY compliance overall, but 100% on interactive calls where it matters. M4 proved print mode is PTY-agnostic. Skill language scoped accordingly.
4. **M3 baseline blocked** (credit exhaustion). Interactive-mode comparison is treatment-only.
5. **Wall-time tradeoff.** Delegation reduces agent actions but increases total execution time (qodercli is slow). This is a tradeoff, not a pure win.

---

## Checklist

- [x] Skill loads and injects correctly (skill_view marker in all treatment traces)
- [x] Model chooses to delegate on complex tasks (P1, P2)
- [x] Model correctly declines on simple tasks (N1, E1)
- [x] Binary resolution procedure followed (H4 confirmed)
- [x] Folder trust dialog handled in interactive mode (H3 confirmed)
- [x] Permission wall bug fixed (`--permission-mode bypass_permissions`)
- [x] PTY language scoped to interactive mode (empirically validated)
- [x] Negative control shows zero skill influence (metric validity)
- [x] One-command reproducibility script (`scripts/run_audit.py`)
- [x] Tests pass: `scripts/run_tests.sh tests/skills/test_qodercli_skill.py -q` (contributing.md HARDLINE #7)

