# Plan 7 — Investigation: Observing Sub-Agent Inference Progress

Status: **REVIEWED** — 3-lens review complete, empirical corrections applied, ready for gated execution
Version: 2.0 (post-adversarial/Karpathy/RCF review)
Parent:
  - 1: plans/1-hermes_cta_fork_plan.md (MONITORING_IMPATIENCE SIP, lines 1614–1668)
Related:
  - 4: plans/4-upstream_pty_collapser.md (PTY observation field)

---

## §0 CURRENT STATE

| Field | Value |
|---|---|
| Active blocker | Priority 1 verification (SDK JSONL activation mechanism) |
| Next action | Run P1 probes (bundle grep + Hermes terminal schema check) |
| Empirical baseline | 48% signal recovery across 75 real polls (measured 2026-07-21) |
| Behavioral fix status | Plan 1 patience guidance drafted, not yet deployed |

---

## §1 PROBLEM STATEMENT

When Hermes delegates to qodercli via `terminal(pty=true, background=true)` and
monitors via `process(poll)`, it sees only spinner glyphs (⠋⠙⠹...) for 58–74
consecutive polls before losing patience and killing the process. This is the
MONITORING_IMPATIENCE SIP documented in Plan 1.

Root cause: no structured progress signal crosses the Hermes ↔ qodercli boundary.
The poll window (measured: max 658 chars, mean 419, median 387 across 75 real
polls) frequently contains only spinner padding with zero information.

---

## §2 KEY THESIS (CORRECTED)

**Original claim**: "The schema problem is solved; the work is purely transport bridging."

**Corrected**: The Qoder SDK wire protocol emits structured sub-agent progress
events (`task_started`/`task_progress`/`task_notification`). However:

1. These events track **sub-agents spawned within a qodercli session** (child
   tasks), NOT the top-level session's own step-by-step progress. Hermes needs
   "qodercli main session is on step 3/~10, editing auth.py, thinking for 25s."
   No SDK event fires for the main session's own tool activity.

2. `session_state_changed` (idle/running/requires_action) is too coarse to
   prevent the 58–74 poll stuck loop.

3. The SDK's JSONL protocol is only active when qodercli is spawned by the SDK
   over stdio pipes. The TUI does NOT render JSONL — it renders via terminal
   redraws. These are two separate output paths.

**Revised thesis**: The SDK proves structured progress is *architecturally
feasible* within qodercli, but real design work is needed to (a) define what the
top-level session emits about its own progress, and (b) bridge that to Hermes'
PTY-based monitoring. The transport gap is real; the schema gap is partially
(real events exist for sub-agents, not for the main session).

### SDK events (confirmed in bundle, 2026-07-21)

| Event (`system` subtype) | Fields | Covers |
|---|---|---|
| `task_started` | `task_id`, `description`, `tool_use_id` | Sub-agent spawned |
| `task_progress` | `task_id`, `last_tool_name`, `usage.tool_uses`, `usage.duration_ms` | Sub-agent step heartbeat |
| `task_notification` | `task_id`, `status: completed\|failed\|stopped`, `summary` | Sub-agent terminal state |
| `session_state_changed` | `state: idle\|running\|requires_action` | Coarse run-state (main session) |
| `result` | `num_turns`, `duration_ms`, `total_cost_usd` | Final outcome (main session) |

Activation: `QODER_SDK_ACCESS_TOKEN` and `QODER_SDK_AUTH_PAYLOAD_FILE` env vars
found in bundle. No user-facing CLI flag (`--sdk`, `--jsonl`) exists in `--help`.
The SDK transport class spawns qodercli with `stdio: ["pipe", "pipe", ...]` —
activation appears internal to the SDK's spawn path.

---

## §3 EMPIRICAL EVIDENCE (measured 2026-07-21)

Source: `data/m3_captures/P1-interactive-kimi-treatment-2/state.db`, 75 process
observations for session `proc_856cdacca3e1`.

### Poll content measurements

| Metric | Value |
|---|---|
| Total process observations | 75 (not 84 as previously stated) |
| ESC (0x1b) characters in output_preview | **0** (zero across all 75 polls) |
| CR characters in output_preview | 32 |
| Max output_preview length | 658 chars |
| Mean output_preview length | 419 chars |
| Median output_preview length | 387 chars |

### Signal recovery rates (regex over all 75 polls)

| Signal | Hit rate | Notes |
|---|---|---|
| Context fill % (`ctx...N%`) | 47% (29/62 truncated polls) | Highest-frequency signal |
| ANY parseable signal | 48% | Combined across all patterns |
| Thinking elapsed time | 7% (5/75) | Spaces dropped: `Thinking...(esctocancel,6s)` |
| Tool activity (`Read(...)`) | 6% (4/75) | Preceded by garbled bytes, not clean `▫`/`▪` |
| ZERO signal (spinner-only) | **52%** | Majority of polls contain nothing |

### Critical empirical findings

1. **OSC sideband is DEAD**: Zero ESC characters in any poll. Hermes' terminal
   infrastructure strips ANSI escape sequences before returning `output_preview`.
   Any OSC-based heartbeat (OSC 9777, OSC 9;4) is invisible to Hermes.

2. **`-p -o json` is a single blob, NOT a stream**: Live test
   `qodercli -p -o json "say hello"` returns one `{"type":"result",...}` object.
   It does NOT emit NDJSON progress events. Priority 1's "verify print mode
   emits stream-json" is definitively answered: **it does not**.

3. **Output is grid-rendered, not raw bytes**: Words run together
   (`Letmefirst readte existingfilestounderstandtheconventions`), cursor
   positioning is lost, multi-byte characters partially captured. This is a
   terminal grid snapshot, not a byte stream.

4. **Two distinct output formats exist**: `output_preview` (short, max 658 chars)
   and `output` (longer, paginated: `total_lines: 1412, showing: 100 lines`).
   The model sees both. The "1000-char window / 200KB buffer" claim is not
   supported by the data.

5. **Regexes as written don't match actual data**: The plan's regex expects
   `esc to cancel` with spaces; actual data shows `esctocancel`. Tool markers
   are preceded by garbled multi-byte sequences, not clean Unicode `▫`/`▪`.

---

## §4 SOLUTION LANDSCAPE (revised)

### Layer 1: Protocol-level (A2A Task Progress)
A2A protocol (Google, v1.0.0): `submitted → working → input-required →
completed/failed/canceled` with ProgressTracker metadata.
**Gap**: assumes HTTP/SSE transport. Not applicable to PTY.

### Layer 2: Streaming SDK (exists but unreachable)
`query()` returns `AsyncGenerator<SDKMessage>` with sub-agent progress events.
**Gap**: requires stdio-pipe spawn. Hermes uses PTY. No CLI flag activates
JSONL mode. `-p -o json` is one-shot, not streaming.

### Layer 3: PTY-level (measured: 48% recovery, grid-rendered)
Signals exist but are unreliable (52% of polls are spinner-only). Output is
grid-rendered (ANSI stripped, spaces lost). Regex requires normalization for
garbled text. OSC sideband is dead.

### Layer 4: Ecosystem convergence
Claude Code (`--output-format stream-json`), Codex (`exec --json`), OpenHands
(HTTP event stream) all abandon PTY for programmatic monitoring.

### Layer 5: Behavioral (lowest cost, highest ROI)
Plan 1's SKILL.md patience guidance ("use `process(wait, timeout=120)` instead
of rapid poll loops; spinner means working; max 10 polls before escalating")
addresses the actual failure mode (model has no patience heuristic) at near-zero
cost. May deliver 80% of the value at 1% of the engineering cost.

---

## §5 ADVERSARIAL REVIEW FINDINGS (2026-07-21)

### HIGH severity (all addressed)

| ID | Finding | Resolution |
|---|---|---|
| H1 | "Schema solved" is false — SDK events cover sub-agents, not main session progress | Thesis corrected in §2 |
| H2 | Regexes don't match actual capture data (spaces dropped, garbled bytes) | Patterns must be rewritten against real data; see §6 |
| H3 | "80% hit rate" asserted without measurement (actual: 48%) | Corrected in §3 with empirical data |

### MEDIUM severity (addressed)

| ID | Finding | Resolution |
|---|---|---|
| M1 | `observation` field is JSON tool-result, not raw PTY bytes | Corrected: `output_preview` within JSON, grid-rendered |
| M2 | Priority 2 viability depends on Priority 1 answer | P1 is now a HARD GATE (§7) |
| M3 | "1000 chars / 200KB" unsourced; reality shows two formats | Corrected in §3 (max 658, two formats documented) |
| M4 | ANSI injection cited but not mitigated | Added §8 security constraint |
| M5 | Priorities 3–4 have no realistic landing path | Moved to backlog as contingent options (§7) |
| M6 | No version-drift mitigation | Added §8 maintenance constraint |
| M7 | OSC proposal contradicted by own evidence (grid strips ESC) | OSC declared dead in §3 finding 1 |

### LOW severity (noted)

| ID | Finding | Resolution |
|---|---|---|
| L1 | "84 polls" is actually 75 | Corrected throughout |
| L2 | 2–3h estimate is ~3x optimistic | RCF forecast: 6–14h base case (§9) |
| L3 | Idle/waiting state handling unspecified | Added to §6 parser requirements |

---

## §6 KARPATHY ASSUMPTION AUDIT

| # | Assumption | Status | Invalidation criterion |
|---|---|---|---|
| 1 | SDK emits task_started/task_progress/task_notification | **PROVEN** | `grep -c "task_progress" bundle/qodercli.js` → 5 |
| 2 | process(poll) returns raw PTY bytes with ANSI escapes | **BROKEN** | Measured: 0 ESC chars in 75 polls |
| 3 | TUI emits parseable signal at ≥1Hz | **PARTIAL** | Measured: 48% of polls (coin-flip, not reliable) |
| 4 | Regex recovers ~80% of signal | **BROKEN** | Measured: 48% |
| 5 | Regex stop-gap is 2–3h work | **UNVERIFIED** | Realistic: 6–14h (RCF §9) |
| 6 | Hermes can spawn with pipes (non-PTY) | **UNVERIFIED** | Check Hermes terminal tool schema for `pty=false` |
| 7 | qodercli has hidden flag for JSONL mode | **PARTIAL** | Env vars found; no CLI flag; activation is SDK-internal |
| 8 | `-p -o json` streams events | **BROKEN** | Live test: single blob, 1 line |
| 9 | Upstream PRs are landable | **UNVERIFIED** | No CONTRIBUTING.md, no public repo found |
| 10 | 1000-char window / 200KB buffer | **BROKEN** (1000) / **UNVERIFIED** (200KB) | Measured max: 658 chars |
| 11 | output_preview is what Hermes uses for decisions | **PARTIAL** | Both output_preview and output visible to model |
| 12 | TUI format stable across versions | **UNVERIFIED** | Auto-update observed mid-session |
| 13 | SDK JSONL = same stream TUI renders | **BROKEN** (likely false) | TUI renders via terminal redraws; SDK via stdio pipes |

### Top 3 assumptions to falsify first

| Rank | Assumption | Cheapest probe |
|---|---|---|
| 1 | #6: Hermes can spawn non-PTY | Inspect Hermes terminal tool schema for `pty` parameter accepting `false` |
| 2 | #7: JSONL activation mechanism | `grep -n "spawn\|execFile\|child_process" bundle/qodercli.js` → inspect argv construction |
| 3 | #3: Full `output` field recovery vs `output_preview` | Run regex over `output` fields (longer, may contain more signal) |

---

## §7 REVISED PRIORITY ORDERING (gated)

| # | Action | Owner | Effort (RCF) | Gate |
|---|---|---|---|---|
| **1** | **Verify SDK JSONL activation + Hermes pipe capability** | Research | 3h base (1.5–6h) | **HARD GATE — blocks all else** |
| 2 | Measurement script: regex hit-rate over existing captures | CTA | 1h | After P1 |
| 3 | Minimal liveness parser (ctx% only) + behavioral fix deployment | CTA | 3–4h | After P2, if recovery >40% |
| 4 | Sidecar file + visible status line | Upstream (contingent) | 3–6 weeks calendar, 30% acceptance | Only if P1 favorable |
| 5 | SDK/pipe mode in Hermes | Hermes arch (contingent) | 4–8 weeks | Only if P1 proves pipe spawn possible |

### Sequencing rule

**P1 is a HARD GATE.** Do NOT build the regex parser (P3) until P1 resolves.
Rationale: if a JSONL activation path exists AND Hermes can spawn non-PTY, the
regex parser is dead code before written. P1's information value exceeds P3's
implementation value.

### Decision tree after P1

```
P1: Can Hermes spawn non-PTY + does JSONL mode activate?
├── YES (both) → Skip P2/P3. Wire SDK JSONL through Hermes pipe spawn. Done.
├── PARTIAL (pipe yes, no flag) → Replicate SDK spawn logic in Hermes. Medium effort.
├── NO (PTY locked) → P2 measurement → P3 minimal parser + behavioral fix.
│   └── P3 delivers 48% liveness detection. Behavioral fix (Plan 1) covers the rest.
└── UNKNOWN → Run P2 measurement while investigating P1 further.
```

### Backlog (not scheduled)

- P4 (sidecar PR): File as feature request with Qoder. Do NOT schedule.
- P5 (Hermes pipe mode): File as feature request with Hermes maintainers.

---

## §8 DESIGN CONSTRAINTS

### Security (ANSI injection mitigation)

Tool output within qodercli can contain forged progress markers (Trail of Bits,
2025). If a malicious file contains `Thinking... (esc to cancel, 999s)` or fake
tool markers, the parser would report false progress.

Mitigations:
- Parser output is **advisory only** — never feeds directly into kill/keep-alive
  decisions without human/model judgment.
- Sequence-number or timestamp monotonicity check: forged markers with
  non-monotonic elapsed times are flagged.
- Prefer sidecar file (P4, qodercli-written) over PTY parsing for trust-critical
  state — only qodercli can write its own progress file.

### Version drift

qodercli auto-updates (observed mid-session: "Update successful! The new version
will be used on your next run"). TUI format is NOT a stable API.

Mitigations:
- Parser must degrade gracefully: if regex hit-rate drops below 20% across a
  capture, emit a warning rather than silently reporting "no signal."
- Pin qodercli version in capture metadata for reproducibility.
- Treat parser as disposable: design for easy replacement when TUI changes.

### Idle/waiting state

Parser must distinguish "qodercli finished, awaiting input" (`Type your message
or @path/to/file`) from "still working." If Hermes doesn't recognize idle state,
it either polls forever (new stuck mode) or sends unintended input.

---

## §9 RCF FORECAST

```yaml
reference_class:
  action_1: "closed-binary reverse-engineering + API discovery"
  action_2: "measurement script over existing data"
  action_3: "regex/ETL parser over adversarial semi-structured TUI output"
  action_4: "external-contribution-to-closed-commercial-CLI"
  action_5: "architectural change to agent framework process-spawning"

base_rates:
  action_1: {median: 3h, mean: 4.5h, stddev: 3h, range: "1-12h"}
  action_2: {median: 1h, mean: 1.5h, stddev: 0.5h, range: "0.5-3h"}
  action_3: {median: 6h, mean: 8h, stddev: 5h, range: "3-20h"}
  action_4: {median: "6 weeks calendar", acceptance: "20-40%"}
  action_5: {median: "4 weeks", mean: "6 weeks", range: "2-8 weeks"}

pre_mortem:
  - risk: "Building parser before P1 resolves (wasted work)"
    probability: 0.35
    why_it_fails: "P1 answer may make parser moot"
    earliest_test: "Run P1 FIRST (hard gate)"
  - risk: "TUI format drift breaks regexes within 1-2 releases"
    probability: 0.6
    why_it_fails: "qodercli auto-updates; TUI is not a stable API"
    earliest_test: "npm view @qoder-ai/qodercli time → release frequency"
  - risk: "48% recovery is too low to change model behavior"
    probability: 0.85
    why_it_fails: "52% of polls still show zero signal; model still sees spinners"
    earliest_test: "ALREADY CONFIRMED — 48% measured"
  - risk: "SDK JSONL flag doesn't exist as user-facing mechanism"
    probability: 0.5
    why_it_fails: "Activation is SDK-internal spawn logic, not a CLI flag"
    earliest_test: "grep spawn/execFile in bundle → inspect argv construction"
  - risk: "Upstream PRs never land"
    probability: 0.6
    why_it_fails: "No public repo found; commercial product"
    earliest_test: "find /opt/homebrew/lib/node_modules/@qoder-ai/ -name CONTRIBUTING"

adjusted_forecast:
  scenarios:
    - name: OPTIMISTIC
      trigger: "P1 proves pipe spawn + JSONL activation exists"
      duration: "3-5 days"
      buffer: "mean + 0.25σ"
    - name: BASE
      trigger: "P1 partial (pipe yes, no flag) or PTY locked"
      duration: "1-2 weeks"
      buffer: "mean + 0.5σ (black-box tax: qodercli + Hermes)"
    - name: PESSIMISTIC
      trigger: "P1 fails (PTY locked, no flag, upstream unresponsive)"
      duration: "Behavioral fix only; parser delivers marginal value"
      buffer: "mean + 1σ"

infrastructure_tax:
  qodercli: "HIGH — closed binary, no source, frequent auto-update, no stable output API"
  hermes_terminal: "MEDIUM — undocumented poll semantics, no pipe mode confirmed"
  combined: "Both black boxes controlled by external parties. Locus of control limited to CTA-side post-processing + behavioral guidance."

tdd_tax: "+0.5σ on action_3 (plan lists NO tests for regex parser)"

simplification_checks:
  - "Measure BEFORE building: 30-line script over existing data (1h) replaces 7h parser if recovery is too low"
  - "Single signal (ctx%) not four: highest-frequency signal at 47%, covers liveness"
  - "No ANSI stripper needed: output is already ANSI-stripped (0 ESC chars)"
  - "No data model integration: emit signals as sidecar list, zero schema change"
  - "P4/P5 to backlog: cannot be scheduled, external dependency"
  - "Compare ROI against behavioral fix (Plan 1 patience guidance): 30 min, zero infra"
```

### The uncomfortable truth

The behavioral stop-gap (SKILL.md patience guidance from Plan 1) may deliver 80%
of the value at 1% of the cost. The regex parser addresses a symptom (no progress
signal) rather than the actual failure mode (model has no patience heuristic).
The plan must explicitly compare ROI against the behavioral fix before investing
in parsing infrastructure.

---

## §10 MINIMUM VIABLE PLAN

Total effort: **4–6h** (vs original implied 10–20h+)

| Step | Action | Time | Deliverable |
|---|---|---|---|
| 1 | P1: SDK flag search + Hermes pipe check | 3h base | Go/no-go decision |
| 2 | Measurement script over existing captures | 1h | Quantified hit-rate per signal |
| 3 | If recovery >40%: single ctx% liveness flag in report | 2h | Working liveness detector |
| 4 | Deploy Plan 1 behavioral fix (SKILL.md patience) | 0.5h | Immediate value |
| 5 | File P4/P5 as external feature requests | 0.5h | Documented options |

Delivers: quantified signal recovery, a working liveness detector for the 47% of
polls containing ctx%, behavioral fix deployment, and clear go/no-go for further
investment. Does NOT solve the fundamental window problem (requires upstream).

---

## §11 SOURCES

- Qoder SDK wire protocol: `/opt/homebrew/lib/node_modules/@qoder-ai/qodercli/bundle/qodercli.js`
- Qoder SDK skill guide: `/opt/homebrew/lib/node_modules/@qoder-ai/qodercli/bundle/builtin/sdk/SKILL.md`
- A2A protocol: https://a2a-protocol.org/dev/topics/life-of-a-task/
- Claude Code stream-json: https://code.claude.com/docs/en/agent-sdk/streaming-output
- Codex exec --json: https://takopi.dev/reference/runners/codex/exec-json-cheatsheet/
- ANSI injection: https://blog.trailofbits.com/2025/04/29/deceiving-users-with-ansi-terminal-codes-in-mcp/
- Empirical data: `data/m3_captures/P1-interactive-kimi-treatment-2/state.db` (75 polls, measured 2026-07-21)

---

## §12 REVIEW METADATA

```yaml
review_date: 2026-07-21
review_version: 2.0
adversarial_findings: {HIGH: 3, MEDIUM: 7, LOW: 3}
assumptions_audited: 13
assumptions_broken: 5 (#2, #4, #8, #10, #13)
assumptions_proven: 1 (#1)
assumptions_partial: 3 (#3, #7, #11)
assumptions_unverified: 4 (#5, #6, #9, #12)
rcf_scenarios: 3 (optimistic/base/pessimistic)
key_corrections:
  - "OSC sideband dead (0 ESC chars in polls)"
  - "80% → 48% signal recovery (measured)"
  - "-p -o json is single blob, not stream"
  - "1000-char window → max 658 chars (measured)"
  - "84 polls → 75 polls (corrected)"
  - "Schema 'solved' → partially solved (sub-agents only, not main session)"
  - "P2 front-loaded → P1 is HARD GATE"
```
