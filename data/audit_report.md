## CTA Skill Audit: qodercli — Full Report

**Last updated:** 2026-07-21
**Sessions:** 23 total (10 print-mode m2 + 13 interactive m3) | **Design:** Option B lean | **Models:** claude-sonnet-4, kimi-k2.7-code

---

### Evaluation Pipeline Status (Plan 2)

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 0: Data collection | **IN PROGRESS** | 11 kimi sessions pending (host reboot blocker). 13/24 kimi sessions captured. |
| Phase 2b: YAML config | **COMPLETE** | `configs/qodercli.yaml` + `audit_config.py` loader |
| Phase 2d: False Success detector | **COMPLETE** | Recovery-aware, delegation-scoped, 0 false positives on 23 sessions |
| Phase 3A: Structural Scorer | **COMPLETE** | `src/cta/structural_scorer.py` — CLI with single-pair + `--pair-by-task` batch |
| Phase 3B: False Success | **COMPLETE** | `src/cta/skill_rules.py` — integrated into `run_audit.py` via registry |
| Phase 3C: Context Preservation | **COMPLETE** | `src/cta/context_preservation.py` — CPI scorer, chars/4 estimation |
| Phase 3D: Preflight Validator | **COMPLETE** | `src/cta/preflight.py` — 5 checks, wired as pre-capture gate |
| Phase 3E: Control Generator | **COMPLETE** | `src/cta/control_generator.py` — SKILL.md scope → YAML skeleton |
| Phase 4: Cross-model writeup | **BLOCKED** | Awaiting Phase 0 completion |
| Phase 5: Loop closure | **BLOCKED** | Awaiting Phase 4 |

All Phase 3 modules run as `python -m cta.<module>` with `PYTHONPATH=src`.

---

### Pre-Registered Hypotheses

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Delegation Efficiency | **PARTIALLY CONFIRMED** | 8x write compression (P2 print). Interactive: 0.55x (treatment worse due to stuck sessions). |
| H2 | PTY Stability | **RECLASSIFIED → H2-revised CONFIRMED** | Print mode PTY-agnostic (M4). Interactive: 100% compliance. |
| H3 | Interactive Blockade Resolution | **CONFIRMED (revised)** | Trust dialog resolved in both conditions. Skill provides orientation speedup (1.3 msgs), not enablement. |
| H4 | Binary Resolution | **CONFIRMED** | 6/6 treatment traces show `which -a qodercli`. |

---

### Structural Comparison

**Print mode (m2, claude-sonnet-4, N=10):**

| Task | T msgs | B msgs | T tools | B tools | T writes | B writes | Compression |
|------|--------|--------|---------|---------|----------|----------|-------------|
| P2 (migration) | 66 | 113 | 38 | 62 | 2 | 16 | **8x** |
| N1 (typo) | 32 | 38 | 14 | 17 | 1 | 3 | 3x |
| E1 (read) | 4 | 4 | 1 | 1 | 0 | 0 | — |

**Interactive mode (m3, kimi-k2.7-code, N=5T + N=4B preliminary):**

| Task | T msgs | B msgs | T tools | B tools | T writes | B writes | Compression |
|------|--------|--------|---------|---------|----------|----------|-------------|
| P1-interactive | 107 | 59 | 58 | 32 | 0 | 1 | 0.55x |

Treatment interactive is bimodal: 60% clean (1.4x efficiency), 40% stuck (2-3x worse).

---

### Skill Influence Patterns (9-detector registry)

| SIP | Valence | Count | Detector |
|-----|---------|-------|----------|
| PROCEDURAL_SCAFFOLDING | constructive | 6 | `procedural_scaffolding` |
| DELEGATION_REDIRECT | constructive | 6 | `delegation_redirect` |
| PTY_OMISSION | neutral | 6 | `pty_omission` |
| FALSE_SUCCESS | destructive | 0 | `false_success` (0 findings — no actual false success in dataset) |
| CONCEPT_BLEED | — | 0 | `concept_bleed` |
| INTERACTIVE_BLOCKADE | — | 0 | `interactive_blockade` |
| VAGUE_PROMPT_DRAIN | — | 0 | `vague_prompt` |
| SECRET_EXPOSURE | — | 0 | `secret_exposure` |
| FORBIDDEN_FLAG_USAGE | — | 0 | `forbidden_flag_usage` |

**False Success detector (Phase 2d/3B):** Recovery-aware design with three gates:
1. Delegation-scoped errors only (qodercli invocations + permission/auth/credit/network patterns)
2. Acknowledgment check (model mentions failure → not false success)
3. Verification recovery (model runs tests/git-diff after error → legitimate success)

Excludes exit_code 124 (timeout) as ambiguous. Skips skill_view JSON content. Validated: 9 synthetic tests, 0 false positives on 23 real sessions.

---

### Controls

- N1 Zero Delegation: **PASS** (0 qodercli invocations on typo task)
- E1 Zero Writes: **PASS** (0 WRITE events on read-only task)
- Metric Not Trivially Constructive: **PASS**

---

### Reproducibility

```bash
# Full audit (no API keys needed)
PYTHONPATH=src python scripts/run_audit.py --config configs/qodercli.yaml --captures-dir data/m3_captures

# Individual eval modules
PYTHONPATH=src python -m cta.structural_scorer --pair-by-task data/m3_captures
PYTHONPATH=src python -m cta.context_preservation --pair-by-task data/m3_captures
PYTHONPATH=src python -m cta.preflight data/m3_captures/P1-interactive-kimi-treatment-1/state.db
PYTHONPATH=src python -m cta.control_generator ~/.hermes/skills/autonomous-ai-agents/qodercli/SKILL.md
```
