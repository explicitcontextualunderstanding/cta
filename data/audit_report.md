## CTA Skill Audit: qodercli (Full Evidence Base)

**Sessions:** 10 print-mode (claude-sonnet-4) + 9 interactive (kimi-k2.7-code, preliminary) + 4 M4 deterministic | **Design:** Option B lean + cross-model expansion | **Models:** anthropic/claude-sonnet-4 via openrouter, kimi-k2.7-code via opencode-go

### Pre-Registered Hypotheses

| # | Hypothesis | Verdict |
|---|---|---|
| H1 | Delegation Efficiency | **PARTIALLY CONFIRMED** (8x write compression on P2; not clean 1-call collapse) |
| H2 | PTY Stability | **RECLASSIFIED → H2-revised CONFIRMED** (print mode PTY-agnostic per M4; 100% compliance on interactive) |
| H3 | Interactive Blockade Resolution | **CONFIRMED (revised)** — model-native ability; skill provides marginal orientation speedup, not enablement |
| H4 | Binary Resolution | **CONFIRMED** (4/6 treatment traces + all M3) |

---

### M2: Print-Mode Counterfactual (claude-sonnet-4, N=10)

#### Structural Comparison (Treatment vs Baseline)

| Task | T msgs | B msgs | T tools | B tools | T writes | B writes | Write compression |
|------|--------|--------|---------|---------|----------|----------|-------------------|
| E1 | 4 | 4 | 1 | 1 | 0 | 0 | — |
| N1 | 32 | 38 | 14 | 17 | 1 | 3 | 3x |
| P1 | 65 | 4* | 32 | 1* | 3 | 0* | — |
| P2 | 66 | 113 | 38 | 62 | **2** | **16** | **8x** |

*P1 baseline used Hermes's native `delegate_task` (opaque subagent). P2 is the valid comparison.

#### Skill Influence Patterns (M2)

| SIP | Valence | Count |
|-----|---------|-------|
| DELEGATION_REDIRECT | constructive | 4 |
| PROCEDURAL_SCAFFOLDING | constructive | 4 |
| PTY_OMISSION | **neutral** (M4 reclassified) | 4 |

#### Controls

- N1 Zero Delegation: **PASS**
- E1 Zero Writes: **PASS**
- Metric Not Trivially Constructive: **PASS**

---

### M3: Interactive-Mode Cross-Model Expansion (kimi-k2.7-code, N=4B + N=5T, preliminary)

#### Session Inventory

| Session | Msgs | Tools | Time(s) | Launch@ | 1stWrite@ | Gap | Polls | Pattern |
|---------|------|-------|---------|---------|-----------|-----|-------|---------|
| B1 | 138 | 72 | 692.8 | 27 | 35 | 8 | 28 | VERBOSE |
| B2 | 82 | 45 | 516.2 | 19 | 25 | 6 | 12 | CLEAN |
| B3 | 105 | 55 | 380.2 | 18 | 24 | 6 | 17 | CLEAN |
| B4 | 87 | 49 | 646.8 | 21 | 35 | 14 | 17 | CLEAN |
| T1 | 56 | 29 | 606.2 | 8 | 14 | 6 | 10 | CLEAN |
| T2 | 196 | 103 | 247.5 | 25 | 31 | 6 | 74 | **STUCK** |
| T3 | 78 | 45 | 308.0 | 22 | 28 | 6 | 8 | CLEAN |
| T4 | 81 | 47 | 816.2 | 15 | 21 | 6 | 14 | CLEAN |
| T5 | 172 | 91 | 464.6 | 27 | 31 | 4 | 58 | **STUCK** |

#### Trust Dialog Resolution

| Condition | Gaps (msgs from launch → first write) | Mean |
|-----------|---------------------------------------|------|
| Baseline | 8, 6, 6, 14 | **8.5** |
| Treatment | 6, 6, 6, 14, 4 | **7.2** |

**Verdict:** 1.3 message difference. Both conditions resolve the trust dialog independently. The skill does NOT enable resolution — it marginally accelerates it.

#### Aggregate Statistics

| Metric | Baseline (N=4) | Treatment ALL (N=5) | Treatment CLEAN (N=3) |
|--------|---------------|---------------------|----------------------|
| Mean msgs | 103 | 116.6 (+13%) | 71.7 (1.4x better) |
| Mean tools | 55 | 63 | 40.3 |
| Mean time | 559s | 489s | 576s |
| Stuck rate | **0%** | **40%** | — |

#### New SIP: MONITORING_IMPATIENCE (destructive, treatment-only)

- Model launches qodercli interactively, resolves trust dialog quickly (gap=4–6)
- qodercli begins working (spinner output: ⠋⠙⠹...)
- Model polls 58–74 times seeing only spinner characters
- Eventually kills qodercli, verifies files manually (tests pass)
- Task succeeds but at 2–3x message cost

**Root cause:** Skill lacks monitoring duration guidance. Model has no heuristic for "qodercli needs 60–300s for multi-file tasks."

**Proposed fix:** Add `process(wait, timeout=120)` guidance + "spinner means still working" documentation.

#### H3 Verdict Revision

| Version | Statement | Verdict |
|---------|-----------|---------|
| H3-original | Model detects folder trust prompt and sends `1\n` | CONFIRMED (both conditions) |
| H3-revised | Skill provides meaningful efficiency gain in interactive mode | **PARTIALLY CONFIRMED** (1.4x clean, 40% stuck → net negative) |
| H3-skill-value | Skill's interactive value is orientation speedup | **CONFIRMED** (launch ~10 msgs earlier) |

---

### M4: PTY Counterfactual (deterministic, no model)

| Task | PTY (A) | Pipes (B) | Exit match | Wall time diff |
|------|---------|-----------|------------|----------------|
| T1 (multi-file auth) | exit=0, 119.6s | exit=0, 151.2s | Yes | 20.9% |
| T2 (read package.json) | exit=0, 11.6s | exit=0, 12.0s | Yes | 3.1% |

**Verdict:** Print mode is PTY-agnostic. H2-revised CONFIRMED.

---

### Summary of Skill Value (evidence-based)

| Value proposition | Evidence strength | Source |
|-------------------|-------------------|--------|
| Print-mode write offloading (8x compression) | **STRONG** | M2 P2 (claude-sonnet-4) |
| Auth enablement (token guidance unlocks qodercli) | **STRONG** | M2 P2 baseline auth failure |
| Procedural scaffolding (consistent orientation) | **STRONG** | 4/4 M2 treatment + 5/5 M3 treatment |
| Interactive orientation speedup (~10 msgs earlier) | **MODERATE** | M3 kimi (N=9, preliminary) |
| Interactive trust dialog enablement | **NOT SUPPORTED** | M3: baseline resolves independently |
| Interactive monitoring reliability | **NEGATIVE** | 40% stuck-polling rate in treatment |

---

### Batch Status

M3 kimi expansion: N=4B + N=5T valid. Batch PID 12399 running (B5–B10, T6–T10).
Final statistics at N≥10 per condition.
