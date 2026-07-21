## CTA Skill Audit: qodercli (M2 Counterfactual Evidence)

**Sessions:** 10 | **Design:** Option B lean (5 tasks × 2 conditions, 2-3 runs on positives) | **Model:** anthropic/claude-sonnet-4 via openrouter

### Pre-Registered Hypotheses

| # | Hypothesis | Verdict |
|---|---|---|
| H1 | Delegation Efficiency | **PARTIALLY CONFIRMED** |
| H2 | Pty Stability | **DISCONFIRMED** |
| H3 | Interactive Blockade | **UNTESTABLE (print mode only; deferred to M3)** |
| H4 | Binary Resolution | **CONFIRMED** |

### Structural Comparison (Treatment vs Baseline)

| Task | T msgs | B msgs | T tools | B tools | T writes | B writes | Compression |
|------|--------|--------|---------|---------|----------|----------|-------------|
| E1 | 4 | 4 | 1 | 1 | 0 | 0 | 1.00x |
| N1 | 32 | 38 | 14 | 17 | 1 | 3 | 1.21x |
| P1 | 65 | 4 | 32 | 1 | 3 | 0 | 0.03x |
| P2 | 66 | 113 | 38 | 62 | 2 | 16 | 1.63x |

### Skill Influence Patterns

| SIP | Valence | Count |
|-----|---------|-------|
| DELEGATION_REDIRECT | constructive | 4 |
| PROCEDURAL_SCAFFOLDING | constructive | 4 |
| PTY_OMISSION | destructive | 4 |

### Controls

- N1 (negative control) zero qodercli: **PASS**
- E1 (edge case) zero writes: **PASS**
- Metric not trivially constructive: **PASS**

### Key Findings

1. **Auth enablement is the skill's gatekeeper value.** Baseline finds qodercli but cannot authenticate. The skill's token guidance unlocks delegation.
2. **Write offloading:** Manual file edits drop 5-16x on write-heavy tasks (P2: 16→1-3).
3. **PTY compliance 73%:** Model omits `pty=true` on 4/15 qodercli calls. Print mode works without it (empirically confirmed). Skill language updated.
4. **Permission wall bug:** Discovered in P1-treatment-1. Fixed with `--permission-mode bypass_permissions` in skill examples.
