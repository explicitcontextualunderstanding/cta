# CTA as Grounded Verification Layer for Tool Interface Alignment

**Position:** CTA is the measurement instrument for Tool Interface Alignment (Ren et al. 2026, §6.3.2) — the grounded, non-LLM feedback signal that answers *did this specific non-parametric update help, hurt, or do nothing?*

**Evidence base:** 17+ containerized counterfactual sessions across 2 model families (claude-sonnet-4, kimi-k2.7-code), 5 task types, 4 milestones (M1-M4).

---

## 1. CTA → Survey Taxonomy Mapping

| CTA Component | Survey Section | Role | Evidence |
|---|---|---|---|
| SIP scope rules ("Do NOT use for single-file lookups") | §6.3.1 Dynamic Tool Routing | Routing constraints. CONCEPT_BLEED = misrouting signal. | N1/E1 controls: zero qodercli invocations on out-of-scope tasks. Metric correctly shows zero influence where zero is expected. |
| Counterfactual pairing (treatment vs baseline) | §6.3.2 Tool Interface Alignment | **The measurement instrument.** SIPs are the divergence signal; structural metrics quantify alignment quality. | P2: 8x write compression with skill. P1-interactive: 2.5x message efficiency. Both measured against identical baselines. |
| Baseline generation for new tools | §6.3.3 Autonomous Tool Creation | CTA generates the missing baseline when a tool is first introduced. No prior trace exists → CTA creates one. | qodercli had no usage history. M1-M2 generated the first counterfactual traces. |
| SKILL.md edits driven by CTA findings | §6.1.2 Feedback Refinement | Qualitative Feedback Refinement on the tool's interface prompt. CTA findings → targeted edits → re-measure. | Permission wall fix (v2.0→v2.1): CTA detected PERMISSION_GAP → added `--permission-mode bypass_permissions` → re-measured in M3. |
| Structural metrics (exit codes, event counts, VFS diffs) | §5.3.1 Programmatic Verifiers | Grounded signal replacing LLM self-critique. Non-parametric, reproducible, external to the model. | M4 PTY counterfactual: deterministic exit-code comparison proved print mode PTY-agnostic. No LLM judgment involved. |

### The gap CTA fills

The survey describes feedback loops (§6.1) and tool governance (§6.3) but does not specify how to *measure* whether a scaffolding edit improved the agent. Existing approaches rely on:

- **LLM self-evaluation:** The model judges its own output. Fails when the model cannot distinguish success from failure (see §3 below).
- **Pass-rate on benchmarks:** Silent on *how* the skill influenced behavior. A +0.3pp pass-rate change (Zhou et al.) tells you nothing about mechanism.
- **Human review:** Does not scale. Cannot run on every skill edit in CI.

CTA provides what these cannot:

1. **Counterfactual pairing** — identical conditions, one variable (skill present/absent)
2. **SIP taxonomy** — labeled divergences with valence (constructive/neutral/destructive)
3. **Structural metrics** — compression ratio, entropy, unilateral actions (no LLM judgment)
4. **Pre-registered disconfirmation thresholds** — prevents confirmation bias (H2-original was disconfirmed and reclassified, not buried)

---

## 2. SIP Taxonomy as Alignment Quality Signal

Each SIP category maps to a specific alignment quality dimension. The valence classification is not subjective — it is determined by structural outcome comparison.

| SIP | Valence | Alignment Interpretation | Empirical Basis |
|---|---|---|---|
| PROCEDURAL_SCAFFOLDING | constructive | Successful alignment. Skill's procedure produces structured, efficient behavior. | 5/5 treatment traces: binary resolution → structured delegation. Consistent across both models. |
| DELEGATION_REDIRECT | constructive | Routing success. Skill redirects work to the appropriate tool. | 5/5 treatment: delegation redirected from native `delegate_task` to qodercli. 8x write compression on P2. |
| EDGE_CASE_PROMPTING | constructive | Environmental cheatsheet working. Skill's edge-case guidance prevents exploration waste. | M3: trust dialog resolved in 4 messages (treatment) vs 22 messages (baseline). Skill text directly referenced by model. |
| REDUNDANT_EXPLORATION | neutral | Routing inefficiency (tolerable). Model explores before delegating. | P1-treatment: 65 messages (vs P2's 66). Verification loops add messages but don't cause errors. |
| PTY_OMISSION | neutral (reclassified) | Correct discrimination, not failure. Model omits PTY where it's a no-op. | M4: print mode PTY-agnostic (identical exit codes). 4/4 omissions were print-mode calls. Model behavior is optimal. |
| SURFACE_ANCHORING | destructive | Over-specification / brittle interface. Skill language too rigid for the model's correct behavior. | H2-original disconfirmed: "PTY is mandatory" was over-specified. Model was already discriminating correctly. Skill language scoped to interactive-only. |
| CONCEPT_BLEED | destructive | Routing failure / scope leak. Skill influences behavior where it should not. | 0 detected. N1 (typo fix) and E1 (read-only) show zero qodercli invocations. Scope constraint effective. |
| PERMISSION_GAP | destructive | Interface misalignment. Skill's examples produce a permission wall the model cannot resolve. | P1-treatment-1: qodercli blocked on permission confirmation. Model reported success despite failure. Fixed in v2.1. |
| FALSE_SUCCESS_REPORTING | destructive | Credit-assignment failure. Model claims success; external state disagrees. | P1-treatment-1: model reported "auth implemented" while qodercli had exited with permission error. |

### Valence determination protocol

A SIP's valence is not assigned by intuition. It is determined by:

1. **Structural comparison:** Does the SIP correlate with better/worse external outcomes (exit codes, file diffs, error presence)?
2. **Counterfactual test:** Would the outcome differ without the SIP? (M4 isolated PTY to prove omission was neutral.)
3. **Reclassification is expected:** PTY_OMISSION moved from destructive → neutral when M4 evidence arrived. This is the system working, not a failure.

---

## 3. The Credit-Assignment Argument

### Why LLM self-evaluation fails

The canonical failure mode is **False Success Reporting** (P1-treatment-1):

```
msg 8:  qodercli output: "Permission confirmation required but no interactive handler"
msg 9:  model reports: "Authentication has been implemented across the project"
```

The model received explicit error output and reported success. This is not a rare edge case — it is the *expected* failure mode of LLM self-evaluation. The model's training objective (helpful, coherent responses) conflicts with accurate error reporting. When a tool fails, the model's prior is to report progress, not failure.

**Why this matters for tool governance:** If the feedback signal for "did this skill edit help?" is the model's own assessment, then False Success Reporting corrupts the loop. A skill edit that introduces a permission wall (v2.0's missing `--permission-mode`) would be evaluated as "working" by the model that hit the wall.

### Why grounded counterfactual signals are necessary

CTA's structural metrics are external to the model:

| Signal | Source | Model can corrupt? |
|---|---|---|
| Exit code | Process return value | No |
| File diff | `git diff --stat` on worktree | No |
| Event count | state.db message/tool records | No |
| Error presence | Background buffer / stderr scraping | No |
| Wall time | Process timing | No |

These signals detected the permission wall that the model's self-report concealed. The CTA audit found PERMISSION_GAP because it compared the model's *claimed* outcome against the *actual* process state — not because it asked the model "did that work?"

### The credit-assignment chain

```
Skill edit (v2.0 → v2.1)
  → Counterfactual capture (treatment vs baseline, identical conditions)
    → Structural metric comparison (external to model)
      → SIP detection (labeled divergence with valence)
        → Accept/reject the edit
```

At no point does the model evaluate itself. The model *acts*; CTA *measures*. This separation is what makes CTA a grounded verification layer rather than another LLM judge.

---

## 4. Worked Example: The Full Σ_t Cycle

The qodercli skill's lifecycle demonstrates one complete iteration of the survey's Σ_t feedback loop (Ren et al. §6.1):

### Stage 1: Initial deployment (v2.0)

Skill v2.0 deployed with:
- Print-mode examples lacking `--permission-mode bypass_permissions`
- Universal PTY requirement ("PTY is mandatory")
- Timeout examples at 180s
- No error recovery guidance
- No partial-completion handling

### Stage 2: CTA audit (M1-M4, 15 sessions)

Counterfactual captures revealed:

| Finding | SIP | Evidence |
|---|---|---|
| Permission wall blocks delegation | PERMISSION_GAP | P1-treatment-1: exit with permission error, model reports success |
| PTY requirement over-specified | SURFACE_ANCHORING | 4/15 calls omit PTY and succeed (print mode). M4: PTY-agnostic. |
| Trust dialog resolvable but costly | EDGE_CASE_PROMPTING | M3: 4 messages (treatment) vs 22 messages (baseline) |
| Model reports false success | FALSE_SUCCESS_REPORTING | P1-treatment-1: "implemented" despite error output |

### Stage 3: Feedback refinement (v2.0 → v2.1)

Targeted edits driven by CTA findings:

| Edit | CTA evidence | Survey mapping |
|---|---|---|
| Add `--permission-mode bypass_permissions` to all examples | PERMISSION_GAP (P1-treatment-1) | §6.1.2 Qualitative Feedback Refinement |
| Scope PTY to interactive mode only | SURFACE_ANCHORING + M4 counterfactual | §6.3.1 Routing constraint correction |
| Add error recovery section | FALSE_SUCCESS_REPORTING | §5.3.1 Programmatic verifier guidance |
| Raise timeout 180→300/600s | P2-treatment-1 hit 300s model-set timeout | §6.3.2 Interface parameter alignment |
| Add partial-completion handling | M3: credit limit (402) killed session at msg 59 | §6.1.2 Failure-mode refinement |

### Stage 4: Re-measure (M3 kimi expansion, N=10 per condition)

The v2.1 skill is now being tested in the cross-model expansion:

- **Treatment (v2.1 skill):** Trust dialog resolved in 4 messages. No permission wall. Error recovery guidance available.
- **Baseline (no skill):** Trust dialog resolved in 22 messages. 2.5x total message cost.
- **Cross-model:** Effect holds on kimi-k2.7-code (Moonshot) — not an artifact of claude-sonnet-4's training distribution.

### Stage 5: Accept/reject

H3 CONFIRMED at 2.5x efficiency. The v2.1 edits are accepted. The cycle can repeat: next CTA audit on v2.1 will detect any new SIPs introduced by the edits themselves.

### The counterfactual: what would have shipped without CTA?

Without CTA, v2.0 would have shipped with:
1. A permission wall that blocks all print-mode delegation (discovered only when users hit it)
2. Over-specified PTY guidance that conflicts with the model's correct behavior
3. No error recovery guidance (users discover false-success reporting in production)
4. 180s timeouts that expire mid-delegation on real tasks

CTA caught all four before the skill reached users. The cost: 15 containerized sessions (~$12 API spend). The alternative: user-reported bugs, each requiring a separate investigation cycle.

---

## 5. Implications for Tool Governance

### CTA as CI gate

The Σ_t cycle can be automated:

```
skill edit committed
  → CTA harness triggered (CI)
    → N=3 counterfactual captures (treatment vs baseline)
      → Structural metric comparison
        → SIP detection
          → PASS: no destructive SIPs → merge
          → FAIL: destructive SIP detected → block + report
```

This requires:
- Containerized isolation (zero-state-pollution between runs) — already implemented
- Structural metrics as standalone scorer — `src/cta/structural_metrics.py` exists
- SIP detectors as pluggable rules — partially implemented
- Pre-registered pass/fail thresholds — prevents post-hoc rationalization

### What CTA does not replace

CTA measures *alignment quality* — whether the skill's interface produces the intended behavior. It does not replace:

- **Functional testing** (does the tool work at all?)
- **Safety evaluation** (does the tool cause harm?)
- **User experience research** (is the tool pleasant to use?)

CTA's scope is the gap between "the tool exists" and "the tool's interface prompt produces optimal agent behavior." This is precisely the §6.3.2 alignment question.

---

## References

- Ren et al. (2026). "A Survey on Self-Evolving Agents." §5.3.1 (Programmatic Verifiers), §6.1.2 (Feedback Refinement), §6.3.1-6.3.3 (Tool Governance).
- Zhou et al. (arXiv:2605.11946). Counterfactual Trace Auditing framework. Extended here from prompt/playbook skills to delegation skills.
- CTA audit data: `data/m2_captures/`, `data/m3_captures/`, `data/m4_captures/` (17+ sessions, 2 models).
