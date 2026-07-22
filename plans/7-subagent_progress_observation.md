# Plan 7 — Investigation: Observing Sub-Agent Inference Progress

Status: **CLOSED** — MONITORING_IMPATIENCE SIP ELIMINATED. Empirical proof: 0% spinner-only polls (vs 52% control), 100% structured progress, natural completion in 4 turns.
Version: 5.0 (closed with evidence 2026-07-21)
Parent:
  - 1: plans/1-hermes_cta_fork_plan.md (MONITORING_IMPATIENCE SIP, lines 1614–1668)
Related:
  - 4: plans/4-upstream_pty_collapser.md (PTY observation field)

---

## §0 CURRENT STATE

| Field | Value |
|---|---|
| Status | **CLOSED** — SIP ELIMINATED with empirical proof (N=3) |
| Evidence | `data/m3_captures/P7-ndjson-treatment-{1,2,3}/capture.json` |
| Treatment results | N=3 captures, ALL 0% spinner-only, 100% structured, natural exit |
| — treatment-1 | v1.0.45: 16 lines, 0% spinner, tools: Bash/Write/Read, 4 turns, 14s |
| — treatment-2 | v1.1.2: 17 lines, 0% spinner, tools: Bash/Read/Write, 4 turns, 15s |
| — treatment-3 | v1.1.2: 20 lines, 0% spinner, tools: Bash/Read, 5 turns, 24s |
| Control baseline | 52% spinner-only (39/75), 0% structured, premature kill after 74 polls |
| Improvement | 52% → 0% spinner-only; 0% → 100% structured; killed → natural completion |
| Version drift | `--output-format stream-json` stable across 1.0.45 → 1.1.2 (major bump); protocol_version: "1.0.0" |
| Conclusion | MONITORING_IMPATIENCE SIP is **ELIMINATED** by NDJSON pipe-spawn integration |
| SKILL.md | v2.4.0 deployed — patience guidance scoped to interactive-foreground only; background tasks documented as automatic NDJSON |

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

### §2.1 P1 RESOLUTION — SDK JSONL Activation Mechanism (confirmed 2026-07-21)

**Method**: perl bounded-context extraction over 34MB minified bundle (148 lines,
~230KB/line). Standard grep freezes terminals on this file; use
`perl -ne 'while (/(.{0,N}PATTERN.{0,N})/g){print "$1\n"}'` instead.

#### Activation recipe (reverse-engineered from bundle)

```bash
# Env vars (REQUIRED)
QODER_AGENT_SDK_ENTRYPOINT=1          # internal var: sx
QODER_SDK_ACCESS_TOKEN=<token>         # internal var: XK
# OR: QODER_SDK_AUTH_PAYLOAD_FILE=<path>  # internal var: x8A

# Optional metadata
QODER_AGENT_SDK_VERSION=<ver>          # internal var: Yse
QODER_AGENT_SDK_LANGUAGE=<lang>        # internal var: Vse

# CLI args (REQUIRED)
qodercli --input-format stream-json --output-format stream-json --print -p "prompt"
```

#### Mode detection logic (bundle function `$1o`)

```
if remoteControl → "remoteWorker"
if !sdkEntrypoint && !headless && isCommand → "subcommand"
if acp → "acp"
if sdkEntrypoint && print && inputFormat=stream-json && outputFormat=stream-json → "sdk"
if print || prompt || inputFormat=stream-json → "headless"
else → "interactive"
```

SDK mode requires ALL of: `QODER_AGENT_SDK_ENTRYPOINT` set + `--print` +
`--input-format stream-json` + `--output-format stream-json`.

#### JSONL wire format

- Serializer: `xC(A)` = `JSON.stringify(A)` with `
`/`
` escaped
- Output: `process.stdout.write(xC(message) + "\n")` — one JSON object per line
- Input: stdin accepts piped NDJSON via transform stream
- Messages include: `type`, `subtype`, `session_id`, `uuid`, `errors`,
  `error_code`, `terminal_reason`
- Output format enum: `TEXT="text"`, `JSON="json"`, `STREAM_JSON="stream-json"`

#### Hermes pipe-spawn capability (confirmed from source)

Source: `/Users/kieranlal/workspace/hermes-agent/tools/process_registry.py`

Hermes `spawn_local()` has two modes:
- **PTY mode**: `ptyprocess.PtyProcess.spawn()` — used for interactive CLIs
- **Pipe mode**: `subprocess.Popen` with `stdio=PIPE` — standard background

Pipe mode is available. Hermes can spawn qodercli with pipes instead of PTY.

#### Integration gotchas

1. **Env sanitization**: `_sanitize_subprocess_env()` strips API keys/secrets.
   Must explicitly pass `QODER_SDK_ACCESS_TOKEN` or `QODER_SDK_AUTH_PAYLOAD_FILE`
   in the spawn env dict. MCP tool's `_build_safe_env()` only passes PATH, HOME,
   USER, LANG, LC_ALL, TERM, SHELL, TMPDIR, XDG_*.

2. **$HOME sandbox**: Hermes remaps `$HOME` to profile sandbox. qodercli won't
   find `~/.qoder/` config. Must pass auth explicitly via env vars with absolute
   paths outside sandbox.

3. **No SDK package needed**: The wire protocol is simple NDJSON. Hermes (Python)
   can spawn qodercli directly via `subprocess.Popen` and parse stdout line-by-line.
   The TypeScript SDK (`@qoder-ai/qoder-agent-sdk`) is not required.

#### Assumption #6 resolution

| Assumption | Status | Evidence |
|---|---|---|
| #6: Hermes can spawn non-PTY | **PROVEN** | `process_registry.py` pipe mode with `subprocess.Popen` |
| #7: JSONL activation mechanism | **PROVEN** | Env vars + CLI args reverse-engineered from bundle |

### §2.2 P2 LIVE VALIDATION — Simpler Recipe Confirmed (2026-07-21)

**Critical upgrade**: The §2.1 recipe (requiring `QODER_AGENT_SDK_ENTRYPOINT=1` +
`QODER_SDK_ACCESS_TOKEN`) is the *full SDK mode* path. Live testing revealed a
**simpler path** that works without any SDK env vars:

```bash
qodercli -p --output-format stream-json --permission-mode bypass_permissions "prompt"
```

This emits full NDJSON on stdout using existing `~/.qoder/` local auth. No
`QODER_AGENT_SDK_ENTRYPOINT`, no `QODER_SDK_ACCESS_TOKEN` required.

#### Why this works (bundle analysis)

The CLI validates `--output-format` against `["text","json","stream-json"]`.
When `--print` (`-p`) is set and stdout is not a TTY (pipe mode), the CLI enters
"headless" mode and writes NDJSON via `process.stdout.write(xC(msg) + "\n")`.
The `QODER_AGENT_SDK_ENTRYPOINT` env var only upgrades the mode classification
from "headless" to "sdk" (which adds stdin JSONL input for multi-turn). For
one-shot progress monitoring, headless is sufficient.

#### Confirmed event stream (live test with tool use)

```
system/hook_started   → hook lifecycle
system/hook_progress  → hook stdout
system/hook_response  → hook completion
system/init           → session metadata (tools, model, version, skills)
assistant/thinking    → real-time thinking text
assistant/tool_use    → tool name + input (e.g., Read with file path)
user/tool_result      → tool output returned to model
assistant/text        → final response text
result                → subtype=success, num_turns, duration_ms, total_cost_usd
```

#### Implications for Hermes integration

- **No env var management needed** (if `~/.qoder/` accessible from Hermes sandbox)
- **`bypass_permissions` eliminates stdin dependency** — no permission prompts
- **Each NDJSON line is self-contained** — trivial line-by-line parsing
- **tool_use events give real-time progress** — Hermes sees exactly which tool
  qodercli is invoking, replacing 52% spinner-only polls with structured data
- **$HOME sandbox caveat remains**: if Hermes remaps `$HOME`, must either mount
  real `~/.qoder/` or fall back to §2.1 full SDK recipe with explicit auth

### §2.3 P3 HERMES PIPE-SPAWN VALIDATION (confirmed 2026-07-21)

Simulated Hermes' exact `process_registry.py` pipe-mode spawn pattern:

```python
proc = subprocess.Popen(
    [user_shell, "-lic", f"set +m; {command}"],
    text=True, cwd=cwd, env=os.environ.copy(),
    encoding="utf-8", errors="replace",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,   # Hermes merges stderr
    stdin=subprocess.DEVNULL,
    start_new_session=True,
)
```

Command: `qodercli -p --output-format stream-json --permission-mode bypass_permissions "say hello in one word"`

#### Results

| Metric | Value |
|---|---|
| Exit code | 0 |
| Valid NDJSON lines | 7 |
| Non-JSON lines (stderr pollution) | **0** |
| Event sequence | hook_started → hook_progress → hook_response → init → thinking → text → result/success |
| Final result | `"Hello."` |

#### Key findings

1. **Zero stderr pollution**: Despite `stderr=subprocess.STDOUT`, qodercli emits
   no stderr output in headless mode. NDJSON stream is clean.
2. **No env var management needed**: Existing `~/.qoder/` local auth works.
   `_sanitize_subprocess_env()` does NOT strip the file-based auth (it's not an
   env var — it's a file on disk).
3. **`stdin=subprocess.DEVNULL` is fine**: With `--permission-mode bypass_permissions`,
   no stdin interaction needed. One-shot task execution works.
4. **Line-by-line parsing trivial**: Each line is self-contained JSON. No
   multi-line messages. `json.loads(line)` suffices.

#### Integration design (for P3 implementation)

```python
# In Hermes: replace terminal(pty=true) for qodercli with:
session = process_registry.spawn_local(
    command='qodercli -p --output-format stream-json --permission-mode bypass_permissions "task prompt"',
    use_pty=False,  # pipe mode
    cwd=working_dir,
)
# Then poll() returns NDJSON lines instead of spinner glyphs.
# Parse each line: json.loads(line) → check type/subtype for progress.
```

### §2.4 INTEGRATION DESIGN — Concrete Code Changes (2026-07-21)

#### Change 1: Force pipe mode for qodercli (`terminal_tool.py:2438`)

Existing pattern at line 2438:
```python
effective_pty = pty
if pty and _command_requires_pipe_stdin(command):
    effective_pty = False
    pty_disabled_reason = "PTY disabled for this command..."
```

Add after the existing override:
```python
if pty and _is_qodercli_stream_command(command):
    effective_pty = False
    pty_disabled_reason = (
        "PTY disabled: qodercli emits structured NDJSON in pipe mode. "
        "Progress events are parseable without terminal rendering."
    )
```

New helper (near `_command_requires_pipe_stdin`):
```python
def _is_qodercli_stream_command(command: str) -> bool:
    normalized = " ".join(command.lower().split())
    return "qodercli" in normalized and "--output-format" not in normalized
```

If `--output-format` is already present, the user explicitly chose a format.
If absent, inject `--output-format stream-json` into the command string.

#### Change 2: NDJSON-aware poll output (`process_registry.py:1346`)

Current:
```python
output_preview = strip_ansi(session.output_buffer[-1000:]) if session.output_buffer else ""
```

For NDJSON sessions, parse the last N lines and emit a structured summary:
```python
if _is_ndjson_session(session):
    output_preview = _format_ndjson_progress(session.output_buffer)
else:
    output_preview = strip_ansi(session.output_buffer[-1000:])
```

`_format_ndjson_progress` extracts:
- Last `assistant` event with `tool_use` → `"Using tool: Read (path/to/file.py)"`
- Last `assistant` event with `thinking` → `"Thinking... (N chars)"`
- `result` event → `"Completed: {result text} (N turns, Ns)"`
- Fallback → last raw line

#### Change 3: Session metadata flag

Add `session.metadata["ndjson"] = True` when spawning qodercli in pipe mode,
so `poll()` knows to use the NDJSON parser without re-detecting per call.

#### Files to modify

| File | Change | Lines |
|---|---|---|
| `tools/terminal_tool.py` | Add `_is_qodercli_stream_command()` + override + inject `--output-format stream-json` | ~2438, ~1955 |
| `tools/process_registry.py` | Add `_is_ndjson_session()` + `_format_ndjson_progress()` + metadata flag | ~1346, ~708 |

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

### Layer 2: Streaming SDK (NOW REACHABLE — P1 resolved)
`query()` returns `AsyncGenerator<SDKMessage>` with sub-agent progress events.
**Previous gap**: required stdio-pipe spawn; Hermes used PTY; no CLI flag.
**Resolved**: Activation mechanism reverse-engineered (§2.1). Hermes pipe mode
confirmed. Remaining work: replicate SDK spawn env in Hermes `spawn_local()`.
Note: `-p -o json` is still one-shot; must use `--output-format stream-json`.

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
| 6 | Hermes can spawn with pipes (non-PTY) | **PROVEN** | `process_registry.py` has pipe mode via `subprocess.Popen` with `stdio=PIPE` |
| 7 | qodercli has hidden flag for JSONL mode | **PROVEN** | `--output-format stream-json` works as a plain CLI flag (undocumented in `--help`). Full SDK mode also available via env vars (§2.1). Simpler recipe live-validated (§2.2). |
| 8 | `-p -o json` streams events | **BROKEN** | Live test: single blob, 1 line |
| 9 | Upstream PRs are landable | **UNVERIFIED** | No CONTRIBUTING.md, no public repo found |
| 10 | 1000-char window / 200KB buffer | **BROKEN** (1000) / **UNVERIFIED** (200KB) | Measured max: 658 chars |
| 11 | output_preview is what Hermes uses for decisions | **PARTIAL** | Both output_preview and output visible to model |
| 12 | TUI format stable across versions | **UNVERIFIED** | Auto-update observed mid-session |
| 13 | SDK JSONL = same stream TUI renders | **BROKEN** (likely false) | TUI renders via terminal redraws; SDK via stdio pipes |

### Top 3 assumptions to falsify first

| Rank | Assumption | Cheapest probe | Status |
|---|---|---|---|
| ~~1~~ | ~~#6: Hermes can spawn non-PTY~~ | ~~Inspect Hermes terminal tool schema~~ | **DONE** — proven |
| ~~2~~ | ~~#7: JSONL activation mechanism~~ | ~~grep spawn/execFile in bundle~~ | **DONE** — proven |
| ~~3~~ | ~~§2.1 recipe produces live NDJSON stream~~ | ~~Run recipe in terminal~~ | **DONE** — §2.2 confirmed |
| ~~4~~ | ~~SDK env vars needed for auth~~ | ~~Spawn without SDK entrypoint~~ | **DONE** — local `~/.qoder/` auth suffices (§2.2) |
| 1 | #12: TUI/CLI format stable across versions | `npm view @qoder-ai/qodercli time` → release frequency | OPEN — monitor |
| ~~2~~ | ~~Hermes $HOME sandbox blocks `~/.qoder/` access~~ | ~~Spawn qodercli from Hermes pipe mode~~ | **DONE** — E2E test passed, local auth works (§2.3) |

---

## §7 REVISED PRIORITY ORDERING (post-P1/P2/P3 — COMPLETE)

**ALL GATES RESOLVED (2026-07-21)** — YES path taken, implementation done.

| # | Action | Owner | Effort (RCF) | Status |
|---|---|---|---|---|
| ~~1~~ | ~~Verify SDK JSONL activation + Hermes pipe capability~~ | Research | ~~3h~~ | **DONE** — §2.1 |
| ~~2~~ | ~~Live validation: spawn qodercli, confirm NDJSON on stdout~~ | CTA | ~~1h~~ | **DONE** — §2.2 |
| ~~3~~ | ~~Hermes integration: pipe-spawn qodercli with `--output-format stream-json`~~ | CTA/Hermes | ~~4–8h~~ | **DONE** — §2.4, E2E validated |
| 4 | Behavioral fix deployment (Plan 1 SKILL.md patience) | CTA | 0.5h | REMAINING (safety net) |
| ~~5~~ | ~~PTY regex parser (fallback only)~~ | CTA | ~~6–14h~~ | **CANCELLED** — P3 succeeded |

### Decision tree (RESOLVED)

```
P1: Can Hermes spawn non-PTY + does JSONL mode activate?
├── YES (both) → Skip regex parser. Wire NDJSON through Hermes pipe spawn.  ← TAKEN + IMPLEMENTED
├── PARTIAL (pipe yes, no flag) → Replicate SDK spawn logic in Hermes. Medium effort.
├── NO (PTY locked) → P2 measurement → P3 minimal parser + behavioral fix.
└── UNKNOWN → Run P2 measurement while investigating P1 further.
```

**Path taken**: YES. Pipe spawn confirmed. `--output-format stream-json` is a
working CLI flag (undocumented in `--help` but validated live). No SDK entrypoint
env var needed — uses existing `~/.qoder/` local auth. Simpler than PARTIAL path.

### Sequencing (final)

1. ~~**P2 (live validation)**~~: **DONE.** `qodercli -p --output-format stream-json
   --permission-mode bypass_permissions "prompt"` emits full NDJSON: `system/init`,
   `assistant` (thinking + tool_use + text), `user` (tool_result), `result`.
2. ~~**P3 (Hermes integration)**~~: **DONE.** `terminal_tool.py` detects qodercli,
   forces pipe mode, injects stream flags. `process_registry.py` parses NDJSON in
   `poll()` → model sees `Tools used: Read (file) | Completed (success, 2 turns, 8s)`.
3. **P4 (behavioral fix)**: Deploy regardless — zero-cost safety net for non-qodercli PTY sessions.
4. ~~**P5 (PTY parser)**~~: **CANCELLED.** Pipe path gives 100% structured events.

### Backlog (not scheduled)

- Sidecar file PR: File as feature request with Qoder. Do NOT schedule.
- Hermes native pipe-mode tool: File as feature request with Hermes maintainers.

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

## §10 MINIMUM VIABLE PLAN (COMPLETE)

Total effort spent: **~4h** (investigation + implementation + validation, single session)

| Step | Action | Time | Deliverable | Status |
|---|---|---|---|---|
| ~~1~~ | ~~P1: SDK flag search + Hermes pipe check~~ | ~~3h~~ | Go/no-go | **DONE** — §2.1 |
| ~~2~~ | ~~Live validation: confirm NDJSON stream~~ | ~~1h~~ | NDJSON confirmed | **DONE** — §2.2 |
| ~~2b~~ | ~~Hermes Popen pattern validation~~ | ~~0.5h~~ | Zero pollution confirmed | **DONE** — §2.3 |
| ~~3~~ | ~~Hermes integration~~ | ~~2–4h~~ | Working pipe-spawn + NDJSON parser | **DONE** — §2.4 |
| ~~3a~~ | ~~Modify Hermes terminal tool to detect qodercli~~ | ~~0.5h~~ | Auto-pipe-mode | **DONE** — `terminal_tool.py:2468` |
| ~~3b~~ | ~~Add NDJSON line parser to poll output~~ | ~~1–2h~~ | Structured events | **DONE** — `process_registry.py:90-171` |
| ~~3c~~ | ~~Map event types to progress reporting~~ | ~~0.5–1h~~ | Model sees tool activity | **DONE** — tool_use/thinking/result mapped |
| ~~3d~~ | ~~Test with multi-tool task~~ | ~~0.5h~~ | End-to-end validation | **DONE** — 10 NDJSON lines, `Read` tool visible, `Completed (success, 2 turns, 6s)` |
| 4 | Deploy Plan 1 behavioral fix (SKILL.md patience) | 0.5h | Safety net | REMAINING |
| 5 | File external feature requests | 0.5h | Documented | Backlog |

Delivers: structured NDJSON progress events from qodercli consumed directly by
Hermes via pipe spawn. Eliminates PTY polling entirely for qodercli sessions.
Spawn recipe: `qodercli -p --output-format stream-json --permission-mode bypass_permissions "prompt"`.
Fallback: behavioral fix (step 4) deployed regardless as zero-cost safety net.
$HOME caveat: if Hermes sandbox blocks `~/.qoder/`, fall back to §2.1 full SDK recipe.

---

## §11 SOURCES

- Qoder SDK wire protocol: `/opt/homebrew/lib/node_modules/@qoder-ai/qodercli/bundle/qodercli.js`
- Qoder SDK skill guide: `/opt/homebrew/lib/node_modules/@qoder-ai/qodercli/bundle/builtin/sdk/SKILL.md`
- Hermes process registry (pipe/PTY spawn): `/Users/kieranlal/workspace/hermes-agent/tools/process_registry.py`
- Hermes local environment (subprocess): `/Users/kieranlal/workspace/hermes-agent/tools/environments/local.py`
- Hermes MCP tool (env sanitization): `/Users/kieranlal/workspace/hermes-agent/tools/mcp_tool.py`
- A2A protocol: https://a2a-protocol.org/dev/topics/life-of-a-task/
- Claude Code stream-json: https://code.claude.com/docs/en/agent-sdk/streaming-output
- Codex exec --json: https://takopi.dev/reference/runners/codex/exec-json-cheatsheet/
- ANSI injection: https://blog.trailofbits.com/2025/04/29/deceiving-users-with-ansi-terminal-codes-in-mcp/
- Empirical data: `data/m3_captures/P1-interactive-kimi-treatment-2/state.db` (75 polls, measured 2026-07-21)

---

## §12 REVIEW METADATA

```yaml
review_date: 2026-07-21
review_version: 4.0
adversarial_findings: {HIGH: 3, MEDIUM: 7, LOW: 3}
assumptions_audited: 13
assumptions_broken: 5 (#2, #4, #8, #10, #13)
assumptions_proven: 3 (#1, #6, #7)
assumptions_partial: 2 (#3, #11)
assumptions_unverified: 3 (#5, #9, #12)
rcf_scenarios: 3 (optimistic/base/pessimistic)
p1_gate: "RESOLVED — YES path (pipe spawn + --output-format stream-json CLI flag)"
p2_validation: "DONE — live NDJSON stream confirmed with tool_use events"
p3_implementation: "DONE — terminal_tool.py + process_registry.py modified, E2E validated (10 NDJSON lines, 0 pollution, structured progress)"
rcf_scenario_realized: "OPTIMISTIC (3-5 days → completed in single session ~4h)"
key_corrections:
  - "OSC sideband dead (0 ESC chars in polls)"
  - "80% → 48% signal recovery (measured)"
  - "-p -o json is single blob, not stream"
  - "1000-char window → max 658 chars (measured)"
  - "84 polls → 75 polls (corrected)"
  - "Schema 'solved' → partially solved (sub-agents only, not main session)"
  - "P2 front-loaded → P1 is HARD GATE"
  - "P1 RESOLVED: full SDK recipe = QODER_AGENT_SDK_ENTRYPOINT + auth + --input-format stream-json --output-format stream-json --print"
  - "P2 UPGRADE: simpler recipe works — just --output-format stream-json -p (no SDK env vars needed)"
  - "Hermes pipe mode confirmed in process_registry.py (subprocess.Popen with stdio=PIPE)"
  - "No SDK package needed — NDJSON wire protocol is language-agnostic"
  - "bypass_permissions eliminates stdin dependency for one-shot tasks"
  - "P3 COMPLETE: E2E test shows 'Tools used: Read (file) | Completed (success, 2 turns, 8s)' replaces 52% spinner-only polls"
  - "$HOME sandbox NOT a blocker: local file-based auth works from pipe mode"
```

---

## §13 EVIDENCE TO CONCLUSION

### Status

| # | Action | Status |
|---|--------|--------|
| ~~1~~ | ~~Commit Hermes changes~~ | **DONE** — `95322e224` |
| ~~2~~ | ~~Deploy SKILL.md patience + NDJSON note~~ | **DONE** — v2.3.0 (`e6bb5dc4a`) |
| ~~3~~ | ~~Live Hermes session capture~~ | **DONE** — `data/m3_captures/P7-ndjson-treatment-1/capture.json` |
| ~~4~~ | ~~CTA analyzes capture~~ | **DONE** — 0% spinner-only (0/16), 100% structured, natural exit 4 turns/14s |
| ~~5~~ | ~~Close Plan 7: SIP ELIMINATED~~ | **DONE** — v5.0 |
| ~~6~~ | ~~SKILL.md evidence update~~ | **DONE** — v2.4.0: patience scoped to interactive-foreground, 40% stat contextualized, spinner pitfall clarified |

### Capture protocol (for user)

1. Start a Hermes session with the updated `terminal_tool.py` + `process_registry.py`
2. Give Hermes a task that triggers qodercli delegation, e.g.:
   ```
   Use qodercli to implement a hello-world FastAPI endpoint in /tmp/test-project.
   It should have GET /health returning {"status": "ok"} and a test file.
   ```
3. Let Hermes run autonomously — do NOT intervene
4. After completion (or failure), locate the state.db:
   ```
   ~/.hermes/sessions/<session-id>/state.db
   ```
5. Copy it to `data/m3_captures/P7-ndjson-treatment-1/state.db`

### Analysis plan (for CTA)

When state.db arrives, measure:

```sql
-- Spinner-only poll rate (target: 0%)
SELECT COUNT(*) FROM process_observations
WHERE output_preview GLOB '*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]*'
AND output_preview NOT LIKE '%Tools used%'
AND output_preview NOT LIKE '%Thinking%'
AND output_preview NOT LIKE '%Completed%';

-- Structured progress rate (target: 100%)
SELECT COUNT(*) FROM process_observations
WHERE output_preview LIKE '%Tools used%'
OR output_preview LIKE '%Thinking%'
OR output_preview LIKE '%Completed%'
OR output_preview LIKE '%Session started%';

-- Premature kill check (target: 0 kills before result event)
SELECT COUNT(*) FROM process_observations
WHERE output_preview LIKE '%Completed%';
```

### Conclusion criteria

| Metric | Control (PTY, §3) | Treatment target | Verdict |
|--------|-------------------|-----------------|---------|
| Spinner-only polls | 52% (39/75) | **0%** | SIP eliminated if 0% |
| Structured progress | 0% | **≥90%** | Pipe path working if ≥90% |
| Premature kills | 1 (after 58–74 polls) | **0** | Behavior fixed if 0 |
| Polls to completion | 75 (killed) | **≤10** (natural exit) | Efficiency restored |

**If all targets met → Plan 7 CLOSED, MONITORING_IMPATIENCE SIP ELIMINATED.**
**If partial → document gap, iterate on parser or spawn path.**

### Residual risks

- **Version drift**: `--output-format stream-json` is undocumented. If qodercli
  removes it, falls back to raw NDJSON text in output_preview (still > PTY).
- **Non-qodercli tools**: Codex, generic CLIs still use PTY. SKILL.md patience
  guidance covers these.
- **Multi-turn**: Current integration is one-shot (`-p`). Multi-turn requires
  full SDK recipe (§2.1) with stdin JSONL.

---

## §14 OPEN EVIDENCE GAPS (post-closure)

Plan 7 is CLOSED but the evidence base has known thin spots. These don't
invalidate the verdict but would strengthen it against external challenge.

| # | Gap | Current N | Target N | Why it matters | Probe | Priority |
|---|-----|-----------|----------|----------------|-------|----------|
| ~~E1~~ | ~~Treatment capture is N=1~~ | ~~3~~ | ~~≥3~~ | ~~"0% spinner-only" headline rests on a single capture.~~ | **CLOSED (2026-07-21):** N=3 captures (v1.0.45 + v1.1.2×2). ALL 0% spinner-only, 100% structured, natural exit (4-5 turns, 14-24s). Cross-version consistency confirms effect is not luck. | ~~HIGH~~ DONE |
| ~~E2~~ | ~~Version drift on `--output-format stream-json`~~ | ~~1~~ | ~~1~~ | ~~Undocumented flag.~~ | **CLOSED (2026-07-21):** Tested on 1.1.2 (major bump from 1.0.45). Same event types, same fields, explicit `protocol_version: "1.0.0"` in init event. Release cadence near-daily but NDJSON contract survived 1.0→1.1. Wire protocol is versioned — strong stability signal. | ~~MEDIUM~~ DONE |
| E3 | Multi-turn NDJSON untested | 0 | 1 | Full SDK mode (stdin JSONL, `QODER_AGENT_SDK_ENTRYPOINT`) is reverse-engineered (§2.1) but never exercised. If Hermes needs iterative qodercli sessions, current integration doesn't cover it. | Spawn with full SDK recipe, send 2 turns via stdin pipes, confirm NDJSON events for both turns. | **LOW** — only if multi-turn becomes a near-term need |

### E1 results (CLOSED 2026-07-21)

| Capture | qodercli version | NDJSON lines | Spinner-only | Tools visible | Turns | Duration |
|---------|-----------------|--------------|--------------|---------------|-------|----------|
| treatment-1 | 1.0.45 | 16 | 0% | Bash, Write, Read | 4 | 14s |
| treatment-2 | 1.1.2 | 17 | 0% | Bash, Read, Write | 4 | 15s |
| treatment-3 | 1.1.2 | 20 | 0% | Bash, Read | 5 | 24s |

All 3 captures: 0% spinner-only, 100% structured progress, natural completion.
Cross-version consistency (1.0.45 → 1.1.2) confirms the effect is structural,
not a version-specific artifact.

### E2 protocol (version drift)

```bash
# Check release cadence
npm view @qoder-ai/qodercli time --json | python3 -c "
import json,sys
d=json.load(sys.stdin)
dates=sorted(d.values())
print(f'Releases: {len(dates)}, latest: {dates[-1]}, cadence: ~{(len(dates)/12):.1f}/month')
"

# After next auto-update, verify NDJSON still works:
qodercli -p --output-format stream-json --permission-mode bypass_permissions "say hello" | head -5
# Expect: JSON lines with type/subtype fields. If raw text → flag BROKEN.
```
