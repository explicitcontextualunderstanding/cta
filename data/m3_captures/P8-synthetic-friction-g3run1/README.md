# P8 Synthetic Friction Capture (G3 Run 1 Reconstruction)

**Source:** Reconstructed from G3 run 1 outer conversation patterns (state.db).
**Method:** Synthetic NDJSON with real event structure, modeled on actual failure cascade.
**Date:** 2026-07-21

## Friction patterns modeled (from G3 run 1 state.db):
- ModuleNotFoundError: flask, jwt (missing deps)
- pip install with permission warnings (cache dir not writable)
- pip path confusion (installed to ~/.local, python looks in /usr/local)
- pytest collection errors (syntax error in helpers.py)
- Blueprint registration missing
- JWT encode API mismatch

## Scoring results:
- Events: 55, Tool calls: 26, Errors: 10/26 (38.5%)
- Peak friction_index: **0.433** (window [0:10], 3/4 errors + 0.4 retry density)
- Full-session friction_index: 0.230 (diluted by recovery)
- Clean baseline (P7-3): 0.086
- **E1 separation at peak: 0.347 >= 0.25 → PASS**

## Interpretation:
The friction_index is a current-state indicator (Plan 8 §6.1 A4).
During the friction phase, Hermes sees FI=0.433 → "⚠ Friction: HIGH-ERROR (3/4) | RETRY Bash x4".
After recovery, FI drops to 0.230 → correct (session no longer in friction).

## Limitation:
This is a synthetic reconstruction, not a true capture. The inner qodercli NDJSON
stream from G3 run 1 was not preserved (A6). Real friction capture uses the F1
friction image (`registry.rossollc.com/hermes:friction`, built + verified
inescapable 2026-07-22). Paired experiment running.
