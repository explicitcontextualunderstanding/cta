# Plan 6 — Upstream PR: Config-Driven Audit Runner

Status: **READY TO SUBMIT** — fourth in upstream chain (3 → 5 → 4 → 6)
Target: WillChow66/CTA (origin)
Parent: [3: plans/3-upstream_hermes_adapter.md, 5: plans/5-upstream_structural_metrics.md]
Depends on: Plans 3 + 5 merged (adapter + metrics)
Gate dissolved: Phase 0 (N≥10) replaced by early-stopping justification.
Plan 9 note: Infrastructure PR — Plan 9 labels do not gate submission.

---

## Summary

The origin repo's pipeline (`CTAPipeline.run_full_analysis`) runs all 5 modules
on a single task. There's no config-driven runner that:
- Evaluates pre-registered hypotheses against configurable thresholds
- Dispatches named SIP detectors from a registry
- Validates negative/edge-case controls
- Generates a markdown audit report

This PR adds a generalized audit runner driven by per-skill YAML config.

---

## Files

| File | Purpose |
|------|---------|
| `src/cta/audit_config.py` | YAML/JSON config schema (tool filters, hypotheses, controls, detectors) |
| `scripts/run_audit.py` | Config-driven runner: analyze → hypothesize → detect SIPs → validate controls → report |

---

## Architecture

```
config.yaml (per-skill)
    ├── tool_filters: delegation_call, manual_writes, skill_view, binary_resolution
    ├── hypotheses: H1-H4 with confirm/disconfirm thresholds
    ├── controls: negative (zero delegation), edge_case (zero writes)
    ├── sip_detectors: [list of registered detector names]
    └── report: title, model, design

run_audit.py
    ├── discover_runs(captures_dir) → paired treatment/baseline
    ├── analyze_run(state.db, config) → structural metrics
    ├── evaluate_hypotheses(runs, config) → verdicts
    ├── detect_sips(events, detector_names, context) → findings
    ├── validate_controls(runs, config) → pass/fail
    └── generate_report() → markdown + JSON
```

---

## Key design decisions

1. **Detector registry dispatch**: `DETECTOR_REGISTRY` maps string names to
   functions. `run_detectors()` uses `inspect.signature` to pass context only
   to detectors that accept it. Each detector is isolated (try/except) so one
   failure doesn't crash the pipeline.

2. **Hypothesis evaluation**: Config declares metric + thresholds. Runner computes
   metric from paired runs and returns CONFIRMED/DISCONFIRMED/INCONCLUSIVE.

3. **Control validation**: Negative control (skill should NOT trigger) and edge
   case (read-only task) validate that the metric isn't trivially constructive.
   Vacuous `all([])` guard prevents false passes.

4. **Skill-agnostic**: Config drives all skill-specific behavior. The runner
   itself contains no qodercli logic. Detectors are registered by name.

---

## Generalization required before upstream

Current `run_audit.py` has some qodercli assumptions baked in:
- `delegation_call` filter assumes `terminal` + command_contains pattern
- `manual_writes` list assumes Hermes tool names
- Report format references specific hypothesis names

These need to be fully config-driven (they mostly are, but verify no hardcoding).

---

## Scope boundary

- Framework only: no qodercli detectors in the PR
- Include 1-2 example detectors that are general (e.g., `concept_bleed`)
- Config schema documented with example YAML
- Does NOT include capture harnesses or session data

---

## Pre-submission checklist

- [ ] Plans 3 + 5 merged
- [ ] Remove all qodercli-specific hardcoding from run_audit.py (xurl dry-run proves mostly generic — verify residual)
- [ ] Include example config for a non-qodercli skill (xurl config exists as candidate)
- [ ] Unit tests: config loading, hypothesis evaluation, control validation
- [ ] Detector isolation: verify one crashing detector doesn't break others
- [ ] Document the detector registration interface for contributors
- [x] ~~Phase 0 (N≥10)~~ — dissolved; early-stopping justified
