# Plan 8 — Runtime Friction Detection

Status: **PHASE 0 COMPLETE** — K2 resolved (K2a), proceeding to Phase 1
Version: 0.2.2 (2026-07-21)
Parent:
  - 7: plans/7-subagent_progress_observation.md (NDJSON wire protocol substrate)
  - 2: plans/2-cta_verification_layer_plan.md (Phase 6 bimodal CPI finding)
Related:
  - 1: plans/1-hermes_cta_fork_plan.md (G3 evidence gap → G7 proposed)

---

## §0 CURRENT STATE

| Field | Value |
|---|---|
| Status | **PHASE 0 COMPLETE** |
| Research question | Can we classify the environment regime (clean vs friction) at runtime from the NDJSON stream? |
| Substrate | `_format_ndjson_progress()` in `hermes-agent/tools/process_registry.py:90-171` |
| Motivation | Plan 2 Phase 6: CPI is bimodal (0.912 friction / 1.594 clean). Regime is currently discoverable only in post-hoc trace analysis. |
| Deliverable | Friction index in `process()` poll output that discriminates clean from friction-heavy sessions at runtime |
| K2 resolution | **K2a obtains.** `context_usage_ratio` present at `message.usage.context_usage_ratio` on every complete assistant event (stop_reason ≠ null). Full S1-S4 plan proceeds. |
| New blocker | G3 run 1 inner NDJSON stream NOT fully preserved — only truncated 1000-char poll fragments in state.db. Phase 1 retrospective requires re-capture or reconstruction from outer Hermes conversation. |
| Clean calibration | P7-3 scores friction_index=0.093 (< 0.15 threshold) with proper `tool:key_input[:80]` signatures. |

---

## §1 PROBLEM STATEMENT

Plan 2 Phase 6 established that CPI is **bimodal**:

| Regime | CPI | Character | Example |
|--------|-----|-----------|---------|
| Clean | 1.594 | No environment issues, linear execution | G3 run 2 (53 msgs) |
| Friction | 0.912 | Missing deps, import errors, debugging loops | G3 run 1 (92 msgs, Flask/werkzeug) |

The regime split is **environment-dependent, not mechanism-dependent**. NDJSON
eliminates monitoring overhead (Plan 7, CLOSED) but cannot eliminate environment
friction. The skill's value proposition depends on which regime the session lands in.

**The gap:** Hermes currently has no runtime signal for which regime a background
qodercli session is in. It discovers friction only after the session completes (or
times out) by reading the full trace. By then, context is already spent.

**The opportunity:** The NDJSON stream already contains the discriminating signals.
`_format_ndjson_progress()` parses the stream but extracts only tool names and
thinking state — it discards `user` events (where `tool_result` errors live) and
ignores `usage` metadata (where `context_usage_ratio` lives).

---

## §2 HYPOTHESIS (PRE-REGISTERED)

**H8:** A friction index computed from NDJSON stream signals (tool_result error rate,
context_usage_ratio velocity, retry pattern density) classifies sessions into
clean vs friction regimes with ≥80% agreement against the post-hoc CPI label
(CPI>1.0 = clean, CPI≤1.0 = friction).

**Falsification criterion:** If the friction index agrees with CPI labels on <80%
of labeled sessions (N≥6), H8 is REJECTED. The signals are either too noisy,
too lagged, or too weakly correlated with the actual CPI driver.

**Pre-registration note:** This threshold is set BEFORE implementation. The 80%
bar is deliberately below 100% — we expect edge cases (sessions that start clean
then hit friction mid-run, or vice versa). A classifier that's right 5/6 times
is still actionable for Hermes decision-making.

---

## §3 DESIGN

### 3.1 Signals

| # | Signal | Source in NDJSON | Computation | Rationale |
|---|--------|-----------------|-------------|-----------|
| S1 | Error rate | `user` → `tool_result` blocks + top-level `tool_use_result` | `error_count / tool_result_count` over last 50 events. Error = `tool_use_result.exitCode ≠ 0` (Bash) OR content matches error patterns (non-Bash fallback). Note: no `is_error` field exists in `tool_result` blocks (Phase 0). | G3 run 1: Flask import errors, werkzeug failures. Run 2: zero errors. exitCode is reliable binary signal; text matching is secondary. |
| S2 | Context velocity | `assistant` → `usage.context_usage_ratio` | `(ratio_last - ratio_first) / event_span` | Friction sessions burn context on remediation loops. Clean sessions grow linearly. |
| S3 | Retry density | `assistant` → `tool_use` blocks | `max(Counter(signatures)) / total_calls` where signature = `tool:key_input[:80]` | Same command retried 3+ times = stuck loop. G3 run 1 had repeated pip install attempts. |
| S4 | Context fullness | `assistant` → `usage.context_usage_ratio` (latest) | `ratio > 0.85` → binary flag | Approaching context limit = session is in trouble regardless of other signals. |

### 3.2 Friction index

```
friction_index = w1 * error_rate + w2 * ctx_velocity_norm + w3 * retry_density
```

Initial weights (equal): w1=w2=w3=1/3. Weights are calibrated in Phase 2 against
labeled data, not tuned to fit.

**Normalization:** `ctx_velocity_norm = min(ctx_velocity / 0.02, 1.0)`. The 0.02
ceiling means velocity above 2% context-per-event saturates at 1.0. Clean sessions
show ~0.0006/event (P7-3); 0.02 is ~33x the clean baseline. Friction sessions
(expected: >0.01/event from remediation loops) would score 0.5-1.0 on this term.

**Note on S4:** Context fullness (S4) is a display-only signal — it adds to the
warning string when friction_index ≥ 0.40 but does NOT contribute to the index
itself. Rationale: a session at 85% context is in trouble regardless of error rate
or retries, but fullness alone doesn't indicate *friction* (a long clean session
can also reach 85%).

**Display thresholds:**
- `friction_index < 0.15` → no display (clean regime)
- `0.15 ≤ friction_index < 0.40` → `"errors: N/M"` (mild friction)
- `friction_index ≥ 0.40` → `"⚠ Friction: HIGH-ERROR | CTX-VELOCITY | RETRY"` (heavy friction)

### 3.3 Integration point

Extends `_format_ndjson_progress()` in `process_registry.py`. The friction index
appends to the existing `" | ".join(parts)` output string. No new function, no new
module — the parser already iterates the same events.

**Constraint:** Must not increase poll output by >100 chars in the clean case
(zero overhead when friction is absent). In the friction case, the warning is
~60-80 chars.

### 3.4 Implementation (v0.2 — incorporates Phase 0 findings)

Phase 0 refinements over the original sketch:
- **Error detection:** `tool_use_result.exitCode ≠ 0` for Bash (no `is_error` field exists in `tool_result` blocks). Text matching is fallback for non-Bash tools only.
- **Context velocity:** `context_usage_ratio` only present on complete assistant events (`stop_reason ≠ null`). Streaming partials lack usage.
- **Retry signature:** MUST be `tool:key_input[:80]`, NOT tool name alone (A7: name-only matching gives false positive 0.26 on clean P7-3).

```python
def _format_ndjson_progress(output_buffer: str) -> str:
    """Parse NDJSON output from qodercli stream-json and produce a progress summary.

    Returns a compact human-readable string showing the latest activity,
    replacing spinner glyphs with structured tool/thinking/result events.
    Includes environment friction detection from tool_result errors,
    context velocity, and retry patterns.
    """
    lines = output_buffer.strip().split("\n")
    events = []
    for line in lines[-50:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        events.append(obj)

    if not events:
        return "[NDJSON: waiting for first event...]"

    parts = []
    tool_uses = []
    last_thinking_len = 0
    result_event = None
    init_event = None

    # --- Friction tracking state ---
    error_count = 0
    tool_result_count = 0
    context_ratios = []          # (event_index, ratio) pairs
    tool_call_signatures = []    # for retry detection

    ERROR_PATTERNS = (
        "Traceback (most recent call last)",
        "Error:",
        "error:",
        "FAILED",
        "Permission denied",
        "No such file or directory",
        "command not found",
        "ModuleNotFoundError",
        "ImportError",
        "ConnectionError",
        "kalloc",
    )

    for i, ev in enumerate(events):
        ev_type = ev.get("type", "")

        if ev_type == "system" and ev.get("subtype") == "init":
            init_event = ev

        elif ev_type == "assistant":
            msg = ev.get("message", {})

            # Context velocity: extract usage ratio from COMPLETE events only
            # (Phase 0: streaming partials with stop_reason=null lack usage)
            if msg.get("stop_reason") is not None:
                usage = msg.get("usage", {})
                ratio = usage.get("context_usage_ratio")
                if ratio is not None:
                    context_ratios.append((i, float(ratio)))

            for block in msg.get("content", []):
                bt = block.get("type", "")
                if bt == "tool_use":
                    name = block.get("name", "unknown")
                    inp = block.get("input", {})
                    detail = ""
                    if name in ("Read", "Edit", "Write") and "file_path" in inp:
                        detail = f" ({inp['file_path']})"
                    elif name == "Bash" and "command" in inp:
                        cmd = inp["command"][:60]
                        detail = f" ({cmd})"
                    elif name == "Grep" and "pattern" in inp:
                        detail = f" (/{inp['pattern']}/)"
                    elif name == "Agent" and "description" in inp:
                        detail = f" ({inp['description']})"
                    tool_uses.append(f"{name}{detail}")

                    # Retry detection: signature = tool name + key input (A7)
                    # Must cover all common tools to avoid false retries
                    sig_input = (inp.get("command") or inp.get("file_path")
                                 or inp.get("pattern") or inp.get("prompt")
                                 or inp.get("url") or inp.get("description")
                                 or str(inp)[:80] if inp else "")
                    tool_call_signatures.append(f"{name}:{str(sig_input)[:80]}")

                elif bt == "thinking":
                    last_thinking_len = len(block.get("thinking", ""))
                elif bt == "text":
                    text = block.get("text", "")
                    if text:
                        parts.append(f"Response: {text[:120]}")

        elif ev_type == "user":
            # --- Mine tool_result blocks for error signals ---
            # Phase 0: tool_use_result is TOP-LEVEL on the user event, not inside
            # the tool_result content block. Structure:
            #   ev["message"]["content'][] = {type: "tool_result", content: "..."}
            #   ev["tool_use_result"] = {exitCode: 0, ...}  ← TOP LEVEL
            tool_use_result = ev.get("tool_use_result", {})
            exit_code = tool_use_result.get("exitCode")

            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") != "tool_result":
                    continue
                tool_result_count += 1

                # Primary: exitCode is the reliable binary signal for Bash
                if exit_code is not None and exit_code != 0:
                    error_count += 1
                    continue

                # Fallback: text matching for non-Bash tools (no exitCode)
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                if any(pat in content for pat in ERROR_PATTERNS):
                    error_count += 1

        elif ev_type == "result":
            result_event = ev

    # --- Existing summary assembly ---
    if init_event and not tool_uses and not parts:
        model = init_event.get("model", "unknown")
        parts.append(f"Session started (model: {model})")

    if tool_uses:
        parts.append(f"Tools used: {', '.join(tool_uses[-5:])}")
        if len(tool_uses) > 5:
            parts[0] = f"Tools used ({len(tool_uses)} total): {', '.join(tool_uses[-5:])}"

    if last_thinking_len and not result_event:
        parts.append(f"Thinking... ({last_thinking_len} chars)")

    if result_event:
        subtype = result_event.get("subtype", "unknown")
        turns = result_event.get("num_turns", "?")
        duration = result_event.get("duration_ms", 0)
        dur_str = _format_duration(duration // 1000) if duration else "?"
        result_text = result_event.get("result", "")
        summary = f"Completed ({subtype}, {turns} turns, {dur_str})"
        if result_text:
            summary += f": {result_text[:100]}"
        parts.append(summary)

    # --- Friction index computation (§3.2 composite formula) ---
    from collections import Counter

    # Signal 1: Error rate
    error_rate = error_count / max(tool_result_count, 1)

    # Signal 2: Context velocity (normalized: 0.02/event = saturation)
    ctx_velocity = 0.0
    if len(context_ratios) >= 3:
        first_idx, first_ratio = context_ratios[0]
        last_idx, last_ratio = context_ratios[-1]
        span = last_idx - first_idx
        if span > 0:
            ctx_velocity = (last_ratio - first_ratio) / span
    ctx_velocity_norm = min(ctx_velocity / 0.02, 1.0)

    # Signal 3: Retry density
    sig_counts = Counter(tool_call_signatures)
    retry_density = max(sig_counts.values(), default=0) / max(len(tool_call_signatures), 1)

    # Composite friction index (equal weights, §3.2)
    friction_index = (error_rate + ctx_velocity_norm + retry_density) / 3

    # Display: composite score drives classification, signals explain why
    if friction_index >= 0.40:
        signals = []
        if error_rate > 0.3:
            signals.append(f"HIGH-ERROR ({error_count}/{tool_result_count})")
        if ctx_velocity > 0.02:
            signals.append(f"CTX-VELOCITY +{ctx_velocity:.1%}/ev")
        if retry_density > 0.3:
            worst = max(sig_counts.items(), key=lambda x: x[1])
            tool_name = worst[0].split(":")[0]
            signals.append(f"RETRY {tool_name} x{worst[1]}")
        if context_ratios and context_ratios[-1][1] > 0.85:
            signals.append(f"CTX-FULL {context_ratios[-1][1]:.0%}")
        parts.append(f"⚠ Friction: {' | '.join(signals)}")
    elif friction_index >= 0.15:
        parts.append(f"errors: {error_count}/{tool_result_count}")

    return " | ".join(parts) if parts else "[NDJSON: processing...]"
```

**Design rationale (mapped to empirical findings):**

| Signal | What it detects | Evidence basis |
|--------|----------------|----------------|
| Error rate (exitCode) | Environment broken (missing deps, permissions, kernel issues) | Run 1's kalloc.1024 failures, Flask import errors — the friction that drove CPI to 0.912 |
| Context velocity | Remediation loops burning context window | NDJSON poll responses are denser than spinners, so context fills faster during error recovery |
| Retry detection | Agent stuck in fix→fail→fix loops | "Verification/remediation loops are the real CPI driver" (§E4) |

**Thresholds are deliberately conservative** — they only fire on patterns that
would shift CPI below 1.0. A single error in 10 tool calls is normal development;
3+ errors in 5 calls is environment friction. The 0.02/event context velocity
threshold corresponds to "context exhausted within 50 events at current rate."

**Clean-case overhead:** Zero chars added when no signals fire (friction_index < 0.15).
**Friction-case output:** ~60-80 chars (e.g., `⚠  Friction: HIGH-ERROR (4/6) | RETRY Bash x4`).

---

## §4 VALIDATION PROTOCOL

### Phase 1a: Clean-session sanity check (immediate, no new captures)

Score existing P7 raw.ndjson captures against the friction index formula:

| Capture | Known regime | Expected friction_index | Actual (Phase 0) |
|---------|--------------|------------------------|-------------------|
| P7-ndjson-treatment-2 | clean (trivial task) | <0.15 | 0.086 (3 unique tool calls, 0 errors) |
| P7-ndjson-treatment-3 | clean (trivial task) | <0.15 | 0.086 (4 unique tool calls, 0 errors) |
| Synthetic friction (5/6 errors, 4x retry) | friction | ≥0.40 | 0.833 (HIGH-ERROR + CTX-VELOCITY + RETRY) |

**Gate:** All clean sessions must score <0.15. If any ≥0.15, the signature
definition or normalization is wrong. Fix before proceeding.

**Status:** PASS. Implementation validated end-to-end:
- Clean sessions: zero friction display (E3: 0 chars overhead ✓)
- Friction session: `⚠ Friction: HIGH-ERROR (5/6) | CTX-VELOCITY +4.2%/ev | RETRY Bash x4` (~70 chars, E4: ≤100 ✓)
- Implementation deployed to `data/ndjson_overlay/process_registry.py:_format_ndjson_progress()`

### Phase 1b: Friction-session capture (requires Hermes runtime)

**Original plan (BLOCKED by A6):** Score G3 run 1 (CPI=0.912, friction) retrospectively.
This is impossible — the inner qodercli NDJSON stream was consumed real-time and only
1000-char poll fragments survive in state.db.

**Revised plan:** Re-run the G3 run 1 task (Flask/JWT auth endpoint) with raw NDJSON
capture enabled (`--output-format stream-json` piped to file). Then compute
friction_index on the preserved stream.

| Capture | Known CPI | Known regime | Expected friction_index |
|---------|-----------|--------------|------------------------|
| Re-captured friction run | ~0.912 (expected) | friction | ≥0.40 |
| P7-ndjson-treatment-2 | N/A (short) | clean | 0.093 |
| P7-ndjson-treatment-3 | N/A (short) | clean | 0.093 |

**Gate:** Friction index must separate friction run from clean runs by ≥0.25 absolute.
If the gap is <0.25, the signals don't discriminate and H8 is in trouble.

#### Phase 1b Test Plan (v0.2.1)

**Objective:** Capture a real friction session's raw NDJSON stream and verify
friction_index ≥ 0.40 (separation ≥ 0.25 from clean baseline of 0.086).

**Approach A: Direct qodercli capture (preferred — no Hermes dependency)**

Run qodercli directly in a friction-inducing environment, capturing the raw
NDJSON stream to file. Then feed the file through `_format_ndjson_progress()`.

```bash
# 1. Set up friction environment (Docker container)
docker run --rm -it -v $(pwd)/data/m3_captures/P1-interactive-kimi-ndjson-treatment-1/workspace:/workspace \
  python:3.11-slim bash -c '
    cd /workspace
    # Remove flask to induce ModuleNotFoundError friction
    pip uninstall flask -y 2>/dev/null || true
    # Remove pyjwt to induce import errors
    pip uninstall pyjwt -y 2>/dev/null || true
    # Run qodercli with stream-json output, piped to file
    qodercli --output-format stream-json --permission-mode bypass_permissions \
      -p "Implement a REST API authentication endpoint in src/routes/auth.py \
          with JWT token validation middleware in src/middleware/token.py. \
          Run pytest to verify." \
      > /workspace/raw_friction.ndjson 2>/dev/null
  '

# 2. Score the captured stream
python3 -c "
import sys; sys.path.insert(0, 'data/ndjson_overlay')
# (extract function, feed raw_friction.ndjson as output_buffer)
# Compute friction_index and verify >= 0.40
"
```

**Friction inducers (environment, not task complexity):**
- Missing `flask` package → `ModuleNotFoundError` on import
- Missing `pyjwt` package → `ImportError` on `import jwt`
- Read-only filesystem for pip → `Permission denied` on install attempts
- These mirror G3 run 1's actual friction (Flask/werkzeug import failures)

**Approach B: Hermes harness with output_buffer dump (full integration)**

Modify the overlay to persist `session.output_buffer` at session end:

```python
# In process_registry.py, at session completion:
def _dump_raw_ndjson(session):
    """Persist raw NDJSON stream for offline friction analysis."""
    if session.output_buffer:
        out_path = f"/root/output/raw.ndjson"
        with open(out_path, "w") as f:
            f.write(session.output_buffer)
```

Then re-run the existing `run.sh` harness. The raw NDJSON will be preserved
alongside state.db in the output directory.

**Step-by-step (Approach A):**

| Step | Action | Success criterion |
|------|--------|-------------------|
| 1 | Build friction container (python:3.11-slim + workspace, no flask/pyjwt) | Container starts, `import flask` fails |
| 2 | Install qodercli 1.1.2 in container | `qodercli --version` prints 1.1.2 |
| 3 | Run qodercli with `--output-format stream-json` piped to `raw_friction.ndjson` | File created, >10 NDJSON lines |
| 4 | Feed `raw_friction.ndjson` through `_format_ndjson_progress()` | Returns string with `⚠ Friction:` |
| 5 | Compute friction_index from the stream | friction_index ≥ 0.40 |
| 6 | Compute separation from clean baseline | friction_index - 0.086 ≥ 0.25 |

**Acceptance criteria:**
- friction_index(friction_run) ≥ 0.40
- friction_index(friction_run) - friction_index(clean_run) ≥ 0.25
- At least 2 of 3 signals fire (error_rate, ctx_velocity, retry_density)
- Raw NDJSON file preserved for Phase 2 re-analysis

**Risk: friction may not reproduce.** If qodercli installs flask/pyjwt itself
(it has `--permission-mode bypass_permissions`), the session may be clean.
Mitigation: use a read-only filesystem or remove pip entirely to make
installation impossible. The friction must be *environmental*, not solvable
by the agent.

**Fallback: synthetic friction with real NDJSON structure.** If no real
friction session can be captured, construct a realistic NDJSON stream from
G3 run 1's outer conversation (tool calls, exit codes, timing are visible in
state.db). This is a proxy, not a true capture — document as limitation.

#### Friction-inducing environment configurations

Three container configurations designed to produce *unsolvable* environmental
friction. The agent cannot escape these — friction is guaranteed by removing
the tools needed to fix the problem.

**Signal budget (modeled vs clean baseline):**

| Config | error_rate | ctx_velocity_norm | retry_density | friction_index | Δ from clean |
|--------|-----------|-------------------|---------------|----------------|--------------|
| Clean baseline (P7) | 0.00 | 0.03 | 0.22 | 0.086 | — |
| F1: No pip + missing deps | 0.75 | 0.80 | 0.50 | 0.683 | +0.597 |
| F2: Read-only FS + broken import | 0.60 | 0.50 | 0.45 | 0.517 | +0.431 |
| F3: Network isolation + no pip | 0.85 | 0.90 | 0.65 | 0.800 | +0.714 |

All three exceed the 0.40 threshold and the 0.25 separation gate.

**F1: No pip + missing dependencies (recommended first attempt)**

```dockerfile
FROM python:3.11-slim

# Remove pip entirely — agent cannot install anything
RUN rm -f /usr/local/bin/pip /usr/local/bin/pip3 \
    && rm -rf /usr/local/lib/python3.11/ensurepip

# Remove flask and pyjwt if present
RUN python3 -c "import flask" 2>/dev/null && pip uninstall -y flask || true
RUN python3 -c "import jwt" 2>/dev/null && pip uninstall -y pyjwt || true

# Workspace with a task that requires flask + pyjwt
WORKDIR /workspace
COPY src/ /workspace/src/
COPY tests/ /workspace/tests/
COPY requirements.txt /workspace/

# Anti-escape: remove apt/dpkg so system packages can't be installed
RUN rm -f /usr/bin/apt-get /usr/bin/apt /usr/bin/dpkg

# Anti-escape: remove curl/wget so pip can't be re-downloaded
RUN rm -f /usr/bin/curl /usr/bin/wget

RUN git init /workspace && cd /workspace && git add -A && git commit -m "baseline"
```

Expected failure cascade:
1. Agent reads task → attempts `import flask` → `ModuleNotFoundError`
2. Agent tries `pip install flask` → `command not found`
3. Agent tries `python -m pip install flask` → `No module named pip`
4. Agent tries `python -m ensurepip` → removed
5. Agent retries variations (pip3, apt-get) → all fail
6. Each retry is a distinct tool call with non-zero exit → error_rate climbs
7. Context fills with error output → ctx_velocity climbs
8. Repeated Bash calls with similar commands → retry_density climbs

**F3: Network isolation + missing system lib (fallback if F1 insufficient)**

```dockerfile
FROM python:3.11-slim

# Remove pip
RUN rm -f /usr/local/bin/pip /usr/local/bin/pip3 \
    && rm -rf /usr/local/lib/python3.11/ensurepip

# Remove flask/pyjwt from site-packages
RUN rm -rf /usr/local/lib/python3.11/site-packages/flask* \
    && rm -rf /usr/local/lib/python3.11/site-packages/jwt*

# Replace pip with error script (in case agent finds alternate path)
RUN printf '#!/bin/sh\necho "pip: command not found"\nexit 127\n' > /usr/local/bin/pip \
    && chmod +x /usr/local/bin/pip

# Remove package managers and download tools
RUN rm -f /usr/bin/apt-get /usr/bin/apt /usr/bin/dpkg \
    && rm -f /usr/bin/curl /usr/bin/wget

WORKDIR /workspace
COPY src/ /workspace/src/
COPY tests/ /workspace/tests/
RUN git init /workspace && cd /workspace && git add -A && git commit -m "baseline"
```

Run with: `docker run --network=none ...`

Network isolation ensures even creative workarounds (downloading get-pip.py,
using python's urllib) cannot succeed. This is the highest-reliability config.

**Anti-escape measures (applied to all configs):**
- Remove `pip`, `pip3`, `ensurepip` — no package installation
- Remove `apt-get`, `dpkg` — no system packages
- Remove `curl`, `wget` — no downloading
- F3 adds `--network=none` — no network access at all
- Task requires flask+pyjwt — cannot be implemented without them
- Tests import flask — cannot pass without the package

**Recommendation:** Start with F1. If the agent gives up early (< 10 tool
calls, friction_index < 0.40), escalate to F3. F2 is omitted from initial
testing because read-only FS may cause the agent to abandon the task entirely
rather than retry, producing low event counts.

### Phase 2: Prospective validation (requires Hermes runtime)

Run 6+ sessions through the existing harness with friction index logging enabled.
Compute agreement between runtime friction label and post-hoc CPI label.

**Gate:** ≥80% agreement (H8 threshold). Sessions where they disagree are
analyzed individually — disagreement is interesting, not just failure.

### Phase 3: Integration (post-merge, if H8 confirmed)

Wire the friction index into `_format_ndjson_progress()` in the hermes-agent fork.
No PR to upstream until Phase 2 validates.

---

## §5 EXIT EVIDENCE CRITERIA

Plan 8 is **COMPLETE** when ALL of the following hold:

| # | Criterion | Evidence artifact | Minimum |
|---|-----------|-------------------|---------|
| E1 | Retrospective separation | friction_index(run1) - friction_index(run2) | ≥0.25 |
| E2 | Prospective agreement | agreement(runtime_label, CPI_label) over N≥6 sessions | ≥80% |
| E3 | Clean-case overhead | chars added to poll output when friction_index < 0.15 | 0 |
| E4 | Friction-case informativeness | chars added when friction_index ≥ 0.40 | ≤100 |
| E5 | Disagreement analysis | Written explanation for every session where runtime ≠ post-hoc | 100% coverage |
| E6 | Falsification reported | If H8 REJECTED, document which signal failed and why | Mandatory |

**Plan 8 is ABANDONED (not failed) if:** E1 < 0.25 on retrospective data.
This means the NDJSON stream doesn't contain enough signal to discriminate
regimes, and the bimodal CPI finding remains a post-hoc-only observation.
Abandonment is a valid outcome — document it in §8 and close.

---

## §6 THREE-LENS REVIEW

### 6.1 Adversarial Review

| # | Finding | Severity | Response |
|---|---------|----------|----------|
| A1 | **Circular validation.** The friction index is designed from the same two sessions (run 1, run 2) that motivate it. Retrospective "validation" on the design data is overfitting. | HIGH | Phase 1 is explicitly labeled as sanity-check, not validation. Phase 2 (prospective, N≥6) is the real test. The 80% threshold is pre-registered before Phase 2 data exists. |
| A2 | **Error pattern list is fragile.** Hardcoded strings ("Traceback", "Error:") will miss novel error formats and false-positive on benign output containing those strings. | MEDIUM | Accept for v0.1. Phase 2 disagreement analysis (E5) will surface false positives/negatives. If error_rate is the weak signal, drop S1 and rely on S2+S3. **Phase 0 note:** `tool_result` blocks have no `is_error` field; errors detected via `tool_use_result.exitCode` (Bash) or content text. exitCode is reliable; text matching is fallback only. |
| A3 | ~~**context_usage_ratio may not be in the stream.**~~ | ~~HIGH~~ | **RESOLVED (Phase 0).** K2a confirmed empirically. `context_usage_ratio` present at `message.usage.context_usage_ratio` on every complete assistant event (P7-2: 4/4 complete events, P7-3: 5/5). Field is absent only on streaming partials (stop_reason=null). Full S1-S4 plan proceeds. |
| A4 | **50-event window is too short for velocity.** If sessions are >50 events, the window sees only recent history. A session that was friction-heavy early but recovered looks clean. | MEDIUM | Acceptable. The poll output is a *current state* indicator, not a session summary. Hermes sees the friction warning in real-time; if it clears, the session recovered. That's correct behavior. |
| A5 | **No ground truth for "friction" independent of CPI.** The plan validates against CPI labels, but CPI is itself a proxy. A session could have CPI<1.0 for reasons unrelated to environment friction (e.g., genuinely complex task). | MEDIUM | Acknowledged. E5 (disagreement analysis) exists precisely for this. If friction_index says "clean" but CPI says "friction", the session is complex-but-clean — a third regime the binary model misses. Document as limitation. |
| A6 | **G3 run 1 inner NDJSON not preserved.** The state.db stores Hermes's outer conversation. The inner qodercli NDJSON stream was consumed real-time by `_format_ndjson_progress()` and only 1000-char truncated poll fragments survive. Phase 1 retrospective scoring cannot reconstruct the full friction index from existing captures. | HIGH | **New (Phase 0).** Two paths: (a) re-run G3 run 1 task with raw NDJSON capture enabled (requires Hermes runtime), or (b) reconstruct signals from the outer Hermes conversation (tool calls, exit codes, retry counts are visible). Path (b) is a proxy, not the actual inner stream. Phase 1 gate (E1) may need to be evaluated on prospective data only. |
| A7 | **Retry density false positive on naive matching.** Using tool NAME only (not signature), P7-3 (clean) scores retry_density=0.75 → friction_index=0.26 (false positive). With proper `tool:key_input[:80]` signatures, P7-3 correctly scores 0.093. | MEDIUM | **New (Phase 0).** Signature MUST include key input, not just tool name. The sketch in §3.4 already uses `tool_call_signatures` correctly. Implementation must not regress to name-only matching. |

**Gate status (v0.2):** A3 RESOLVED. A1 addressed by design. A6 is the new HIGH — Phase 1 retrospective on G3 run 1 is blocked unless inner NDJSON is re-captured or reconstructed. A7 is a implementation guardrail, not a design flaw.

### 6.2 Karpathy Assumption Audit

| # | Hidden assumption | Reality check | Invalidation criterion | Status |
|---|-------------------|---------------|----------------------|--------|
| K1 | NDJSON `user` events contain `tool_result` blocks with readable error text | **CONFIRMED (Phase 0).** P7-2 raw.ndjson: 3/3 user events contain `tool_result` blocks with `content` field. No `is_error` field present; error detection via `tool_use_result.exitCode` (Bash: exitCode=0 for success) or content text matching. G3 run 1 outer conversation shows error content preserved (e.g., "ModuleNotFoundError: No module named 'jwt'"). | — | **VERIFIED** |
| K2 | `context_usage_ratio` is emitted in assistant events | **CONFIRMED (Phase 0).** K2a obtains. Field at `message.usage.context_usage_ratio`. P7-2: 4/4 complete assistant events (stop_reason≠null). P7-3: 5/5. G3 run 1 poll fragment: ratio=0.0978 at message 41, 0.1293 at message 47. Absent only on streaming partials (stop_reason=null). | — | **VERIFIED (K2a)** |
| K3 | Error patterns are distinguishable from benign output by string matching | Flask tracebacks are obvious. But "Error:" appears in benign contexts (e.g., grep for "Error" in source code). **Phase 0 refinement:** `tool_use_result.exitCode` provides a reliable binary signal for Bash tools (no string matching needed). Text matching is fallback for non-Bash tools only. | If false positive rate > 30% on clean sessions | PARTIALLY VERIFIED — exitCode reliable, text matching untested on friction sessions |
| K4 | Retry = same tool + same input repeated 3+ times | **CONFIRMED WITH NUANCE (Phase 0).** G3 run 1 outer Hermes conversation shows 3 qodercli launches with VARIED inputs: (1) `-i` piped → stdin error, (2) `-i` background → exit 1, (3) `-p` print → success. Signature-based detection (`tool:key_input[:80]`) correctly treats these as DISTINCT calls (retry_density=0 for the launch sequence). True retries would be identical command re-execution (e.g., same pip install 3x). P7-3 clean session: 4 unique signatures, retry_density=0.25 (max 1 repeat / 4 calls). | — | **VERIFIED** — varied inputs are NOT retries; signature approach is correct |
| K5 | 50-event window captures enough signal | G3 run 1 is 92 messages (outer). Inner qodercli session length unknown from existing data (inner NDJSON not preserved — see A6). P7 sessions: 17-20 events total (well within window). | If friction_index computed on last-50 of run 1 < 0.25 | UNVERIFIABLE from existing data (A6 blocks retrospective). Deferred to Phase 2 prospective. |
| K6 | Clean sessions stay clean | A session can start clean, hit friction at event 60, and the 50-window catches it. But a session that hits friction at event 10 and recovers by event 40 looks clean at event 90. | If Hermes needs *historical* friction, not just current | Accept by design — poll is current-state. Mitigation: add cumulative error_count to session object so Hermes can query lifetime friction even after window clears. |

**K2 decomposition (RESOLVED):**

| Sub-case | Condition | Consequence | Pre-committed action | Outcome |
|----------|-----------|-------------|---------------------|---------|
| K2a | `usage` object present, `context_usage_ratio` field present, emitted every complete assistant event | Full plan proceeds (S1-S4) | — | **OBTAINS.** Verified on P7-2 (4/4), P7-3 (5/5), G3 run 1 poll fragments. |
| K2b | `usage` present but field named differently or emitted sparsely (e.g., every Nth event) | S2 velocity computation unreliable on sparse data; S4 may survive | Adapt: use field if present under any name; drop S2 if sparse, keep S4. Friction index = (S1 + S3 + S4) / 3. H8 threshold unchanged (80%). | Not applicable. |
| K2c | `usage` object absent entirely | S2 and S4 dead. Only S1 (error rate) + S3 (retry density) survive. | **H8 threshold drops to 70%.** | Not applicable. |

**Phase 0 verification results (completed 2026-07-21):**

| Task | Method | Result |
|------|--------|--------|
| K1: tool_result presence | Parsed P7-ndjson-treatment-2/raw.ndjson user events | 3/3 user events have `tool_result` with `content`. No `is_error` field; `tool_use_result.exitCode` available for Bash. |
| K2: context_usage_ratio | Parsed P7-2, P7-3 raw.ndjson assistant events + G3 run 1 state.db poll fragments | Present on every complete assistant event. Values: P7-2 [0.1123→0.1137], P7-3 [0.1122→0.1145], G3-run1 [0.0978→0.1293]. |
| K4: retry input patterns | Extracted G3 run 1 outer Hermes tool_calls (40 assistant messages) | 3 qodercli launches with varied flags (`-i` piped, `-i` bg, `-p` print). NOT retries by signature definition. True retries = identical command re-execution. |
| Clean calibration | Computed friction_index on P7-3 (known clean) | friction_index=0.093 with proper signatures. Naive name-only matching gives 0.26 (false positive) — signature must include key_input. |
| **A6 discovery** | Attempted to extract inner NDJSON from G3 run 1 state.db | Inner stream NOT preserved. state.db stores Hermes outer conversation only. Poll output truncated to 1000 chars. Phase 1 retrospective on run 1 blocked. |

### 6.3 RCF Forecast (Reference Class Forecasting)

**Reference class:** Plans 3-7 in this repo (implementation plans with empirical validation).

| Plan | Estimated effort | Actual effort | Ratio |
|------|-----------------|---------------|-------|
| Plan 7 (NDJSON integration) | "purely transport bridging" | 7 versions, 3 evidence gaps, H6 reclassification | ~5x |
| Plan 2 Phase 6 (CPI re-measurement) | "~30 min, no new code" | Multi-day, 3 runs, bimodal surprise, reclassification | ~4x |
| Plan 5 (structural metrics) | 2 phases | 3 phases + false_success detector | ~1.5x |

**Mean overrun:** ~3.5x on plans involving empirical validation.

**Plan 8 estimate (naive, revised v0.2):** Phase 1a (clean sanity) = done (0h remaining). Phase 1b (friction capture) = 2 hours (re-run task + parse NDJSON). Phase 2 (prospective) = 2 hours. Phase 3 (integration) = 1 hour. Total = 5 hours.

**RCF-adjusted:** 5h × 3.5 = **17.5 hours** realistic. Buffer for:
- A6 re-capture failure (task succeeds cleanly on re-run, no friction) → need different friction-inducing task (adds 2-3h)
- Phase 2 disagreement analysis revealing a third regime (adds 2-3h)
- Error pattern tuning (adds 1-2h)
- Hermes runtime unavailability (calendar delay, not effort)

**Effort gate:** If Phase 1b friction separation (E1) is <0.25, ABANDON
immediately. Do not proceed to Phase 2 on hope. Sunk cost is ~2 hours.

**A6 risk:** The re-captured friction session may not reproduce friction (the
original G3 run 1 friction was caused by Hermes not knowing qodercli flags —
a one-time learning curve, not an environment issue). If the re-run is clean,
Phase 1b needs a deliberately friction-inducing environment (missing deps,
broken imports). This is a design risk for the capture harness, not a Plan 8
design flaw.

---

## §7 EXECUTION ORDER

| Phase | Task | Depends on | Gate |
|-------|------|-----------|------|
| 0 | ~~**Verify K2:** Check if `context_usage_ratio` exists in NDJSON stream~~ | — | **DONE.** K2a confirmed. K1, K4 also verified. A6 discovered. |
| 1a | **Clean-session sanity check:** Compute friction_index on P7-2, P7-3 (raw.ndjson available). Confirm all score <0.15. | Phase 0 | All clean sessions <0.15. If any ≥0.15 → signature definition is wrong, fix before proceeding. |
| 1b | **Friction-session capture:** Re-run G3 run 1 task (Flask/JWT) with raw NDJSON capture enabled. Compute friction_index on the preserved stream. | Hermes runtime | E1: friction_index(friction_run) - friction_index(clean_run) ≥ 0.25. If <0.25 → ABANDON. |
| 2 | **Prospective validation:** Run N≥6 sessions with friction logging, compute agreement | Phase 1b pass | E2: agreement ≥80%. If <80% → analyze disagreements, revise signals or REJECT H8. |
| 3 | **Integration:** Wire into `_format_ndjson_progress()`, verify E3/E4 overhead constraints | Phase 2 pass | E3+E4 pass. Deploy to fork. |

**Temporal constraints (updated v0.2):**
- Phase 0: COMPLETE.
- Phase 1a: Can proceed immediately (P7 raw.ndjson on disk).
- Phase 1b: Requires Hermes runtime + raw NDJSON capture harness (same dependency as Plan 1 G1). The original plan to retrospectively score G3 run 1 is BLOCKED by A6 (inner NDJSON not preserved). Must re-capture.
- Phase 2: Requires Hermes runtime + 6+ labeled sessions.

---

## §8 ABANDONMENT PROTOCOL

If Plan 8 is abandoned (E1 fails or H8 rejected):

1. Record the friction_index values that failed to discriminate
2. Record which signal(s) were uninformative
3. Update Plan 2 Phase 6 with: "Runtime friction detection investigated and
   abandoned — NDJSON stream signals insufficient to discriminate regimes at
   runtime. Bimodal CPI remains a post-hoc-only finding."
4. Close this plan with status **ABANDONED** and link the evidence
5. Do NOT delete this file — the negative result is evidence

---

## §9 RELATIONSHIP TO OTHER PLANS

| Plan | Relationship |
|------|-------------|
| Plan 7 (CLOSED) | Provides the NDJSON substrate. Plan 8 extends `_format_ndjson_progress()` but does NOT reopen Plan 7. |
| Plan 2 Phase 6 | Provides the motivation (bimodal CPI). Plan 8's friction index is a new measurement instrument for the same phenomenon. |
| Plan 1 G7 (proposed) | Tracks Plan 8 in the evidence gap table. LOW priority, post-merge. |
| Plan 1 G3 | G3 run 3 provides the third labeled session needed for Phase 0. |

---

## §10 CHANGELOG

| Version | Date | Change |
|---------|------|--------|
| 0.2.2 | 2026-07-21 | Phase 1b friction environments: added F1 (no pip + missing deps, fi=0.683), F2 (read-only FS, fi=0.517), F3 (network isolation, fi=0.800) with Dockerfiles, signal budget table, anti-escape measures, expected failure cascade, and escalation recommendation (F1→F3). |
| 0.2.1 | 2026-07-21 | Consistency fixes + implementation: (1) BUG FIX — `tool_use_result` accessed from top-level user event, not inside tool_result block. (2) Implementation aligned with §3.2 composite formula (was using per-signal thresholds). (3) Signature extraction broadened to cover Agent/WebFetch/generic tools. (4) §3.2 documents 0.02 normalization constant and S4 display-only role. (5) Implementation deployed to `data/ndjson_overlay/process_registry.py`. (6) Phase 1a validated: P7-2/P7-3 score 0.086 (clean), synthetic friction scores 0.833 (HIGH). E3/E4 constraints verified. |
| 0.2 | 2026-07-21 | Phase 0 COMPLETE. K2a confirmed (context_usage_ratio on every complete assistant event). K1 verified (tool_result present, exitCode for Bash). K4 verified (varied inputs ≠ retries, signature approach correct). A3 resolved. New findings: A6 (G3 run 1 inner NDJSON not preserved — Phase 1 retrospective blocked), A7 (naive name-only retry matching causes false positives). Clean calibration: P7-3=0.093. Execution order updated: Phase 1 split into 1a (clean sanity, immediate) + 1b (friction capture, requires Hermes runtime). |
| 0.1 | 2026-07-21 | Initial draft. 3-lens review complete. K2 blocking. |
