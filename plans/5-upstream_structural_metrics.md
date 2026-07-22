# Plan 5 — Upstream PR: Structural Metrics for Asymmetric Traces

Status: **DRAFT** — awaiting Phase 0 results before submitting
Target: WillChow66/CTA (origin)
Parent: [3: plans/3-upstream_hermes_adapter.md]
Depends on: Plan 3 (uses CTA Trace data model)

---

## Summary

CTA's Module 3 (TraceAligner) uses DTW alignment, which is semantically dubious
when treatment traces are ~5 events and baseline traces are ~50. Delegation skills
produce extreme asymmetry: one `terminal(qodercli -p ...)` call replaces 16 manual
file writes. DTW warps these into meaningless correspondence.

This PR adds structural comparison metrics that capture the real signal without
requiring symmetric traces.

---

## Files

| File | Purpose |
|------|---------|
| `src/cta/structural_metrics.py` | Event count ratio, tool vocabulary entropy, write compression, unilateral actions |

---

## Metrics provided

| Metric | What it captures |
|--------|-----------------|
| `event_count_ratio` | Treatment/Baseline event count (delegation collapse) |
| `tool_vocabulary_entropy` | Shannon entropy of tool type distribution per trace |
| `entropy_ratio` | T/B entropy (skill narrows or broadens tool usage?) |
| `write_compression` | Baseline writes / Treatment writes (the headline metric) |
| `unilateral_actions` | Actions present in one trace but not the other |

---

## Key design decisions

1. **Complements DTW, doesn't replace it**: For symmetric traces (both conditions
   do similar work), DTW remains appropriate. Structural metrics are for the
   delegation case where asymmetry is the signal.

2. **No alignment required**: Metrics operate on raw event counts and type
   distributions. No O(n²) cross-trace comparison.

3. **General**: Works for any skill that collapses granular operations into
   delegation calls (code generation, API orchestration, infra provisioning).

---

## Scope boundary

- Pure metrics module: no detection, no hypothesis testing
- Does NOT include the audit runner or config schema
- Does NOT include qodercli-specific thresholds

---

## Pre-submission checklist

- [ ] Plan 3 merged (Trace data model dependency)
- [ ] Unit tests with synthetic asymmetric traces
- [ ] Demonstrate on non-qodercli delegation (e.g., delegate_task in origin's data)
- [ ] Document when to use structural metrics vs DTW
