# Plan 3 — Upstream PR: Hermes Agent Adapter for CTA

Status: **DRAFT** — awaiting Phase 0 results before submitting
Target: WillChow66/CTA (origin)
Parent: [1: plans/1-hermes_cta_fork_plan.md]
Depends on: Phase 0 (N=10 kimi data) for validation evidence

---

## Summary

Extend CTA from Claude-Code-only traces to Hermes Agent sessions. The origin
repo's `module1_parser.py` handles Claude's stream-json `.jsonl` format
(`tool_use` blocks, tool names `bash`/`read`/`write`/`grep`). Hermes emits a
structurally isomorphic but field-incompatible envelope (single-JSON sessions,
OpenAI-shaped `tool_calls[]`, tool names `terminal`/`read_file`/`patch`/...).

This PR adds the translation layer so CTA's 5-module pipeline (segmenter,
aligner, detector, predictor) can operate on any Hermes skill execution.

---

## Files

| File | Purpose |
|------|---------|
| `src/cta/hermes_adapter.py` | Hermes session → CTA Trace (tool vocabulary map, event typing, outcome heuristics) |
| `scripts/validate_g1_plus.py` | Adapter validation (conservation, alternation, vocabulary, CTA mapping) |

---

## Key design decisions

1. **Explicit vocabulary map** (`HERMES_TOOL_MAP`): 24 Hermes tools → CTA EventType.
   Unseen tools fall back to `TOOL_CALL` (never None). Validator flags unmapped usage.

2. **G1+ validation protocol**: 5-check pipeline distinguishes adapter bugs (FAIL)
   from infrastructure failures (SKIP). Degenerate sessions (HTTP 402, 0 assistant
   messages) are excluded from analysis without poisoning aggregate metrics.

3. **Dual input format**: Accepts both session JSON and SQLite `state.db`
   (Hermes's persistent store). SQL query filters `active=1 AND compacted=0`
   to exclude compressed/superseded messages.

4. **Outcome heuristics**: Rule-based error detection (traceback, permission denied,
   command failed) — no trained classifiers (G3-compliant).

---

## Validation evidence (to include in PR)

- 25 sessions validated: 14 PASS, 3 SKIP (degenerate), 0 FAIL
- 11 unique tools observed across all captures: 100% mapped
- Smoke test: container run → state.db → G1+ → trace extraction (21.6s)
- Two models tested: claude-sonnet-4 (Anthropic), kimi-k2.7-code (Moonshot)

---

## Scope boundary

- Does NOT include qodercli-specific detectors (`skill_rules.py`)
- Does NOT include capture harnesses or session data
- Does NOT include config schema or audit runner (separate PR)
- Pure structural translation: no SIP detection, no hypothesis testing

---

## Pre-submission checklist

- [ ] Phase 0 complete (N≥10 per condition)
- [ ] All sessions pass G1+ (or SKIP with documented cause)
- [ ] Adapter handles both Claude-origin and Hermes-origin traces in same pipeline
- [ ] Unit tests for `hermes_session_to_trace` and `evaluate_gate`
- [ ] PR body explains the Claude→Hermes format difference and why this extends CTA's scope
