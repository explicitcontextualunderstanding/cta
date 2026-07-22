# Plan 8 — Runtime Friction Detection

Status: **DRAFT** — pending 3-lens review gates
Version: 0.1 (2026-07-21)
Parent:
  - 7: plans/7-subagent_progress_observation.md (NDJSON wire protocol substrate)
  - 2: plans/2-cta_verification_layer_plan.md (Phase 6 bimodal CPI finding)
Related:
  - 1: plans/1-hermes_cta_fork_plan.md (G3 evidence gap → G7 proposed)

---

## §0 CURRENT STATE

| Field | Value |
|---|---|
| Status | **DRAFT** |
| Research question | Can we classify the environment regime (clean vs friction) at runtime from the NDJSON stream? |
| Substrate | `_format_ndjson_progress()` in `hermes-agent/tools/process_registry.py:90-171` |
| Motivation | Plan 2 Phase 6: CPI is bimodal (0.912 friction / 1.594 clean). Regime is currently discoverable only in post-hoc trace analysis. |
| Deliverable | Friction index in `process()` poll output that discriminates clean from friction-heavy sessions at runtime |
| Blocker | None (design-only; implementation is post-merge) |

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
| S1 | Error rate | `user` → `tool_result` blocks | `error_count / tool_result_count` over last 50 events | G3 run 1: Flask import errors, werkzeug failures. Run 2: zero errors. |
| S2 | Context velocity | `assistant` → `usage.context_usage_ratio` | `(ratio_last - ratio_first) / event_span` | Friction sessions burn context on remediation loops. Clean sessions grow linearly. |
| S3 | Retry density | `assistant` → `tool_use` blocks | `max(Counter(signatures)) / total_calls` where signature = `tool:key_input[:80]` | Same command retried 3+ times = stuck loop. G3 run 1 had repeated pip install attempts. |
| S4 | Context fullness | `assistant` → `usage.context_usage_ratio` (latest) | `ratio > 0.85` → binary flag | Approaching context limit = session is in trouble regardless of other signals. |

### 3.2 Friction index

```
friction_index = w1 * error_rate + w2 * ctx_velocity_norm + w3 * retry_density
```

Initial weights (equal): w1=w2=w3=1/3. Weights are calibrated in Phase 2 against
labeled data, not tuned to fit.

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

### 3.4 Sketch

```python
# --- Inside _format_ndjson_progress(), after existing event loop ---

# Signal 1: Error rate
error_rate = error_count / max(tool_result_count, 1)

# Signal 2: Context velocity
ctx_velocity = 0.0
if len(context_ratios) >= 3:
    first_idx, first_ratio = context_ratios[0]
    last_idx, last_ratio = context_ratios[-1]
    span = last_idx - first_idx
    if span > 0:
        ctx_velocity = (last_ratio - first_ratio) / span

# Signal 3: Retry density
sig_counts = Counter(tool_call_signatures)
retry_density = max(sig_counts.values(), default=0) / max(len(tool_call_signatures), 1)

# Composite
friction_index = (error_rate + min(ctx_velocity / 0.02, 1.0) + retry_density) / 3

# Display
if friction_index >= 0.40:
    signals = []
    if error_rate > 0.3:
        signals.append(f"HIGH-ERROR ({error_count}/{tool_result_count})")
    if ctx_velocity > 0.02:
        signals.append(f"CTX-VELOCITY +{ctx_velocity:.1%}/ev")
    if retry_density > 0.3:
        signals.append(f"RETRY {worst_tool} x{worst_count}")
    if context_ratios and context_ratios[-1][1] > 0.85:
        signals.append(f"CTX-FULL {context_ratios[-1][1]:.0%}")
    parts.append(f"⚠ Friction: {' | '.join(signals)}")
elif friction_index >= 0.15:
    parts.append(f"errors: {error_count}/{tool_result_count}")
```

---

## §4 VALIDATION PROTOCOL

### Phase 1: Retrospective labeling (no new code)

Score existing captures against the friction index formula:

| Capture | Known CPI | Known regime | Expected friction_index |
|---------|-----------|--------------|------------------------|
| G3 run 1 (P1-interactive-kimi-ndjson-treatment-1) | 0.912 | friction | ≥0.40 |
| G3 run 2 (P1-interactive-kimi-ndjson-treatment-2) | 1.594 | clean | <0.15 |
| G3 run 3 (pending) | ? | ? | ? |
| P7-ndjson-treatment-{1,2,3} | N/A (short tasks) | clean (expected) | <0.15 |
| M3 baselines (B1-B4, B6-B8) | varies | mixed | calibrate |

**Gate:** Friction index must separate run 1 from run 2 by ≥0.25 absolute.
If the gap is <0.25, the signals don't discriminate and H8 is in trouble.

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
| A2 | **Error pattern list is fragile.** Hardcoded strings ("Traceback", "Error:") will miss novel error formats and false-positive on benign output containing those strings. | MEDIUM | Accept for v0.1. Phase 2 disagreement analysis (E5) will surface false positives/negatives. If error_rate is the weak signal, drop S1 and rely on S2+S3. |
| A3 | **context_usage_ratio may not be in the stream.** The sketch assumes `usage.context_usage_ratio` is present in assistant events. If qodercli doesn't emit it, S2 and S4 are dead. | HIGH | **Must verify empirically** before Phase 1. Check existing captures for `usage` field presence. If absent, Plan 8 reduces to S1+S3 only, and the friction index formula changes. |
| A4 | **50-event window is too short for velocity.** If sessions are >50 events, the window sees only recent history. A session that was friction-heavy early but recovered looks clean. | MEDIUM | Acceptable. The poll output is a *current state* indicator, not a session summary. Hermes sees the friction warning in real-time; if it clears, the session recovered. That's correct behavior. |
| A5 | **No ground truth for "friction" independent of CPI.** The plan validates against CPI labels, but CPI is itself a proxy. A session could have CPI<1.0 for reasons unrelated to environment friction (e.g., genuinely complex task). | MEDIUM | Acknowledged. E5 (disagreement analysis) exists precisely for this. If friction_index says "clean" but CPI says "friction", the session is complex-but-clean — a third regime the binary model misses. Document as limitation. |

**Gate status:** A1 and A3 are HIGH. A1 is addressed by design (Phase 2 is prospective). A3 requires empirical verification before Phase 1 can proceed — added as Phase 0 prerequisite below.

### 6.2 Karpathy Assumption Audit

| # | Hidden assumption | Reality check | Invalidation criterion | Status |
|---|-------------------|---------------|----------------------|--------|
| K1 | NDJSON `user` events contain `tool_result` blocks with readable error text | Verified in Plan 7 captures (treatment-{1,2,3} show tool_result in user messages) | If G3 run 1 (92 msgs) shows tool_result truncated or absent | **VERIFY IN PHASE 0** — run 1 is on disk, this is a task not an assumption |
| K2 | `context_usage_ratio` is emitted in assistant events | **UNVERIFIED.** Plan 7 captures are short (14-24s). Long sessions may or may not include usage metadata. | See K2 decomposition below | **BLOCKING** — verify before Phase 1 |
| K3 | Error patterns are distinguishable from benign output by string matching | Flask tracebacks are obvious. But "Error:" appears in benign contexts (e.g., grep for "Error" in source code). | If false positive rate > 30% on clean sessions | UNVERIFIED |
| K4 | Retry = same tool + same input repeated 3+ times | Agent may retry with *slightly different* inputs (e.g., different pip flags). Signature-based detection misses these. | If G3 run 1 retries use varied inputs | **VERIFY IN PHASE 0** — check run 1 trace, this is a task not an assumption |
| K5 | 50-event window captures enough signal | G3 run 1 is 92 messages. The last 50 events may be the *recovery* phase, not the friction phase. | If friction_index computed on last-50 of run 1 < 0.25 | UNVERIFIED — compute on actual data. Note: Phase 1 (retrospective) can use full stream; window constraint applies only to Phase 3 (runtime). |
| K6 | Clean sessions stay clean | A session can start clean, hit friction at event 60, and the 50-window catches it. But a session that hits friction at event 10 and recovers by event 40 looks clean at event 90. | If Hermes needs *historical* friction, not just current | Accept by design — poll is current-state. Mitigation: add cumulative error_count to session object so Hermes can query lifetime friction even after window clears. |

**K2 decomposition (blocking):**

| Sub-case | Condition | Consequence | Pre-committed action |
|----------|-----------|-------------|---------------------|
| K2a | `usage` object present, `context_usage_ratio` field present, emitted every assistant event | Full plan proceeds (S1-S4) | — |
| K2b | `usage` present but field named differently or emitted sparsely (e.g., every Nth event) | S2 velocity computation unreliable on sparse data; S4 may survive | Adapt: use field if present under any name; drop S2 if sparse, keep S4. Friction index = (S1 + S3 + S4) / 3. H8 threshold unchanged (80%). |
| K2c | `usage` object absent entirely | S2 and S4 dead. Only S1 (error rate) + S3 (retry density) survive. | **H8 threshold drops to 70%.** Pre-committed before data: 2 signals are weaker than 4, and we will not tune the bar post-hoc. If 70% is not met, H8 REJECTED. |

**Pre-commitment:** The threshold adjustment in K2c is declared NOW, before Phase 0
verification. If K2c obtains and the plan later "needs" 80% to feel credible, that is
p-hacking. The 70% bar is the honest floor for a 2-signal classifier. Below 70%,
the NDJSON stream simply doesn't carry enough friction information.

**Phase 0 verification tasks (K1, K2, K4):**
1. Parse G3 run 1 state.db NDJSON log: check `user` events for `tool_result` presence and completeness (K1)
2. Parse G3 run 1/2 assistant events: check for `usage` object and `context_usage_ratio` field (K2)
3. Extract G3 run 1 retry sequences: check whether repeated tool calls use identical or varied inputs (K4)

### 6.3 RCF Forecast (Reference Class Forecasting)

**Reference class:** Plans 3-7 in this repo (implementation plans with empirical validation).

| Plan | Estimated effort | Actual effort | Ratio |
|------|-----------------|---------------|-------|
| Plan 7 (NDJSON integration) | "purely transport bridging" | 7 versions, 3 evidence gaps, H6 reclassification | ~5x |
| Plan 2 Phase 6 (CPI re-measurement) | "~30 min, no new code" | Multi-day, 3 runs, bimodal surprise, reclassification | ~4x |
| Plan 5 (structural metrics) | 2 phases | 3 phases + false_success detector | ~1.5x |

**Mean overrun:** ~3.5x on plans involving empirical validation.

**Plan 8 estimate (naive):** Phase 1 (retrospective) = 1 hour. Phase 2 (prospective) = 2 hours. Phase 3 (integration) = 1 hour. Total = 4 hours.

**RCF-adjusted:** 4h × 3.5 = **14 hours** realistic. Buffer for:
- K2 verification failure → redesign (adds 2-4h)
- Phase 2 disagreement analysis revealing a third regime (adds 2-3h)
- Error pattern tuning (adds 1-2h)

**Effort gate:** If Phase 1 retrospective separation (E1) is <0.25, ABANDON
immediately. Do not proceed to Phase 2 on hope. Sunk cost is 1 hour.

---

## §7 EXECUTION ORDER

| Phase | Task | Depends on | Gate |
|-------|------|-----------|------|
| 0 | **Verify K2:** Check if `context_usage_ratio` exists in G3 run 1/2 NDJSON logs | G3 run 3 complete | Field present → proceed. Absent → redesign around S1+S3. |
| 1 | **Retrospective scoring:** Compute friction_index on existing captures (run 1, run 2, P7 treatments, M3 baselines) | Phase 0 | E1: separation ≥0.25. If <0.25 → ABANDON. |
| 2 | **Prospective validation:** Run N≥6 sessions with friction logging, compute agreement | Phase 1 pass | E2: agreement ≥80%. If <80% → analyze disagreements, revise signals or REJECT H8. |
| 3 | **Integration:** Wire into `_format_ndjson_progress()`, verify E3/E4 overhead constraints | Phase 2 pass | E3+E4 pass. Deploy to fork. |

**Temporal constraint:** Phase 0 cannot begin until G3 run 3 completes (provides
a third labeled data point). Phase 2 requires Hermes runtime (same dependency as
Plan 1 G1).

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
| 0.1 | 2026-07-21 | Initial draft. 3-lens review complete. K2 blocking. |
