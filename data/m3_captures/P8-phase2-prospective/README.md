# P8 Phase 2: Prospective Validation

**Date:** 2026-07-21
**N:** 9 sessions (6 new + 2 P7 existing + 1 synthetic friction)

## H8 Verdict: CONFIRMED (100% agreement, threshold ≥80%)

| Session | Events | Turns | Calls | Errors | FI | FI-label | CPI | CPI-label | Agree |
|---------|--------|-------|-------|--------|-----|----------|-----|-----------|-------|
| P8-S1 (count files) | 16 | 4 | 3 | 0 | 0.114 | CLEAN | 3.00 | clean | ✓ |
| P8-S2 (add function) | 20 | 5 | 4 | 0 | 0.087 | CLEAN | 3.00 | clean | ✓ |
| P8-S3 (fix tests) | 30 | 8 | 8 | 1 | 0.090 | CLEAN | 2.40 | clean | ✓ |
| P8-S4 (add endpoint) | 17 | 4 | 3 | 0 | 0.121 | CLEAN | 1.55 | clean | ✓ |
| P8-S5 (run tests) | 19 | 5 | 4 | 0 | 0.089 | CLEAN | 3.00 | clean | ✓ |
| P8-S6 (refactor) | 21 | 5 | 4 | 0 | 0.089 | CLEAN | 2.62 | clean | ✓ |
| P7-T2 (existing) | 17 | 4 | 3 | 0 | 0.113 | CLEAN | 3.00 | clean | ✓ |
| P7-T3 (existing) | 20 | 5 | 4 | 0 | 0.086 | CLEAN | 3.00 | clean | ✓ |
| P8-SYNTH (friction) | 55 | 30 | 26 | 10 | 0.433 | FRICTION | 0.70 | friction | ✓ |

## Limitations

- 8/9 sessions are clean (only 1 friction, synthetic)
- Real friction sessions require Docker (F1/F3 configs) — Docker unavailable
- CPI proxy is simplified: (success_rate * expected_growth / actual_growth)
- No disagreement cases to analyze (E5 trivially satisfied)

## Interpretation

The friction_index has zero false positives on clean sessions (N=8).
Clean sessions score 0.086-0.121 (well below 0.15 threshold).
The friction session scores 0.433 (well above 0.40 threshold).
The gap between clean max (0.121) and friction (0.433) is 0.312 — clear separation.

## E5 (Disagreement Analysis)

No disagreements observed. All sessions classified correctly by both methods.
