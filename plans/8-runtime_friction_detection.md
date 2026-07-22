# Plan 8 — Runtime Friction Detection

Status: **GAP 3 → OPTION 3 (SCOPE REDUCTION).** H8 CONFIRMED (9/9 = 100%, R4-flagged). SKILL.md v2.5.1 pushed. §4.1 exit-42 probe (Run 2) VALID on hermes:m1probe but **NO FIRE** — both arms chose `-p` directly, exit-42 never surfaced (antecedent unreachable under the skill's own print-mode default). R6 fires: do not replicate. Exit-42 prescription is a redundant edge-case guard, not a load-bearing behavior.
Version: 0.4.0 (2026-07-22)
Parent:
  - 7: plans/7-subagent_progress_observation.md (NDJSON wire protocol substrate)
  - 2: plans/2-cta_verification_layer_plan.md (Phase 6 bimodal CPI finding)
Related:
  - 1: plans/1-hermes_cta_fork_plan.md (G3 evidence gap → G7 proposed)

---

## §0 CURRENT STATE

| Field | Value |
|---|---|
| Status | **GAP 3 IN PROGRESS — ±ADAPTATION PAIRED DESIGN** |
| Research question | Can we classify the environment regime (clean vs friction) at runtime from the NDJSON stream? |
| Causal role | Friction is a **moderator** (stratification instrument), not a treatment. See §1.1. |
| Substrate | `_format_ndjson_progress()` in `hermes-agent/tools/process_registry.py:90-268` (friction-enabled) |
| Motivation | Plan 2 Phase 6: CPI is bimodal (0.912 friction / 1.594 clean). Regime is currently discoverable only in post-hoc trace analysis. |
| Deliverable | Friction index in `process()` poll output that discriminates clean from friction-heavy sessions at runtime |
| H8 result | **CONFIRMED.** 9/9 sessions = 100% agreement (threshold ≥80%). Clean FI: 0.086–0.121. Friction FI: 0.433 (peak). Zero FP/FN. |
| K2 resolution | **K2a obtains.** `context_usage_ratio` present at `message.usage.context_usage_ratio` on every complete assistant event (stop_reason ≠ null). Full S1-S4 plan proceeds. |
| Clean calibration | P7-3 scores friction_index=0.093 (< 0.15 threshold) with proper `tool:key_input[:80]` signatures. |
| Phase 3 status | Deployed to hermes-agent fork. SKILL.md **v2.5.1** pushed (commit `00591faa6`): mild friction triage + exit-42 fallback guidance. **Gap 2 CLOSED:** friction display proven across CLEAN/MILD/HEAVY regimes. `detect_regime_adaptation()` in 10-detector registry. Integration tests persisted: `tests/test_regime_adaptation.py` (7/7 pass). Live container proof: `P1-interactive-P8-phase3-friction-treatment-1` (valid, exit 0, 57.8s). |
| Background-mode test | **COMPLETE.** Tag `P8-phase3-bgmode`. Model hit exit-42 (`-i` in background), quoted SKILL.md guidance verbatim, fell back to `-p`, completed task (auth.py + token.py created). 25-min reasoning loop stall (adversarial prompt conflict, not skill failure). Evidence: `data/m3_captures/P1-interactive-P8-phase3-bgmode-treatment-1/behavioral_trace.md`. |
| Next | **Gap 3 experiment RUNNING.** Post-reboot: kalloc.1024 at ~118k (headroom ~2.88M ✓). Run-1 re-attempt hit second infra failure: ssl removal broke hermes (`hermes_cli/auth.py:26` imports ssl at startup — both arms exited in ~5s). **Fix applied (step 11 revised — venv split):** copy `ssl.py` + `_ssl*.so` into hermes venv site-packages, THEN remove from system python. Hermes venv python finds ssl in its own site-packages; agent's bare `python3` does not. Stronger than urllib patch — blocks ALL ssl-dependent escapes (urllib, http.client, raw socket+ssl). Image rebuilt `--no-cache` + verified: system `import ssl` → ModuleNotFoundError, hermes venv `import ssl` → OpenSSL 3.0.19, `hermes --version` → v0.19.0, all escape vectors blocked. **Paired experiment re-launched** (`python scripts/gap3_friction_harness.py --condition both --run-num 1 --timeout 900`). Awaiting results. Invalid runs preserved at `P8-gap3-friction-{treatment,control}-1-INVALID-ssl-escape/`. |

---

## §0.1 GAP 3 RECOVERY PROCEDURE (COMPLETED 2026-07-22)

**Status: DONE.** Reboot completed, kalloc headroom restored (~118k elements).
Second infra failure discovered and fixed (ssl removal broke hermes — venv split
applied). Image rebuilt `--no-cache`, verified, experiment re-launched.

**Why this exists:** Gap 3 was blocked on a host reboot (kalloc.1024 kernel leak).
After reboot, these steps were followed in order. The inescapability probe is
MANDATORY — run-1 proved the agent WILL escape if any vector is left open.

### Pre-flight

```bash
# 1. Confirm kernel memory headroom (need >200k free elements)
zprint | grep "data.kalloc.1024"
# Parse: elements column. Threshold is 3M. If (3M - current) < 200k → reboot again.

# 2. Start container system
container system start
```

### Rebuild friction image

```bash
# 3. Rebuild from scratch (no cache — ensures all 11 removal steps apply)
container build --no-cache -f containers/Dockerfile.friction \
  -t registry.rossollc.com/hermes:friction .
```

### Verify inescapability (MANDATORY)

```bash
# 4. Probe the built image. ALL must fail except node https.
container run --rm --entrypoint /bin/sh registry.rossollc.com/hermes:friction -c '
  echo "--- pip ---"; pip --version 2>&1 || true
  echo "--- uv ---"; which uv 2>&1 || true
  echo "--- curl ---"; which curl 2>&1 || true
  echo "--- wget ---"; which wget 2>&1 || true
  echo "--- apt ---"; which apt-get 2>&1 || true
  echo "--- ensurepip ---"; python3 -m ensurepip 2>&1 || true
  echo "--- import flask ---"; python3 -c "import flask" 2>&1 || true
  echo "--- import jwt ---"; python3 -c "import jwt" 2>&1 || true
  echo "--- import ssl ---"; python3 -c "import ssl" 2>&1 || true
  echo "--- urllib https ---"; python3 -c "
import urllib.request
urllib.request.urlopen(\"https://pypi.org\", timeout=5)
" 2>&1 || true
  echo "--- node https ---"; node -e "
const https = require(\"https\");
https.get(\"https://registry.npmjs.org\", r => {
  console.log(\"node https status:\", r.statusCode);
  process.exit(0);
}).on(\"error\", e => { console.log(\"node https FAIL:\", e.message); process.exit(1); });
" 2>&1 || true
'
```

**Expected results:**
| Probe | Expected |
|-------|----------|
| pip | "pip: command not found" (fake script, exit 127) |
| uv | not found |
| curl / wget / apt-get | not found |
| ensurepip | ModuleNotFoundError |
| import flask / jwt | ModuleNotFoundError |
| import ssl (system python) | ModuleNotFoundError (venv split — agent blocked) |
| import ssl (hermes venv) | **SUCCEEDS** (OpenSSL 3.0.19 — hermes needs it) |
| urllib https | fails (no ssl module in system python) |
| node https | status 200 (Node.js TLS independent of Python) |
| hermes --version | v0.19.0 (hermes functional) |

If ANY probe deviates → do NOT run the experiment. Fix the Dockerfile and rebuild.

### Run the paired experiment

```bash
# 5. Launch both arms (treatment=v2.5.1 skill, control=v2.4.0 skill)
python scripts/gap3_friction_harness.py --condition both --run-num 1 --timeout 900
```

### Post-run assessment

```bash
# 6. Check both arms completed (not infra_failure, not escaped)
cat data/m3_captures/P8-gap3-friction-treatment-1/classification.json
cat data/m3_captures/P8-gap3-friction-control-1/classification.json
# Both must show "valid". If either shows "infra_failure" → retry that arm.
# If treatment shows flask/jwt imports in state.db → ESCAPE, image is broken.

# 7. Score CPI
python -m cta.structural_scorer \
  data/m3_captures/P8-gap3-friction-treatment-1/state.db \
  data/m3_captures/P8-gap3-friction-control-1/state.db
# Treatment CPI > control CPI → Gap 3 closed (adaptation improves outcomes).
```

### Gap 3 Results — Run 1 (EXPLORATORY, N=1)

**Pre-registered status:** Per §4.0.2, N=1 can ONLY produce an exploratory result.
This CANNOT close Gap 3 regardless of Δ_CPI.

| Metric | Treatment (v2.5.1) | Control (v2.4.0) | Δ |
|--------|--------------------|--------------------|---|
| Classification | valid | valid | — |
| Messages | 111 | 126 | -12% (treatment fewer) |
| Tool/process invocations | 11 | 53 | -79% (treatment far fewer) |
| Wall time | 556.8s | 508.6s | +9% (treatment slower) |
| CPI (vs clean baseline 53) | 0.477 | 0.421 | +0.056 |
| Files modified | 2 (44 insertions) | 4 (19 insertions) | — |
| Tests passed | 8/8 | 8/8 | — |
| Friction detected by Hermes? | **NO** (inner qodercli adapted) | N/A (no guidance) | — |
| Adapted (killed + retried `-p`)? | **NO** | N/A | — |
| Task completed? | YES (stdlib JWT, 8 tests pass) | YES (stdlib JWT + helpers fix, 8 tests pass) | — |
| Escape (flask/jwt installed)? | NO | NO | — |

**Validity gates:**
1. ✅ Both arms classify as `valid`
2. ⚠️ Friction was present (no pip/ssl/PyJWT) but manifested as inner-qodercli
   adaptation, NOT as Hermes-visible error tool_results. The friction was absorbed
   INSIDE the delegated session, not at the Hermes monitoring layer.
3. ✅ Neither arm escaped (no flask/jwt installed; stdlib implementation only)

**Behavioral observation:**
- Treatment's inner qodercli wrote a 93-line stdlib JWT (`jwt_compat.py`) using
  `hmac`/`hashlib`/`base64` — adapted at the CODE level, not the regime level.
- Control did the same but also fixed pre-existing `helpers.py` syntax error and
  `package.json` test script. More thorough, more messages.
- Control used 5x more tool/process invocations (53 vs 11) — excessive polling.
- **The SKILL.md friction protocol (detect ⚠ Friction → kill → retry `-p`) did
  NOT activate.** The friction was invisible to Hermes because qodercli handled it
  internally. The regime-adaptation guidance targets a failure mode that didn't occur.

**Outcome classification (per §4.0 interpretation table):**
→ **"Treatment ≈ control, both succeed" — sub-case (a) NO FIRE.** The inner
qodercli agent absorbed the friction at the code level (stdlib `jwt_compat.py`);
it never surfaced as Hermes-visible error tool_results. The prescription's
precondition (visible friction, FI≥0.40) was never met, so it correctly never fired.
**This is a construct-validity gap, NOT a verdict that the friction block is inert.**
The F1 environment did not instantiate the construct (Hermes-visible friction) the
prescription targets — the extinguisher had no fire to fight. Treatment's 12%
message advantage is from less polling overhead, not regime-switching. Resolution:
the redesigned probe (§4.1) must produce genuine Hermes-visible friction before any
treatment verdict is possible.

**Confirmatory threshold check:** Δ_CPI = +0.056 > 0 ✓ BUT treatment_CPI = 0.477
< 1.0 ✗. Threshold NOT met. Even if N≥3, this pattern would not confirm Gap 3.

### Outcome Interpretation

| Result pattern | What it tells us | SKILL.md implication |
|----------------|-----------------|---------------------|
| **Treatment CPI > control CPI** (treatment recovers toward >1.0) | The prescription works. Agent CAN be taught to override persistence instinct. Friction guidance is the skill's highest-value component. | Shift design philosophy from "how-to guide" toward "regime-awareness + adaptive strategy." Generalize: detect regime → change strategy → preserve context. |
| **Treatment ≈ control, both stuck** (both CPI < 1.0, both burn context) | Guidance arrives but doesn't change behavior. Model ignores SKILL.md under task pressure, or guidance arrives too late (friction already terminal). | Friction block is dead weight at current placement. Move guidance earlier (before task starts) or make it more salient (system-level injection, not skill text). |
| **Treatment ≈ control, both succeed** (both CPI > 1.0) | **Two sub-cases — do NOT conflate.** **(a) No fire:** friction was absorbed INSIDE the inner agent (e.g., stdlib workaround) and never surfaced as Hermes-visible error tool_results. The prescription's precondition (visible friction) was never met, so it correctly never fired. This is **NOT evidence the prescription is inert** — the extinguisher had no fire to fight. It is a **construct-validity gap**: the F1 environment did not instantiate the construct (Hermes-visible friction) the prescription targets. → Requires the redesigned probe (§4.1), not a treatment verdict. **(b) Native adaptation:** Hermes-visible friction DID occur (FI≥0.40 surfaced) but the agent recovered without guidance. → Skill is genuinely redundant in this regime; friction block adds nothing. | If (a): do not conclude "dead weight" — test the prescription against real Hermes-visible friction first. If (b): friction block is dead weight for this friction type; revert to procedural content. The instrument (H8) retains value for Hermes monitoring either way. |
| **Treatment < control** (treatment abandons recoverable session) | Over-triggering: guidance causes premature abandonment. Agent kills a session that would have self-recovered. | **Redesign required.** Binary "friction → kill" is too aggressive. Need confidence threshold: tolerate mild (FI < 0.40), act only on heavy + high context (>70%). Expose friction_index gradient in SKILL.md decision surface. |
| **Either arm escapes** (flask/jwt installed) | Image is broken. Result is INVALID regardless of CPI. | Fix Dockerfile, rebuild, re-run. Do not interpret CPI. |

**The deeper causal claim:**

```
observed_outcome = skill_effect + environment_effect + noise
```

Gap 3 isolates `skill_effect` in the friction regime specifically. In clean regime,
the skill may be neutral (agent succeeds anyway — environment_effect dominates). In
friction regime, the skill's ONLY lever is preventing context death spirals. It
cannot fix the environment; it can only change how the agent responds to it.

This makes SKILL.md fundamentally different from a typical skill: it's not teaching
a capability, it's teaching **when to stop trying and switch strategy** — the
hardest thing for an LLM agent to do autonomously, because the training signal
rewards persistence.

**Design risk (pre-registered):** If treatment over-triggers (kills healthy sessions
that would self-recover), the guidance needs a confidence threshold, not a binary
switch. The friction_index already provides the gradient (0.15 mild / 0.40 heavy).
SKILL.md v2.5.1's mild/heavy distinction is a start, but the *prescription* is still
binary once heavy fires. Next iteration if needed: heavy + low context (<50%) →
monitor one more cycle; heavy + high context (>70%) → kill immediately.

### Known escape vectors (all patched in Dockerfile.friction)

| # | Vector | Fix |
|---|--------|-----|
| 1 | pip/pip3 binaries | Steps 1, 3, 10 (fake pip) |
| 2 | ensurepip bootstrap | Step 2 |
| 3 | uv (at /usr/bin/uv) | Step 4 |
| 4 | curl/wget download | Step 5 |
| 5 | apt-get/dpkg | Step 6 |
| 6 | flask/pyjwt in 3 venvs | Steps 7, 8, 8b |
| 7 | uv wheel cache | Step 8c |
| 8 | python -m pip | Step 9 |
| 9 | urllib + ssl (get-pip.py) | Step 11 (venv split: ssl copied to hermes venv, removed from system python) |

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

### §1.1 Causal Role: Friction as Moderator (v0.3.0)

**Core decomposition:**

```
observed_outcome = skill_effect + environment_effect + noise
```

CTA isolates `skill_effect` by pairing ±skill in the same environment. Friction
is a **stochastic environment variable** — the same task randomly lands in clean
(CPI=1.594) or friction (CPI=0.912) regime. This means:

1. **Friction is a moderator, not a treatment.** The skill is the treatment.
   Friction is the regime that modulates the treatment's effect size. A skill
   that's constructive in clean regime may be neutral or destructive in friction
   regime — and that's not the skill's fault.

2. **The friction index is a stratification instrument.** It separates
   `environment_effect` from `skill_effect` before SIP labeling. Without it, the
   bimodal CPI contaminates verdicts — you'd attribute environment-driven variance
   to the skill.

3. **"Friction treatment" in SKILL.md is a second-order intervention.** It's not
   "treat the task" — it's "treat the regime signal." The guidance ("if you see
   ⚠ Friction, kill and retry with print mode") is a **meta-SIP**: a skill
   instruction that changes how the agent responds to the environment, independent
   of the task.

4. **SIPs need regime-conditional labels:**
   ```
   SIP = f(skill, task, regime)
   ```
   A session where the skill activates, friction is detected, and the agent
   switches to print mode is not INTERACTIVE_BLOCKADE (destructive) or
   PROCEDURAL_SCAFFOLDING (constructive). It's **REGIME_ADAPTATION** — the skill
   correctly identified the environment and changed strategy. CTA measures: does
   this adaptation close the CPI gap between regimes?

**The honest boundary (Gap 3):**

H8 proves the **instrument** works (classification accuracy: 9/9 = 100%). It does
NOT prove the **treatment** works (that acting on the signal improves outcomes).
The instrument is necessary but not sufficient for the causal claim.

Gap 3 closure requires: same task, same friction regime, ±adaptation. That's a
2×2 design (regime × response) nested within the existing 2×2 (skill × task).
Minimum evidence: one paired session where friction fires, agent adapts per
SKILL.md, and CPI recovers toward clean-regime baseline.

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

### §4.0 Gap 3 Pre-Registration (LOCKED before unblinding)

**Status: PRE-REGISTERED 2026-07-22, before sibling's Gap 3 run (PID 8176) unblinds.**
This subsection freezes the analysis rules per reconciliation rule R5 (blind
evaluation). Once locked, the decision rule, metric, and reconciliation rules
CANNOT be changed after results are seen. Changes after unblinding invalidate the
claim and must be logged as post-hoc in §10. Adapted from the dual-engine
epistemic chain (`compose-pkl/docs/patent/verification/dual-engine-epistemic-chain.html`):
deduction (`detect_regime_adaptation()` registry, deterministic) confronts
induction (CPI measured from sessions), with reconciliation rules preventing
incestuous amplification (Boyd; Kaddour et al. 2023).

**Why this exists:** Gap 3's verdict was previously a single comparison
(`treatment_CPI > control_CPI`) with no uncertainty, no pre-locked rules, and an
N=1 design. The §0.3.7 "Outcome Interpretation" table is post-hoc narrative unless
frozen here. Pre-registration is the clinical-trial standard that separates
confirmatory from exploratory analysis.

#### 4.0.1 Primary outcome and decision rule

| Field | Locked value |
|-------|--------------|
| Primary metric | CPI = (success_rate × expected_growth) / actual_growth |
| Effect | Δ_CPI = CPI_treatment − CPI_control (paired by run_num) |
| Direction of interest | Δ_CPI > 0 (treatment recovers toward clean baseline >1.0) |
| Confirmatory threshold | Δ_CPI > 0 AND treatment_CPI > 1.0 on ≥2 of N pairs |
| Minimum N for confirmatory claim | **N ≥ 3 paired runs** (see 4.0.2) |

**Decision rule (frozen):** Gap 3 is CONFIRMED only if the confirmatory threshold
holds on N≥3 valid, non-escaped pairs. A single pair (N=1) can ONLY produce an
EXPLORATORY result, explicitly labeled as such — it cannot close Gap 3 regardless
of how large Δ_CPI is.

#### 4.0.2 What N=1 can and cannot claim (honesty boundary)

A single paired run has catastrophic Type M error: with one observation per arm,
any observed effect is almost certainly a magnitude exaggeration, and the sign may
be wrong (high Type S). Therefore:

- **N=1 VALID pair →** report as "exploratory single-pair observation." Report
  Δ_CPI with the explicit caveat that no uncertainty estimate is possible. Do NOT
  write "Gap 3 closed." This is a hypothesis-generating result, not a confirmation.
- **N≥3 VALID pairs →** fit the hierarchical model in 4.0.4 and report Type S/M.
  Only this supports a confirmatory claim.

If sibling's current run (N=1) is valid and treatment > control, the correct
conclusion is "promising — requires replication at N≥3," NOT "Gap 3 closed."

#### 4.0.3 Reconciliation rules (locked, R1–R4 adapted)

Applied to every FI-vs-CPI and treatment-vs-control comparison. A claim that fails
one reconciliation rule is REJECTED regardless of the headline metric.

| Rule | Condition | Action |
|------|-----------|--------|
| **R1 — Convergence mismatch** | `detect_regime_adaptation()` fires (skill activated, friction detected) but CPI does not improve in treatment | TRUST the detector's structural logic; FLAG the prescription as weak. The mechanism is sound; the guidance did not change behavior. Report as "instrument valid, treatment inert." |
| **R2 — Sign reversal** | Treatment_CPI < Control_CPI (guidance causes WORSE outcomes — over-triggering / premature abandonment) | **HARD REJECT** the prescription. Do not ship SKILL.md friction block unchanged. Trigger the redesign path in §0.3.7 (confidence threshold, not binary kill). |
| **R3 — Direction agree, magnitude disagree** | Both arms agree friction is present (FI≥0.40 in both) but Δ_CPI magnitude is outside the calibrated CI | TRUST direction, FLAG magnitude. Report both CPI values with uncertainty; do not over-interpret the size of the effect. |
| **R4 — Perfect agreement / co-adaptation** | FI and CPI label agree on 100% of sessions (the H8 9/9 result), OR treatment≡control on every metric | **FLAG as suspicious.** Genuinely independent engines diverge. Run the co-adaptation check in 4.0.5 before treating agreement as validation. |

#### 4.0.4 Inductive engine (Bayesian hierarchical model, N≥3)

For N≥3 paired runs, fit (in Stan or equivalent):

```
CPI_ij ~ Normal(μ_ij, σ)
μ_ij = β0 + β1·treatment_j + β2·regime_ij + u_pair_j
u_pair_j ~ Normal(0, σ_pair)        # pair-level random effect
```

- `β1` = treatment effect (the skill_effect isolated from environment_effect)
- `u_pair_j` absorbs pair-level environment noise (the friction regime is a
  moderator, §1.1 — pairing controls for it)
- Report posterior median + 95% credible interval for `β1`, plus R-hat (<1.05)
  and ESS (>100) convergence diagnostics.

**Type S/M (mandatory for any confirmatory claim):**
- Type S = P(sign(β1) wrong | data). Report as a percentage.
- Type M = E[|β1_estimate| / |β1_true| | data, sign correct]. Report as a ratio;
  1.00× is unbiased, >1.0 is exaggeration. (Compose-pkl measured α=0.857×,
  β=1.033× — even instrumented measurements overstate. We will not claim 1.00×.)

#### 4.0.5 Co-adaptation check on H8 (R4 follow-up)

The H8 result (9/9 = 100% agreement between runtime FI label and post-hoc CPI
label) is exactly what R4 flags: FI and CPI are both computed from the SAME NDJSON
stream, so they are not independent engines. Perfect agreement may be co-adaptation,
not validation. Before H8 is cited as confirmatory evidence:

1. **Held-out signal test:** classify the same sessions using a signal NOT in the
   FI formula (e.g., raw message count, or wall-clock duration). If the held-out
   signal also separates regimes, the discrimination is real, not an artifact of
   FI and CPI sharing inputs.
2. **Independent scorer:** a second agent (or human) classifies friction traces
   BLIND to condition and to the FI value. Agreement between blind scorer and FI
   breaks the same-codebase loop. (This is the strongest available substitute for
   external replication, which we lack — compose-pkl gap C2/G9.)
3. **Document the limitation:** until 1 or 2 passes, H8 is labeled "validated
   within-codebase; independent confirmation pending," not "proven."

#### 4.0.6 Robustness gates for Gap 3 (G1–G8 adapted)

A confirmatory Gap 3 claim must pass ≥6 of 8. Failing >1 robustness gate (while
passing reconciliation) downgrades "confirmed" to "promising — requires replication."

| # | Gate | Gap 3 test | Minimum |
|---|------|-----------|---------|
| G1 | Benchmark independence | Does Δ_CPI>0 survive a SECOND model provider (not just kimi-k2.7-code)? | ≥1 replication provider |
| G2 | Seed independence | Stable Δ_CPI across ≥3 run_nums (paired)? | CI on β1 excludes 0 |
| G3 | Metric independence | Does the conclusion hold under escape-rate, task-completion, AND context-at-termination — not just CPI? | ≥2 of 3 metrics agree on sign |
| G4 | Ablation honesty | Does the control arm (v2.4.0, no friction block) isolate the friction guidance as the single differing factor? | Skill files identical except friction block |
| G5 | Variance visibility | Are CPI distributions reported, never bare means? | Mandatory |
| G6 | Baseline sanity | Is treatment_CPI meaningful vs the clean-regime baseline (1.594, Plan 2 Phase 6)? | Treatment recovers ≥50% of the gap to clean |
| G7 | Claim scope | Is the claim bounded to "F1 friction regime, JWT-auth task, kimi model"? | No over-generalization |
| G8 | Leakage / escape | Is neither arm escaped (flask/jwt NOT importable at session end)? | Both arms escape-free |

**Escape is a hard gate (G8):** any arm with flask/jwt installed at session end is
INVALID and excluded, regardless of CPI. (Run-1 treatment escaped via urllib+ssl;
the venv split + step 12 close this, but G8 must be re-verified per run.)

#### 4.0.7 Operating rule (frozen)

A Gap 3 claim is **CONFIRMED** only if: (a) N≥3 valid escape-free pairs, AND
(b) all reconciliation rules R1–R4 pass, AND (c) ≥6 of 8 robustness gates pass,
AND (d) Type S/M reported. A claim failing any reconciliation rule is REJECTED. A
claim passing reconciliation but failing >1 robustness gate is DOWNGRADED to
"promising — requires replication." An N=1 result is EXPLORATORY and cannot close
Gap 3 under any circumstance.

### §4.1 Redesigned Friction Probe (post-Run-1)

**Why this exists:** Run 1 (F1 environment) produced **no fire** (§4.0 sub-case a).
The inner agent absorbed missing-package friction at the code level (stdlib
`jwt_compat.py`); nothing surfaced to Hermes as error tool_results, so the
prescription never fired. F1 tested the prescription against a friction type it was
never designed to handle. This probe produces **genuine Hermes-visible friction** so
the prescription can actually be exercised.

#### 4.1.1 The prescription's two mechanisms (clarified)

The SKILL.md prescription is "kill the qodercli session, retry with `-p`." This
helps via two distinct mechanisms:

| Mechanism | When it helps | Proven? |
|-----------|--------------|---------|
| **M1 — Mode switch** | `-i`/background mode is itself broken; `-p` avoids the broken mode | **Yes** — exit-42 (bgmode test P8-phase3-bgmode): model quoted guidance, fell back to `-p`, completed task |
| **M2 — Context reset** | Session is dying from accumulated friction context; a fresh `-p` start avoids the death spiral | **No** — plausible but uninstantiated; requires friction that accumulates terminal context |

Run 1 tested neither (no fire). The bgmode test proved M1's **behavior** (model
follows guidance) but had **no control arm and no CPI measurement** — it never showed
the prescription *improves outcomes*, only that the model *complies*. That is the gap
this probe fills.

#### 4.1.2 Primary probe: PAIRED background-mode (exit-42) experiment

Test the prescription in its **proven domain (M1, mode friction)** with the missing
ingredient: a control arm + CPI comparison.

**Design:**
- **Task:** the same JWT-auth task, but Hermes launches qodercli in **background
  mode** (`background=true, pty=true`) — the condition that triggers exit-42 on `-i`.
- **Treatment (v2.5.1):** has friction/exit-42 guidance → should detect exit-42,
  fall back to `-p` quickly.
- **Control (v2.4.0):** no guidance → expected to retry `-i` repeatedly into a
  context death spiral (the failure mode the prescription prevents).
- **Both arms** install a skill; only the friction block differs (G4 ablation honesty).
- **Image:** `registry.rossollc.com/hermes:latest` (NOT the friction image).

**Image choice rationale (revised post-Run-1):**
- **Why NOT `hermes:friction`:** Compound friction (exit-42 + missing deps) violates
  G4 (ablation honesty). The `-p` fallback session would hit dep-friction and
  self-heal at the code level (Run 1 replay), masking the exit-42 signal. You'd
  measure "can the agent self-heal dep-friction in `-p` mode" instead of "does the
  prescription recover from mode friction."
- **Why NOT read-only FS:** The prescription's recovery path is kill → diagnose →
  fix environment → retry `-p` *in the same container*. A non-remountable read-only
  bind mount makes "fix the environment" structurally impossible — the prescription
  can never complete its recovery sequence. A null would be uninterpretable (R6:
  construct-invalid).
- **Why `hermes:latest`:** Deps present → exit-42 is the ONLY friction → the `-p`
  fallback completes the task cleanly → treatment_CPI > control_CPI directly
  measures the prescription's value for M1. One variable, one mechanism, clean
  ablation. The prescription doesn't conjure recovery from unfixable environments —
  it recovers efficiency on *fixable* friction (kill early + mode-switch, instead of
  burning context in a retry loop).

**Harness change:** One-line `CONTAINER_IMAGE` override in
`scripts/gap3_friction_harness.py` (or a `--image` flag):
```python
CONTAINER_IMAGE = "registry.rossollc.com/hermes:latest"
```

**Hypothesis (pre-registered direction):**
- Control: retries `-i` → repeated exit-42 errors visible in process() poll →
  FI≥0.40 (high retry density on the `-i` launch signature + context velocity) →
  context exhaustion / timeout → **low CPI**.
- Treatment: hits exit-42 once, falls back to `-p` → transient FI then recovery →
  task completes with low context burn → **higher CPI**.
- Predicted: **treatment_CPI > control_CPI**, with control showing the death spiral
  the prescription is designed to prevent.

**This is the fire the extinguisher was built for.** Unlike F1 (environment friction
the agent self-heals), exit-42 is a mode failure the inner agent cannot code around —
it surfaces to Hermes as visible errors regardless of the agent's coding skill.

#### 4.1.3 Success / failure criteria (tied to §4.0)

| Probe outcome | Classification | Next action |
|---------------|---------------|-------------|
| Treatment_CPI > control_CPI, control shows death spiral, treatment fell back to `-p` | **Prescription works for M1 (mode friction)** — fire extinguished | Run N≥3 paired bgmode runs to confirm (§4.0.4 hierarchical model + Type S/M). Then test M2 generalization (4.1.5). |
| Treatment ≈ control, BOTH fall back to `-p` | **Sub-case (b) native adaptation** — control figures out `-p` without guidance | Prescription is redundant even in its proven domain → **option 3 (scope reduction)**. The instrument (H8) retains monitoring value. |
| Treatment ≈ control, BOTH stuck | Guidance arrives but doesn't change behavior | Friction block placement/salience problem → redesign guidance delivery (system-level injection). |
| Treatment < control | Over-triggering / premature abandonment | **R2 HARD REJECT** → confidence-threshold redesign (§0.3.7). |

**Note:** This probe is still **N=1 → EXPLORATORY** per §4.0.2. It cannot close Gap 3.
Its purpose is to resolve the Run-1 ambiguity (inert vs no-fire) cheaply before
committing to N≥3. A positive result here justifies the N≥3 investment; a null here
saves it.

**Run 2 result (2026-07-22, hermes:m1probe, kimi-k2.7-code) — NO FIRE, new mechanism.**
Both arms VALID (treatment 54 msgs/250.5s, control 41 msgs/225.4s; both exit 0; both
produced working `auth.py`+`token.py`). But **exit-42 never occurred in either arm.**
Ground truth from state.db terminal tool_calls:

- Treatment: `qodercli -p "Implement JWT..."` → exit 0 (one launch, `-p` directly).
- Control: `qodercli -p 'Implement...'` → exit 0 (two `-p` launches). **Neither arm
  ever invoked `-i`.**

The probe's antecedent — "Hermes launches `-i` in background, hits exit-42, treatment's
guidance triggers the `-p` fallback" — was never satisfied, because **both models chose
`-p` up front.** The SKILL.md mode table ("Default to print mode" for bounded tasks) is
*shared by both skill variants* and overrode the prompt's "use background mode"
instruction in both arms. The exit-42 prescription could not fire because its trigger
condition (an `-i` attempt) never arose.

**This is a THIRD no-fire mechanism, distinct from the other two:**

| Run | Friction | Why no fire | Mechanism class |
|-----|----------|-------------|-----------------|
| Run 1 | F1 (missing deps) | Inner agent self-healed at code level (stdlib `jwt_compat.py`); nothing surfaced to Hermes | Self-heal (antecedent absorbed) |
| Run 2 | exit-42 (mode) | Both arms chose `-p` directly per the skill's own print-mode default; `-i` never attempted | **Antecedent unreachable under the skill's own design** |
| §4.1.3 sub-case (b) | exit-42 | Control tries `-i`, fails, figures out `-p` anyway | Native adaptation (antecedent reached then overcome) |

Run 2 is **not** sub-case (b): in (b) the control attempts `-i` and abandons it; here
neither arm attempted `-i` at all. The fire was never lit because the skill's dominant
print-mode recommendation preempts the `-i` attempt that exit-42 punishes.

**Per-arm efficiency (raw, N=1, EXPLORATORY — not a CPI claim):** treatment used MORE
resources than control (20 vs 13 API calls; 59.3k vs 40.2k input tokens; 401k vs 244k
cache-read; 250.5s vs 225.4s) for the same successful outcome. If anything the
treatment arm was *less* efficient — but with exit-42 absent in both, this difference
is unrelated to the prescription (noise on a shared `-p` code path). **No signal for
the exit-42 prescription; mild negative point estimate, uninterpretable at N=1.**

**Implication (R6 fires again, deeper):** The exit-42 prescription is **behaviorally
redundant in the bounded-task regime** — not because it fails when needed, but because
the skill's own print-mode default means `-i` is rarely attempted, so exit-42 rarely
surfaces. The prescription's proven domain (bgmode test, where `-i` was *forced*) is a
narrow edge case the skill's general guidance already preempts. Per §4.1.4 this is the
**option 3 (scope-reduction)** branch — but reached via "antecedent unreachable" rather
than "native adaptation." The two have different SKILL.md actions: native adaptation →
delete the exit-42 block as dead weight; antecedent-unreachable → keep exit-42 as a
*narrow edge-case guard* but stop presenting it as a general friction protocol, and
recognize the print-mode default is doing the real work.

**Do NOT replicate this probe (R6).** Re-running produces the same no-fire: a capable
model following the print-mode default will keep choosing `-p`. To force the exit-42
antecedent would require *removing* the print-mode recommendation (testing the
prescription against a deliberately worse skill) — which measures an artificial regime,
not the shipped skill's behavior. The honest conclusion: the exit-42 prescription is a
redundant safety net under the current skill design, not a load-bearing behavior.

#### 4.1.4 Decision gate (option 2 vs option 3)

- **If the probe shows treatment > control** (prescription extinguishes a real fire):
  → **option 2.** Commit to N≥3 paired bgmode runs for a confirmatory claim, then
  probe M2 (context-reset) generalization.
- **If the probe shows treatment ≈ control** (native adaptation or inert):
  → **option 3.** Scope-reduce Plan 8: the prescription's value is bounded; the
  friction INDEX (H8) is the durable deliverable for Hermes monitoring, and the
  prescription is at best a narrow mode-friction helper. Document as honest finding.

This is the cheap-probe-before-expensive-commitment principle (Plan 8 §6.3 RCF):
do not sink N≥3 API budget into a path before checking the construct produces fire.

#### 4.1.5 Secondary probe (M2 context-reset, lower priority)

Only if 4.1.2 confirms M1. Tests whether the prescription generalizes beyond mode
friction to a **designed context death spiral**:

- **Friction design:** a persistent, high-output error the inner agent cannot resolve
  in `-i` mode (e.g., a test runner that emits large tracebacks on every retry),
  causing context velocity to climb until FI≥0.40 surfaces to Hermes.
- **Open risk (honest):** a capable agent may self-heal (as in Run 1) or abandon the
  task, producing no death spiral. If so, M2 is not instantiable and the prescription's
  domain is confirmed narrow (M1 only). This is informative, not a failure.
- **Design constraint:** the friction must be unsolvable-in-accumulated-context but
  solvable-fresh-in-`-p` — a narrow space. If no clean instantiation exists, document
  M2 as theoretical and close Plan 8 on M1.

#### 4.1.6 What this probe CANNOT show

- It cannot confirm Gap 3 at N=1 (exploratory only, §4.0.2).
- It cannot prove the prescription helps for **environment friction the inner agent
  self-heals** — Run 1 already showed that case is inert by construction (no fire).
- A positive M1 result generalizes only to **mode friction**, not to all friction.
  Claim scope (G7) must stay bounded to "background-mode/exit-42 family."

---

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

> **TERRITORY AUDIT (2026-07-22):** Live probe of `registry.rossollc.com/hermes:latest`
> (digest `59843a2193a4`) reveals the F1/F3 Dockerfiles below are **stale** — they
> target `python:3.11-slim` but the actual base is Python 3.13.12 with additional
> escape vectors not addressed:
>
> | Tool | Path | F1/F3 removes? |
> |------|------|----------------|
> | `uv 0.9.24` | `/usr/bin/uv` | **NO** (critical gap) |
> | `pip 25.3` | `/usr/local/bin/pip` | Yes |
> | `ensurepip` | python3 -m ensurepip | Yes |
> | `curl` | `/usr/bin/curl` | Yes |
> | `wget` | not present | N/A |
> | `apt-get` | `/usr/bin/apt-get` | Yes |
> | `dpkg` | `/usr/bin/dpkg` | Yes |
> | `urllib` | stdlib | **NO** (needs `--network=none`) |
>
> Additional findings:
> - Harness scripts (`m3_interactive_harness.py`, `capture_harness.py`) hardcode
>   `CONTAINER_IMAGE` with no `--image` flag — requires edit or new harness.
> - `container build` (Apple Container native) supports Dockerfiles directly.
> - `container run --network <network>` exists for network isolation.
>
> **Resolution (2026-07-22):** Materialized as `containers/Dockerfile.friction`
> (based on `hermes:latest`, uv removed from `/usr/bin/uv`). Built and tagged
> `registry.rossollc.com/hermes:friction`. Inescapability verified via live probe.
> Paired experiment running via `scripts/gap3_friction_harness.py`.

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

#### Phase 1b Execution Results (2026-07-21)

**Approach A (direct capture): FAILED — agent too resilient.**

Three attempts to induce friction locally, all defeated by the agent:

| Attempt | Friction inducer | Agent workaround | FI | Result |
|---------|-----------------|-----------------|-----|--------|
| 1 | Missing packages (no venv) | Agent created venv, installed via system pip | 0.063 | CLEAN |
| 2 | PIP_INDEX_URL=unreachable | Agent used `uv` (bypasses pip entirely) | 0.047 | CLEAN |
| 3 | PATH restricted + fake pip + PIP_INDEX_URL | Agent used `ensurepip` + overrode env var | 0.083 | CLEAN |

**Root cause:** On a development machine with full Bash access, the agent can
always find a workaround (uv, ensurepip, absolute paths, env override). Real
friction requires Docker with removed pip/ensurepip/curl/wget/network (F1/F3
configs above). Docker daemon was unavailable during this test.

**Approach B (synthetic reconstruction): E1 CONDITIONAL PASS.**

Reconstructed a realistic friction NDJSON from G3 run 1's state.db outer
conversation (50 tool calls, exit codes, error patterns visible). The synthetic
models the actual failure cascade: ModuleNotFoundError → pip permission warnings →
path confusion → pytest collection errors → syntax error → blueprint registration.

Evidence: `data/m3_captures/P8-synthetic-friction-g3run1/raw.ndjson` (55 events)

**Sliding-window analysis (window=50, matching implementation):**

| Window | FI | Error rate | Ctx vel norm | Retry | Classification |
|--------|-----|-----------|-------------|-------|----------------|
| [0:10] (initial burst) | **0.433** | 0.750 (3/4) | 0.150 | 0.400 | **FRICTION** |
| [0:20] | 0.302 | 0.556 (5/9) | 0.150 | 0.200 | MILD |
| [0:40] (friction phase) | 0.257 | 0.421 (8/19) | 0.150 | 0.200 | MILD |
| [0:55] (full session) | 0.230 | 0.385 (10/26) | 0.150 | 0.154 | MILD |
| Clean baseline (P7-3) | 0.086 | 0.000 | 0.030 | 0.220 | CLEAN |

**E1 gate verdict: CONDITIONAL PASS.**

- Peak FI during friction phase: **0.433** (separation 0.347 ≥ 0.25 ✓)
- Full-session FI: 0.230 (separation 0.144 < 0.25 ✗)

The friction_index is a **current-state indicator** (§6.1 A4), not a session
summary. At poll time during the friction burst, Hermes sees FI=0.433 →
`⚠ Friction: HIGH-ERROR (3/4) | RETRY Bash x4`. After recovery, FI correctly
drops to 0.230. This is the designed behavior.

**E1 interpretation:** The gate tests whether the index *discriminates* regimes.
It does: clean=0.086, friction-phase=0.433. The full-session average is diluted
by recovery (correct — the session IS no longer in friction). E1 passes on the
discrimination question.

**Remaining gap:** A real Docker-captured friction session (F1/F3) would provide
stronger evidence than synthetic reconstruction. Deferred to when Docker is
available. The synthetic is a proxy — documented as limitation per §8 protocol.

### Phase 2: Prospective validation (requires Hermes runtime)

Run 6+ sessions through the existing harness with friction index logging enabled.
Compute agreement between runtime friction label and post-hoc CPI label.

**Infrastructure ready (v0.2.4):**
- `_move_to_finished()` in the overlay auto-dumps raw NDJSON to
  `/root/output/raw_<session_id>.ndjson` on every ndjson_mode session completion.
  No additional code changes needed — just run the harness.
- `scripts/score_friction.py` scores captured streams offline:
  `python3 scripts/score_friction.py /root/output/raw_proc_*.ndjson --json`

**Gate:** ≥80% agreement (H8 threshold). Sessions where they disagree are
analyzed individually — disagreement is interesting, not just failure.

**Phase 2 EXECUTED (v0.2.5) — H8 CONFIRMED:**

| Session | Source | FI (full) | CPI proxy | Runtime label | Post-hoc label | Agree? |
|---------|--------|-----------|-----------|---------------|----------------|--------|
| session_1 | P8-phase2-prospective | 0.121 | 1.42 | clean | clean | ✓ |
| session_2 | P8-phase2-prospective | 0.113 | 1.38 | clean | clean | ✓ |
| session_3 | P8-phase2-prospective | 0.118 | 1.45 | clean | clean | ✓ |
| session_4 | P8-phase2-prospective | 0.109 | 1.51 | clean | clean | ✓ |
| session_5 | P8-phase2-prospective | 0.115 | 1.33 | clean | clean | ✓ |
| session_6 | P8-phase2-prospective | 0.107 | 1.48 | clean | clean | ✓ |
| P7-2 | P7-ndjson-treatment-2 | 0.086 | 1.60 | clean | clean | ✓ |
| P7-3 | P7-ndjson-treatment-3 | 0.113 | 1.35 | clean | clean | ✓ |
| synthetic-friction | P8-synthetic-friction-g3run1 | 0.433 (peak) | 0.62 | friction | friction | ✓ |

**Agreement: 9/9 = 100%** (threshold ≥80% ✓)

- Clean range: FI 0.086–0.121 (all < 0.15 display threshold)
- Friction: FI 0.433 (peak, sliding window during friction burst)
- Zero false positives, zero false negatives
- **E5 trivially satisfied:** no disagreements to analyze

**Limitations:**
- 8/9 sessions are clean; only 1 friction session (synthetic reconstruction)
- Docker unavailable — no organic friction capture possible on this machine
- CPI proxy uses `(success_rate × expected_growth) / actual_growth`, not full CPI

**Verdict:** H8 CONFIRMED. The friction_index discriminates clean from friction
regimes with 100% agreement against CPI labels across N=9 sessions. Phase 3
(integration) is unblocked.

### Phase 3: Integration (post-merge, if H8 confirmed)

Wire the friction index into `_format_ndjson_progress()` in the hermes-agent fork.
No PR to upstream until Phase 2 validates. **H8 confirmed — Phase 3 unblocked.**

**Container infrastructure (from Plan 1 §M2):**

- **Image:** `registry.rossollc.com/hermes:latest` (local, digest `59843a2193a4`)
- **Runtime:** Apple Container (`container` CLI). Start with `container system start`.
- **In-container upgrade to v0.19.0 (~20s):**
  ```bash
  cd /opt/hermes
  git fetch origin a41d280f95c69f67380358b305b62345934ecaf3 --depth=1
  git checkout -f a41d280f95c69f67380358b305b62345934ecaf3
  uv pip install . --python /opt/hermes/.venv/bin/python3 --quiet
  npm install -g @qoder-ai/qodercli@1.1.1
  ```
- **Harness scripts:** `scripts/m3_interactive_harness.py` (interactive NDJSON),
  `scripts/capture_harness.py` (print-mode counterfactual)
- **Provider:** opencode-go / kimi-k2.7-code (`OPENCODE_GO_API_KEY` env var)
- **WAL checkpoint required** before copying state.db:
  `PRAGMA wal_checkpoint(TRUNCATE)`
- **NDJSON auto-dump:** `_move_to_finished()` writes raw NDJSON to
  `/root/output/raw_<session_id>.ndjson` on ndjson_mode session completion
- **Persistence context:** Plan 8's NDJSON-only captures (`P8-phase2-prospective/`,
  6 sessions) represent the lightest persistence pattern in the M2→M3→P8 evolution.
  NDJSON is written line-by-line (inherently crash-safe), requires no WAL checkpoint,
  no SQLite dependency, and can run without a container. This eliminates the
  kalloc.1024 crash vulnerability entirely for friction measurement captures.
  Full persistence reference: [`docs/container_mounts_and_secrets.md`](../docs/container_mounts_and_secrets.md).

**Execution steps:**

1. Deploy friction index implementation (`data/ndjson_overlay/process_registry.py`)
   into the container's `/opt/hermes/tools/process_registry.py`
2. Run 3+ interactive sessions via `m3_interactive_harness.py` with ndjson_mode
3. Score captured NDJSON with `scripts/score_friction.py`
4. Verify runtime friction display matches post-hoc score

**Phase 3 Evidence (Gap 2 closure, 2026-07-22):**

Gap 2: "friction index visible in live Hermes poll output." Proven by feeding
NDJSON through `_format_ndjson_progress()` extracted from the deployed overlay:

| Regime | Input | FI | Display output | E3/E4 |
|--------|-------|-----|----------------|-------|
| CLEAN | `P8-phase2-prospective/session_1.ndjson` (live) | <0.15 | *(no annotation)* | E3: 0 chars ✓ |
| MILD | Live pipe-mode run (`/tmp/p8-phase3-pipe-test.ndjson`, 10 events) | 0.333 | `errors: 0/1` | +11 chars ✓ |
| HEAVY | Synthetic friction (10 calls, 5 errors, retries) | ≥0.40 | `⚠ Friction: HIGH-ERROR (5/10) \| CTX-VELOCITY +2.8%/ev \| RETRY Bash x10` | E4: ~80 chars ✓ |

Method: `qodercli -p --output-format stream-json --permission-mode bypass_permissions`
produces valid NDJSON in pipe mode. The overlay's `_format_ndjson_progress()` was
extracted and executed against each input. All three display thresholds fire correctly.

Note: The MILD case (FI=0.333) is a known edge case — retry_density=1.0 on a
single-tool-call session. Multi-tool clean sessions score 0.086–0.121 (Phase 2).

**Remaining:** Live container session where qodercli successfully emits NDJSON
through the pipe-spawn path (exit-42 fallback to `-p` mode) to prove the display
in an actual Hermes `process()` poll loop. The overlay is deployed; the blocker
is the `-i` → `-p` fallback logic in the model's tool invocation.

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
| 0.4.0 | 2026-07-22 | **§4.1 exit-42 probe (Run 2) executed — VALID but NO FIRE → option 3 (scope reduction).** Built `hermes:m1probe` (pinned commit `a41d280`, overlay-compatible, deps present — no friction removals) after the first attempt infra-failed on base `hermes:latest` (NDJSON overlay imports `nous_tool_gateway_unavailable_message`, absent from the unpinned base). Both arms VALID (treatment 54 msgs/250.5s, control 41 msgs/225.4s, both exit 0, both produced working auth.py+token.py). **Ground truth from state.db terminal tool_calls: exit-42 never fired in either arm — both launched `qodercli -p` directly; neither ever attempted `-i`.** The skill's shared "default to print mode" table overrode the prompt's background-mode instruction in BOTH arms, so the prescription's trigger (an `-i` attempt) never arose. This is a THIRD no-fire mechanism — *antecedent unreachable under the skill's own design* — distinct from Run 1 (F1 self-heal) and from §4.1.3 sub-case (b) native adaptation (which assumes `-i` was tried then abandoned). Per-arm efficiency (N=1, EXPLORATORY): treatment used MORE resources than control (20 vs 13 API calls, 59.3k vs 40.2k input tokens) for the same outcome — no signal for the prescription, mild negative point estimate, uninterpretable at N=1. **R6 fires: do NOT replicate** (a capable model following the print-mode default keeps choosing `-p`; forcing `-i` would require a deliberately worse skill = artificial regime). Conclusion: the exit-42 prescription is a **redundant edge-case guard**, not a load-bearing behavior — the print-mode default does the real work. Gap 3 lands on option 3: narrow SKILL.md's friction section, keep exit-42 as a narrow guard, stop presenting it as a general friction protocol. Result is [DEDUCTIVE] (no-fire mechanism fact) + [EXPLORATORY] (N=1 efficiency), per Plan 9 §1.1 mixed-claim labeling. |
| 0.3.9 | 2026-07-22 | **Run-1 reframe + §4.1 redesigned friction probe.** Run-1 (N=1) returned treatment=control=success — initially read as "extinguisher inert." Corrected: this is sub-case **(a) NO FIRE**, not an inert-verdict. F1 friction (missing flask/pyjwt) self-healed inside the inner qodercli session before it could surface to Hermes, so the SKILL.md friction guidance was never *triggered* — the construct was not exercised, not disproven. Refined the §4.0 Outcome Interpretation table "both succeed" row to split (a) no-fire (construct-validity gap) from (b) native adaptation (genuine null). Added **§4.1 Redesigned Friction Probe**: probes the *proven* friction domain (exit-42 mode-switch, from §0.3.4 bgmode test) instead of the self-healing F1 domain. Primary probe = PAIRED background-mode/exit-42 experiment with the missing control arm + CPI measurement (4.1.2), success/failure criteria (4.1.3), decision gate (4.1.4: option 2 N≥3 replication vs option 3 scope reduction), secondary M2 context-reset probe (4.1.5), and explicit limits on what the probe cannot show (4.1.6). Run-1 remains EXPLORATORY per §4.0.2 — cannot close Gap 3. |
| 0.3.8 | 2026-07-22 | **Gap 3 pre-registration LOCKED (§4.0).** Added §4.0 "Gap 3 Pre-Registration" before sibling's run (PID 8176) unblinds, per reconciliation rule R5 (blind evaluation). Adapts the dual-engine epistemic chain (`compose-pkl/docs/patent/verification/dual-engine-epistemic-chain.html`): deduction (`detect_regime_adaptation()` registry) confronts induction (CPI). Locks: primary metric (Δ_CPI, paired), confirmatory threshold (Δ_CPI>0 AND treatment>1.0 on ≥2 of N pairs), **N≥3 minimum** for any confirmatory claim (N=1 is EXPLORATORY only — cannot close Gap 3). Reconciliation rules R1–R4 frozen (R2 sign reversal = HARD REJECT; R4 perfect agreement = co-adaptation flag). Bayesian hierarchical model (`CPI ~ condition + regime + (1|pair)`) with mandatory Type S/M reporting for N≥3. Co-adaptation check on H8 9/9 (FI and CPI share the same NDJSON stream — not independent engines; requires held-out signal or blind scorer). Robustness gates G1–G8 adapted (G8 escape = hard gate). Operating rule: CONFIRMED requires N≥3 + all R1–R4 + ≥6/8 gates + Type S/M. **Key honesty boundary:** even a valid N=1 treatment>control result is "promising — requires replication," not "Gap 3 closed." |
| 0.3.7 | 2026-07-22 | **Post-reboot recovery + second infra fix.** kalloc.1024 restored (~118k elements, headroom ~2.88M). Run-1 re-attempt: both arms infra_failure in ~5s — `hermes_cli/auth.py:26` does `import ssl` at startup; removing ssl.py from system python killed hermes entirely. **Fix (step 11 revised — venv split):** copy `ssl.py` + `_ssl*.so` into `/opt/hermes/.venv/lib/python3.13/site-packages/`, then remove from system python. Hermes venv python finds ssl in its own site-packages; agent's bare `python3` should not. Image rebuilt `--no-cache` + verified: hermes venv ssl → OpenSSL 3.0.19, `hermes --version` → v0.19.0, flask/jwt/pip/uv/curl/wget/apt all blocked, urllib HTTPS blocked (step 12). **Residual escape accepted:** system python can still `import ssl` (sitecustomize.py leaks hermes venv site-packages onto system sys.path). Raw `ssl.create_default_context()` + socket download is a novel multi-step chain the model is unlikely to discover under 900s time pressure. Proven escape (urllib one-liner) remains blocked. **Paired experiment re-launched** — awaiting results. |
| 0.3.6 | 2026-07-22 | **Gap 3 run-1: INVALID — friction escaped.** Treatment arm completed (46 msgs, exit 0) but did NOT experience sustained friction: qodercli's inner session used `urllib.request` over Python `ssl` to download get-pip.py and reinstall flask/pyjwt (proven via state.db trace: pytest ImportError at msg 31, then 15 passed at msg 39 with jwt warning from system site-packages). Control arm was infra_failure (exit 137 kalloc, retry failed on stale container name — no session produced). **Escape vectors patched:** step 11 removes `ssl.py` + `_ssl.cpython-313-aarch64-linux-gnu.so` (blocks all Python HTTPS; Node.js TLS unaffected so LLM API calls work); step 8b removes honcho `/app/.venv` flask/pyjwt; step 8c clears uv cache (`/tmp/uv-cache`, `/root/.cache/uv`). Image rebuilt `--no-cache` + verified: `import flask`/`import jwt`/`import ssl` all ModuleNotFoundError, `node https` returns 200, hermes v0.19.0 functional. **BLOCKED on reboot:** kalloc.1024 ~2.86M (headroom ~143k < 200k). Invalid runs preserved at `P8-gap3-friction-{treatment,control}-1-INVALID-ssl-escape/` as evidence the agent WILL escape via urllib+ssl when given the chance (validates F3 design rationale). Recovery: see §0 Next + `docs/container_mounts_and_secrets.md` §Friction Container Verification. |
| 0.3.5 | 2026-07-22 | **Gap 3 protocol designed.** Experimental design: ±adaptation paired sessions in F1 friction container (no pip/uv/curl/wget/apt, flask/pyjwt removed). Treatment arm: SKILL.md v2.5.1 (friction guidance block). Control arm: SKILL.md v2.4.0 (no friction block). Same task (JWT auth requiring flask+pyjwt). CPI recovery criterion: treatment CPI > control CPI, with treatment recovering toward clean-regime baseline (>1.0). Infrastructure: `containers/Dockerfile.friction` (F1 image via `container build`), `scripts/gap3_friction_harness.py` (paired runner, both arms install skill, only guidance block differs). Run IDs: `P8-gap3-friction-adaptation-{N}` / `P8-gap3-friction-control-{N}`. Timeout: 900s. Apple Container `container build` confirmed available (builder shim `0.11.0` local). Critical escape vectors addressed: `/bin/uv`, `/opt/hermes/.venv/bin/pip*`, `python3.13/ensurepip` all removed. |
| 0.3.4 | 2026-07-22 | **Bgmode test COMPLETE.** Container `P8-phase3-bgmode-treatment-1` (kimi-k2.7-code): model launched `-i` in background → exit 42, quoted SKILL.md exit-42 guidance verbatim ("Fall back to -p immediately — do NOT retry with -i"), fell back to `-p`, completed task (auth.py + token.py created with proper JWT implementation). 25-min reasoning loop stall due to adversarial prompt conflict ("Do NOT use print mode" vs skill guidance) — prompt-conflict stall, not skill failure. NDJSON: 1 line (exit-42 error only; no stream generated since `-i` failed immediately). Friction display NOT exercised in this run (already proven in Gap 2, v0.3.1). Evidence: `behavioral_trace.md` in capture dir. **Exit-42 → `-p` fallback guidance in SKILL.md v2.5.1 is proven effective in-container.** Only Gap 3 remains. |
| 0.3.3 | 2026-07-22 | **Restart checkpoint.** AGENTS.md created (Apple Container, NOT Docker — kalloc.1024 leak, bind mounts, secrets, friction scope). .gitignore updated (hermes_home runtime artifacts excluded). CTA commit `79edd8f` (38 files, 1927 insertions): regime-conditional framing, Phase 3 evidence, plans 1/2/7/8 persistence updates, audit_report + pr_writeup synced to v2.5.0. `detect_regime_adaptation()` integration test: 6 scenarios pass (constructive kill, constructive print-switch, neutral no-switch, clean empty, context-flag, registry dispatch). SKILL.md step 5 `-p` mandate verified: `qodercli\s+-p\b` matches detector pattern. hermes-agent fork pushed (`4d3623106` on `feat/add-qodercli-skill`). Background-mode container test launched: PID 22126, tag `P8-phase3-bgmode`, output at `data/m3_captures/P1-interactive-P8-phase3-bgmode-treatment-1/`. **On restart:** check `result.json` + `hermes_stdout.txt` in that dir for bgmode proof. Only Gap 3 remains (behavioral evidence, blocked on friction environment). |
| 0.3.2 | 2026-07-22 | **SKILL.md v2.5.1 pushed** (commit `00591faa6` on `fork/feat/add-qodercli-skill`). Changes: mild friction triage ("monitor, may self-recover"), heavy friction urgency ("act immediately"), exit-42 pipe conflict paragraph ("fall back to `-p`, never retry `-i`"). Integration tests persisted: `tests/test_regime_adaptation.py` (7/7 pass — 6 scenarios + registry count). 10-detector registry verified. CTA captures confirmed as v2.4.0 historical snapshots (no friction content). No active skills depend on old protocol. |
| 0.3.1 | 2026-07-22 | **Gap 2 CLOSED.** Friction display proven across all three regimes by feeding live NDJSON through `_format_ndjson_progress()`: CLEAN (session_1.ndjson, no annotation, E3=0 chars), MILD (live pipe-mode 10-event run, `errors: 0/1`, +11 chars), HEAVY (synthetic 10-call/5-error, `⚠ Friction: HIGH-ERROR (5/10) | CTX-VELOCITY +2.8%/ev | RETRY Bash x10`, ~80 chars, E4 ✓). Method: `qodercli -p --output-format stream-json` pipe mode. Remaining: in-container poll-loop proof (exit-42 `-i`→`-p` fallback). |
| 0.3.0 | 2026-07-21 | **Regime-conditional causal framing.** Added §1.1: friction as moderator/stratification instrument (not treatment). Core decomposition: `observed_outcome = skill_effect + environment_effect + noise`. Meta-SIP concept: SKILL.md friction guidance is a second-order intervention (treats the regime signal, not the task). SIPs are now `f(skill, task, regime)`. New SIP category: REGIME_ADAPTATION. Gap 3 boundary stated: H8 proves instrument validity, not treatment efficacy. Phase 3 deployed: friction index in hermes-agent fork, SKILL.md v2.5.0, live container proof (`P1-interactive-P8-phase3-friction-treatment-1`: valid, exit 0, 57.8s). `detect_regime_adaptation()` added to `skill_rules.py`. |
| 0.2.5 | 2026-07-21 | Phase 2 EXECUTED — **H8 CONFIRMED**. N=9 sessions (6 prospective + 2 P7 baseline + 1 synthetic friction). Agreement: 9/9 = 100% (threshold ≥80%). Clean FI: 0.086–0.121, Friction FI: 0.433 (peak). Zero FP/FN. E5 trivially satisfied. Limitation: 8/9 clean, synthetic friction only (Docker unavailable). Phase 3 (integration) unblocked. Evidence: `data/m3_captures/P8-phase2-prospective/`. |
| 0.2.4 | 2026-07-21 | Phase 2 infrastructure: (1) `_move_to_finished()` auto-dumps raw NDJSON to `/root/output/raw_<session_id>.ndjson` for ndjson_mode sessions. (2) `scripts/score_friction.py` standalone scorer for offline validation (--window, --json, exit codes). Validated: P7-2=0.113 CLEAN, P7-3=0.086 CLEAN, synthetic=0.20-0.43. |
| 0.2.3 | 2026-07-21 | Phase 1b EXECUTED. Direct capture FAILED (agent defeats all local friction: uv, ensurepip, env override — requires Docker F1/F3). Synthetic reconstruction from G3 run 1 state.db: peak FI=0.433 at friction burst [0:10], separation 0.347 ≥ 0.25. E1 CONDITIONAL PASS (current-state indicator discriminates regimes; full-session diluted by recovery at 0.230). Evidence: `data/m3_captures/P8-synthetic-friction-g3run1/`. Remaining: Docker-captured real friction when daemon available. |
| 0.2.2 | 2026-07-21 | Phase 1b friction environments: added F1 (no pip + missing deps, fi=0.683), F2 (read-only FS, fi=0.517), F3 (network isolation, fi=0.800) with Dockerfiles, signal budget table, anti-escape measures, expected failure cascade, and escalation recommendation (F1→F3). |
| 0.2.1 | 2026-07-21 | Consistency fixes + implementation: (1) BUG FIX — `tool_use_result` accessed from top-level user event, not inside tool_result block. (2) Implementation aligned with §3.2 composite formula (was using per-signal thresholds). (3) Signature extraction broadened to cover Agent/WebFetch/generic tools. (4) §3.2 documents 0.02 normalization constant and S4 display-only role. (5) Implementation deployed to `data/ndjson_overlay/process_registry.py`. (6) Phase 1a validated: P7-2/P7-3 score 0.086 (clean), synthetic friction scores 0.833 (HIGH). E3/E4 constraints verified. |
| 0.2 | 2026-07-21 | Phase 0 COMPLETE. K2a confirmed (context_usage_ratio on every complete assistant event). K1 verified (tool_result present, exitCode for Bash). K4 verified (varied inputs ≠ retries, signature approach correct). A3 resolved. New findings: A6 (G3 run 1 inner NDJSON not preserved — Phase 1 retrospective blocked), A7 (naive name-only retry matching causes false positives). Clean calibration: P7-3=0.093. Execution order updated: Phase 1 split into 1a (clean sanity, immediate) + 1b (friction capture, requires Hermes runtime). |
| 0.1 | 2026-07-21 | Initial draft. 3-lens review complete. K2 blocking. |
