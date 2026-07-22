# Plan 9 — Dual-Engine Validation Framework

Status: **DRAFT** — methodology plan (not a feature plan; judged by adoption, not deployment)
Version: 0.4.0 (2026-07-22)
Parent:
  - 8: plans/8-runtime_friction_detection.md (§4.0 Gap 3 pre-registration is the first consumer)
  - 2: plans/2-cta_verification_layer_plan.md (CPI claims need Type S/M backfill)
Related:
  - 1: plans/1-hermes_cta_fork_plan.md (skill-effect claims need inductive labeling)
External reference:
  - compose-pkl/docs/patent/verification/dual-engine-epistemic-chain.html (Rocq → Stan → Gelman)

---

## §0 RESEARCH QUESTION

**What validation discipline must any CTA empirical claim meet before it is
reported as confirmatory evidence?**

This is a methodology plan. Its deliverable is not a feature or a capture — it is
a validation protocol that all other plans consume. It outlives Plan 8 and applies
equally to Plan 2's bimodal CPI, Plan 1's skill-effect claims, and any future CTA
experiment.

**CTA's actual failure mode is construct validity, not statistical power.** Every
real failure this project has hit is an abduction-stage (measurement-instrument)
failure: Run 1's no-fire (instrument didn't produce the construct), ssl-breaks-
hermes, the overlay ImportError, the F1 urllib escape, and now probe run 2's
antecedent-unreachable result (the skill's own mode-selection table defaults to
`-p`, so exit-42 never fires and the prescription is never exercised).
The statistical machinery (Type S/M, hierarchical Bayes) has never failed
CTA because it has never been exercised — N is too small. The plan's center of
gravity must match where failures actually occur.

**Why this exists:** CTA currently reports point estimates (CPI=0.833, WC=8x,
FI separation=0.312) with no uncertainty bounds, no Type S/M analysis, and no
pre-registered reconciliation rules. But the more urgent problem is that CTA's
experiments keep failing to produce the phenomenon they claim to test. Construct
validity — "does the experiment exercise the mechanism?" — is the primary risk.
Statistical insufficiency is the secondary risk that becomes relevant only once
the instrument works.

**The sharpest illustration:** H8's "100% agreement" between friction_index and CPI
labels looks like validation but is co-adaptation. FI uses
error_rate/ctx_velocity/retry_density; CPI uses success_rate/growth — both derived
from the *same NDJSON stream*. Engines sharing an input are not independent
regardless of agreement level; agreement between them is uninformative. We have one
engine talking to itself and calling the echo "confirmation."

**The commitment:** The epistemic chain closes — or the claim dies. A CTA claim
that cannot survive structural detection AND statistical measurement confronting
each other is not evidence. It is a hope. Hopes are fine for generating the next
experiment; they are not fine for closing a plan or shipping a skill.

**Honest framing:** CTA does not have a dual-engine system. compose-pkl's power
comes from genuine independence — Rocq and Stan are different formalisms,
codebases, epistemic foundations, so they can't share a bug. CTA's "deduction"
(skill_rules.py) and "induction" (CPI) are written by the same agents, in the same
codebase, reading the same captures. This plan adopts the *discipline* of
dual-engine validation as an aspiration — the independent-scorer pattern (§6) is
what would make the framing literally true. Until then, CTA has one engine looking
at its own data two ways. That's still valuable cross-checking, but the plan should
not claim more than it delivers.

**What this is NOT:** This is not a plan to install Rocq or run Stan on every
capture. It is a plan to adopt the *epistemic discipline* of the dual-engine chain
at the scale CTA can actually sustain (N=3-10 paired sessions, not N=1000).

---

## §1 THE TWO ENGINES (ASPIRATIONAL DISCIPLINE)

The dual-engine chain separates what you know by **structure** (deduction) from
what you know by **measurement** (induction). CTA conflates these. This plan
separates them — while acknowledging that CTA's "two engines" share a codebase,
a data source, and an author. The separation is a discipline, not a fact. The
independent-scorer pattern (§6) is what would make it a fact.

| Engine | CTA instantiation | Role | Output |
|--------|-------------------|------|--------|
| **Deduction** (structural) | SIP detectors (`skill_rules.py`), `detect_regime_adaptation()`, session classification logic | Proves mechanism presence/absence by trace inspection. Deterministic. Does not need N. | "The skill activated" / "The detector fired" / "The session escaped" |
| **Induction** (statistical) | CPI, ECR, write compression, friction_index, message counts | Estimates effect magnitude from paired sessions. Stochastic. Needs N + uncertainty. | "Treatment CPI > control CPI by β1 (95% CrI: [x, y])" |

**The rule:** Deductive claims don't need N=10. Inductive claims need posterior
distributions, not point estimates. Never let the confidence of one leak into the
other.

### §1.1 Claim labeling (mandatory for all CTA outputs)

Every claim in audit_report.md, pr_writeup.md, and plan exit criteria must be
labeled:

- **[DEDUCTIVE]** — mechanism proof from trace inspection. Example: "Binary
  resolution occurs in 6/6 treatment traces" (H4). No statistical uncertainty
  applies; the claim is about presence, not magnitude.
- **[INDUCTIVE]** — statistical estimate from paired measurement. Example: "Mean
  CPI = 0.833" or "Write compression = 8x." Requires N, CI, and Type S/M.
- **[EXPLORATORY]** — inductive claim with N < minimum. Example: any single-pair
  observation. Cannot close a hypothesis; generates the next one.

**Mixed claims:** A result can carry multiple labels for its components. Example:
the probe run 2 result is **[DEDUCTIVE]** for "exit-42 did not fire; both arms
used `-p` from start" (mechanism fact from trace inspection) AND **[EXPLORATORY]**
for "ΔCPI = +0.056 at N=1" (inductive estimate, non-confirmatory). The decisive
component is deductive; the inductive component is context. Label both:
`[DEDUCTIVE + EXPLORATORY]`. When components disagree, the weaker label governs
the claim's overall status.

### §1.2 Construct validity — does the experiment exercise the mechanism?

**The Gap 3 Run 1 lesson:** The friction prescription (SKILL.md v2.5.1) is
conditional: *if* Hermes sees a qodercli session dying from friction, kill it and
retry with `-p`. In Run 1, the session wasn't dying — the inner agent adapted at
the code level (wrote stdlib `jwt_compat.py` using hmac/hashlib/base64). There was
no friction fire for Hermes to see, so the prescription correctly never fired.

**"Extinguisher didn't activate" ≠ "extinguisher is broken."** It means the
building didn't burn down. The §4.0 outcome table row "both succeed → friction
block is dead weight" conflates two different claims:

| Claim | What it means | Tested in Run 1? |
|-------|--------------|-----------------|
| No fire occurred (prescription not exercised) | The friction was self-healable; the conditional's antecedent was never true | **YES** — this is what happened |
| Extinguisher is inert (prescription doesn't work when needed) | The kill+retry mechanism fails even when friction IS Hermes-visible | **NOT TESTED** |

**The construct-validity problem:** F1 friction (no pip/ssl/flask) is the kind a
capable inner agent silently self-heals at the code level. It never surfaces as
Hermes-visible error tool_results. The prescription targets Hermes-visible friction;
F1 doesn't produce it. We tested the prescription against the wrong friction type —
like testing a headache drug on people without headaches.

**The strategic implication:** A capable inner agent with `--yolo` + full Bash will
absorb most environment friction silently. The friction that DOES surface to Hermes
is either:
- **Invocation-mode friction** (exit-42 pipe conflict) — already proven the
  prescription works here (bgmode test, Phase 3)
- **Genuinely unsolvable friction** — task fails entirely, no recoverable regime

This suggests the prescription's real domain may be narrow: invocation-mode friction,
not environment friction. And that domain is already proven.

**Methodological rule (new):** Before committing to N≥3 replication of an experiment,
run a **construct-validity probe** — one pair designed to guarantee the mechanism's
antecedent is true. If the mechanism still doesn't fire under guaranteed antecedent
conditions, the mechanism is inert and replication is wasted budget. If it fires,
commit to N≥3 with the validated friction type.

**Probe design for Gap 3 (Plan 8 §4.1):** Test the prescription in its proven
domain — invocation-mode friction (exit-42). Hermes launches qodercli in background
mode, which triggers exit-42 on `-i`. Treatment (v2.5.1) has guidance to detect
exit-42 and fall back to `-p`; control (v2.4.0) does not. This is friction the inner
agent CANNOT code around (it's a mode failure, not a missing library), and it
surfaces to Hermes as visible errors regardless of coding skill. The bgmode test
already proved the model *complies* with the guidance; the probe adds the missing
ingredient: a control arm + CPI comparison to show the prescription *improves
outcomes*.

### §1.3 Measurement integrity — the abduction stage

compose-pkl's four-stage loop is Deduction → **Abduction** → Induction →
Confrontation. The Abduction stage (Plan 13, "Dries") is the measurement bridge:
it ensures "data entering the inductive engine is measured, not synthesized."
Plan 9's two-engine model collapses this into Induction, but the concern is
distinct and must be named.

**CTA's abduction stage is the harness + classification pipeline:**
- The harness (`gap3_friction_harness.py`, `m3_interactive_harness.py`) produces
  the NDJSON stream and stdout captures.
- The classification logic (validity gates, escape detection, failure-pattern
  matching) determines which sessions enter the statistical model.
- The metric computation (CPI, FI, ECR) transforms raw events into the numbers
  the hierarchical model consumes.

**The principle:** The NDJSON stream, classification logic, and metric pipeline
are the *measurement instrument*. Their correctness is a prerequisite for the
statistical model. A misclassified session (e.g., an infra_failure labeled
`valid`, or an escaped session not caught) corrupts every downstream inference.
No amount of Bayesian modeling saves you from a broken instrument.

**Minimum integrity checks (before any inductive claim):**
1. Classification logic is deterministic and version-controlled (no manual
   overrides after the fact).
2. Escape detection runs on EVERY session, not a sample.
3. Metric computation is reproducible from raw captures (re-running the scorer
   on the same NDJSON produces identical numbers).
4. The harness writes a `run_metadata.txt` with image digest, timestamp, model
   ID, and skill variant — enabling post-hoc audit.

**Relationship to compose-pkl:** Their Plan 13 ensures μ_γ = 49,054 is measured
from hardware (30-run CI, adaptive seeds, kernel telemetry). CTA's equivalent is:
every CPI/FI value is computed from actual session captures, never estimated or
synthesized. The "territory before map" principle applies: the capture is the
territory; the metric is the map.

---

## §2 TYPE S/M REPORTING (MANDATORY FOR ALL INDUCTIVE CLAIMS)

Adapted from Gelman & Carlin (2014) and compose-pkl's implementation
(Type S=0.0%, Type M=0.857× for α).

| Metric | Definition | CTA application |
|--------|-----------|-----------------|
| **Type S** (sign) | P(estimated sign is wrong \| data) | "Is it possible the skill HURTS rather than helps?" At N=4 with bimodal CPI, Type S may be >10%. |
| **Type M** (magnitude) | E[\|estimate\| / \|true\| \| data, sign correct] | "By how much are we exaggerating?" 8x WC from N=1 likely has Type M > 2.0x. |

**Reporting standard:** Every inductive claim reports:
```
CPI_treatment = 1.42 (posterior median, 95% CrI: [0.89, 2.01])
Type S = 4.2% | Type M = 1.34×
```

Not:
```
CPI_treatment = 1.42
```

**Minimum N for Type S/M computation:** N≥3 paired observations. Below this,
report as [EXPLORATORY] with the caveat "no uncertainty estimate possible at N=1."

---

## §3 BAYESIAN HIERARCHICAL MODEL (STANDARD FOR N≥3)

For any paired CTA experiment with N≥3 valid pairs:

**Full model (N≥5, random effects identifiable):**

```stan
data {
  int<lower=1> N;              // number of pairs
  int<lower=1> K;              // number of distinct tasks
  vector[N] cpi_treatment;
  vector[N] cpi_control;
  int<lower=1,upper=K> task[N]; // task identity (for multi-task designs)
}
parameters {
  real beta0;                   // baseline CPI (control, average task)
  real beta1;                   // treatment effect (the skill_effect)
  real<lower=0> sigma;          // residual SD
  real<lower=0> sigma_pair;     // pair-level SD (environment noise)
  vector[N] u_pair;             // pair random effects
}
model {
  beta0 ~ normal(1.0, 0.5);    // weakly informative: CPI near 1.0 a priori
  beta1 ~ normal(0.0, 1.0);    // skeptical prior: no effect expected
  sigma ~ exponential(1);
  sigma_pair ~ exponential(1);
  u_pair ~ normal(0, sigma_pair);
  for (i in 1:N) {
    cpi_treatment[i] ~ normal(beta0 + beta1 + u_pair[i], sigma);
    cpi_control[i] ~ normal(beta0 + u_pair[i], sigma);
  }
}
```

**Minimal model (N=3-4, fixed-effect pairs):**

At N=3-4, the `u_pair` random effects are unidentifiable (more random effects
than observations per group). Use a fixed-effect pair model instead:

```stan
data {
  int<lower=1> N;              // number of pairs (3 or 4)
  vector[N] cpi_treatment;
  vector[N] cpi_control;
}
parameters {
  real beta0;                   // baseline CPI (control, average pair)
  real beta1;                   // treatment effect (the skill_effect)
  vector[N] alpha_pair;         // pair fixed effects (absorbs environment)
  real<lower=0> sigma;          // residual SD
}
model {
  beta0 ~ normal(1.0, 0.5);
  beta1 ~ normal(0.0, 1.0);    // skeptical prior
  alpha_pair ~ normal(0, 1.0); // weakly regularized
  sigma ~ exponential(1);
  for (i in 1:N) {
    cpi_treatment[i] ~ normal(beta0 + beta1 + alpha_pair[i], sigma);
    cpi_control[i] ~ normal(beta0 + alpha_pair[i], sigma);
  }
}
```

**When to use which:** N=3-4 → minimal model (fixed effects). N≥5 → full model
(random effects). Report which model was used alongside results. The minimal
model's `beta1` is the same quantity of interest (isolated skill_effect); only
the pair-noise modeling differs.

**Key design choices:**
- `u_pair` absorbs environment noise (friction regime is a moderator, Plan 8 §1.1).
  Pairing controls for it; the random effect models residual pair-level variance.
- `beta1` is the isolated `skill_effect` from the decomposition
  `outcome = skill_effect + environment_effect + noise`.
- Skeptical prior on `beta1` (centered at 0) prevents the model from "wanting"
  an effect. The data must overcome the prior.

**Convergence diagnostics (mandatory):**
- R-hat < 1.05 on all parameters
- ESS > 100 (effective sample size)
- 4 chains, 1000 warmup, 1000 sampling (minimum)

**Software:** CmdStan (preferred) or PyMC. If neither is available, report
bootstrap CI (10,000 resamples) as a frequentist approximation, labeled as such.

---

## §4 CIRCUIT BREAKERS / RECONCILIATION RULES (R1–R6)

**Sequential mandatory checkpoint.** Every CTA claim passes through R1→R6 in order
before publication. A claim that trips any breaker is REJECTED at that point — it
does not continue to subsequent rules. This is not advisory; it is a gate.

Adapted from compose-pkl's R1-R5 (which are themselves adapted from the clinical
trial standard) plus R6 (construct validity, added from Gap 3 Run 1).

| Rule | Condition | Action | Rationale |
|------|-----------|--------|-----------|
| **R1 — Convergence mismatch** | Deductive engine proves mechanism (detector fires), inductive engine shows no effect (β1 CrI includes 0) | TRUST mechanism, FLAG prescription. "The skill activates but doesn't help." | Structure is proven; magnitude is not. |
| **R2 — Sign reversal** | Inductive engine shows β1 < 0 with high posterior probability (P(β1<0) > 0.95) | **HARD REJECT.** The skill hurts. Do not ship. | Sign errors are the most dangerous — they mean the intervention is destructive. |
| **R3 — Direction agree, magnitude disagree** | Both engines agree on direction but the magnitude is outside calibrated CI | TRUST direction, FLAG magnitude. Report with wide CI. | Direction agreement = structural insight correct. Magnitude = measurement issue. |
| **R4 — Shared input** | Two metrics derive from the same data source (e.g., FI and CPI both from NDJSON stream) | **Engines sharing an input are NOT independent regardless of agreement level.** Agreement between them is uninformative. Run co-adaptation check (§7) with a held-out signal. | Independence requires different inputs, not just different computations on the same input. |
| **R5 — Blind evaluation** | Acceptance criteria are locked BEFORE data collection | PASS. The evaluator cannot tune thresholds to fit data. | Pre-registration prevents p-hacking and HARKing. |
| **R6 — Construct validity** | The experiment's friction/treatment does not exercise the mechanism's antecedent (e.g., friction is self-healable, never surfaces to the detection layer) | **DO NOT REPLICATE.** The experiment is construct-invalid. Redesign the stimulus before spending N≥3 budget. | Testing a headache drug on people without headaches wastes budget and produces uninformative nulls. |

### §4.1 R5 pre-registration proof mechanism

R5 requires acceptance criteria to be locked before data collection. But "locked"
needs proof, not just assertion. Minimum mechanism:

1. Write the pre-registration (metrics, thresholds, reconciliation rules, validity
   gates) into the plan document.
2. Commit the plan with a descriptive message: `pre-register: Gap 3 analysis
   protocol locked before Run N`.
3. Record the commit hash + timestamp in the plan's §4.0 header:
   `Pre-registered: <commit_hash> (<ISO date>)`.
4. Any results section added AFTER that commit is provably post-registration.

**Honest strength of this guarantee:** At CTA's scale, the same agents design, run,
and analyze — often in one session. The git-commit mechanism proves the text
predated the data, but cannot prevent a later commit from rationalizing "actually
the criterion was Y." R5's real value here is *disciplining the analyst's
attention* — forcing criteria-commitment before seeing data, which curbs
unconscious HARKing. It is NOT a tamper-proof seal. The clinical-trial power of
R5 comes from temporal and social separation (different teams run vs analyze);
CTA lacks that separation. State the guarantee honestly: "pre-registered by
commit hash; honor-system enforcement."

This is CTA's equivalent of compose-pkl's `scripts/pre-register-claim.py` +
FreeTSA timestamps. Less formal, but sufficient for internal pre-registration
at CTA's scale. If CTA ever publishes externally, upgrade to RFC 3161 timestamps.

### §4.2 R6 concrete example — Gap 3 Run 1

**Scenario:** Gap 3 Run 1 completes. Both arms valid. Treatment CPI = 0.477,
control CPI = 0.421. The naive next step: "Run 2 more pairs to reach N≥3."

**R6 check (applied BEFORE replicating):**
- Mechanism's antecedent: "Hermes sees ≥3 consecutive error tool_results from
  qodercli (FI≥0.40), triggering the kill+retry prescription."
- Did the antecedent occur in Run 1? **No.** The inner qodercli wrote stdlib
  `jwt_compat.py`; zero error tool_results surfaced to Hermes. FI never exceeded
  0.15. The prescription's conditional was never evaluated.
- **R6 fires.** The F1 friction environment does not produce the construct
  (Hermes-visible friction) the prescription targets. Replicating this experiment
  2 more times will produce 2 more "no fire" results — confirming a measurement
  artifact, not testing the mechanism.

**R6 verdict:** DO NOT REPLICATE. Redesign the stimulus. → Plan 8 §4.1 probe
(paired bgmode exit-42 experiment) produces genuine Hermes-visible friction that
the inner agent cannot code around. Only after the probe confirms fire does N≥3
replication become justified.

**What R6 prevented:** ~$6-12 in API budget, ~54 minutes of compute, and a
misleading "N=3 null result" that would have been cited as evidence the
prescription is inert — when it was never tested.

**Operating rule:** A claim failing any reconciliation rule is REJECTED regardless
of robustness gate scores. A claim passing reconciliation but failing >1 robustness
gate is DOWNGRADED to "promising — requires replication."

---

## §5 ROBUSTNESS GATES (G1–G8)

Adapted from Kaddour et al. (2023) and compose-pkl's implementation. A
confirmatory CTA claim must pass ≥6 of 8.

| # | Gate | CTA test | Minimum |
|---|------|----------|---------|
| G1 | **Benchmark independence** | Does the effect survive a second model (not just the one tested)? | ≥1 replication model |
| G2 | **Seed independence** | Stable effect across ≥3 independent runs (paired)? | CI on β1 excludes 0 |
| G3 | **Metric independence** | Does the conclusion hold under ≥2 alternative metrics (not just the headline)? | ≥2 of 3 agree on sign |
| G4 | **Ablation honesty** | Does the control isolate exactly one factor? | Single differing variable between arms |
| G5 | **Variance visibility** | Are distributions reported, never bare means? | Mandatory for all inductive claims |
| G6 | **Baseline sanity** | Is the effect meaningful vs a trivial baseline? | Effect > noise floor |
| G7 | **Claim scope** | Are generality claims bounded by evidence breadth? | No over-generalization beyond tested models/tasks/regimes |
| G8 | **Leakage / escape** | Is the test uncontaminated by the treatment leaking into control? | Clean separation verified |

---

## §6 INDEPENDENT-SCORER PATTERN

The strongest defense against co-adaptation (R4) and the substitute for external
replication (which CTA lacks — compose-pkl gap C2/G9).

**Pattern:** Any metric computed by code in `src/cta/` must be verified by a
second computation path that does NOT share the same codebase.

| Metric | Primary scorer | Independent scorer | Agreement criterion |
|--------|---------------|-------------------|---------------------|
| CPI | `cta.context_preservation` | Manual computation from state.db (messages, tokens, success) | Within 5% |
| Friction index | `cta.structural_scorer` / `score_friction.py` | Blind human classification of NDJSON traces | Cohen's κ ≥ 0.7 |
| Write compression | `cta.structural_scorer` (WRITE events) | `git diff --stat` line count ratio | Within 10% |
| SIP detection | `skill_rules.py` detectors | Blind trace reading by second agent | Agreement on valence |

**Blind protocol:** The independent scorer must NOT see the condition label
(treatment/control) or the primary scorer's output before producing its own
classification. This breaks the same-codebase loop.

**Minimum:** At least one metric per plan must have an independent-scorer
verification before the plan's exit criteria are met.

---

## §7 CO-ADAPTATION CHECK (R4 FOLLOW-UP)

When R4 fires (perfect or near-perfect agreement between engines), run:

1. **Held-out signal test:** Classify the same sessions using a signal NOT in the
   primary metric's formula. If the held-out signal also separates conditions, the
   discrimination is real, not an artifact of shared inputs.

2. **Independent scorer (§6):** A second agent or human classifies traces BLIND
   to condition and to the primary metric. Agreement breaks the loop.

3. **Perturbation test:** Add noise to one engine's input (e.g., shuffle 10% of
   tool_result labels). If the metric is robust to perturbation, it's capturing
   real signal. If it collapses, it's overfit to the specific input structure.

**Documentation:** Until at least one co-adaptation check passes, any 100%-agreement
result is labeled "validated within-codebase; independent confirmation pending."

---

## §8 BACKFILL SCHEDULE

Apply this framework retroactively to existing claims. Priority order:

| Priority | Claim | Plan | Current state | Action |
|----------|-------|------|---------------|--------|
| 1 | Gap 3 CPI comparison | Plan 8 §4.0 | Run 1 EXPLORATORY (R6: F1 self-healed). Probe run 2 (m1probe image, exit-42 as only friction): VALID, NO FIRE — antecedent unreachable (skill's mode-selection table defaults to `-p`; neither arm attempted `-i`). | **CLOSED via option 3 (scope reduction).** R6 fires: do not replicate. Prescription arm untestable under current skill design. Instrument arm (H8) stands independently. SKILL.md v2.5.2 retains friction index as signal, removes unproven kill→retry protocol. |
| 2 | H8 9/9 agreement | Plan 8 Phase 2 | 100% agreement. §7 co-adaptation check RUN. | **DONE.** Held-out signal test: 3/4 independent signals separate regimes (event count 2.68x, turns 2.42x, content 0.09x). Perturbation test: 0 FP, 0 FN under 10% exitCode flip. R4 CLEARED — label upgraded to [DEDUCTIVE] (no flag). |
| 3 | Bimodal CPI (0.912 / 1.594) | Plan 2 Phase 6 | N=2 per regime, point estimates | Label as [EXPLORATORY]. Cannot compute Type S/M at N=2. |
| 4 | Write compression 8x | Plan 2 / audit_report | N=1 valid pair (P2) | Label as [EXPLORATORY]. Type M almost certainly >2.0x at N=1. |
| 5 | Skill-effect (orientation speedup 7.2 vs 8.5 msgs) | Plan 1 / audit_report | N=9, but effect is 1.3 msgs | Fit hierarchical model. Likely Type S > 10% (effect near zero). |
| 6 | MONITORING_IMPATIENCE elimination (0% vs 52%) | Plan 7 | N=3 treatment, N=1 control | Label as [DEDUCTIVE] (mechanism elimination, not magnitude). |

**Rule:** Backfill does NOT invalidate existing claims. It adds honest uncertainty
labels. "8x write compression [EXPLORATORY, N=1, Type M unknown]" is still
evidence — it's just honestly labeled evidence.

---

## §9 DEDUCTIVE vs INDUCTIVE: RECLASSIFICATION OF EXISTING CLAIMS

| Claim | Current label | Correct label | Why |
|-------|--------------|---------------|-----|
| H4: Binary resolution (6/6 traces) | "CONFIRMED" | **[DEDUCTIVE]** — mechanism proof | Presence/absence in traces. No magnitude. N=6 is exhaustive, not statistical. |
| H8: FI discriminates regimes (9/9) | "CONFIRMED" | **[DEDUCTIVE]** — R4 cleared | Classification accuracy is structural. §7 co-adaptation check passed: 3/4 held-out signals separate regimes; 0 FP/FN under 10% perturbation. |
| Plan 7: 0% spinner-only (N=3) | "ELIMINATED" | **[DEDUCTIVE]** — mechanism elimination | Before/after mechanism proof. Not a magnitude claim. |
| CPI = 0.833 (N=4 pairs) | Reported as fact | **[INDUCTIVE]** — needs CI + Type S/M | Statistical estimate from paired measurement. |
| Write compression = 8x (N=1) | Reported as headline | **[EXPLORATORY]** — N=1, no CI | Single observation. Cannot support confirmatory claim. |
| Orientation speedup 1.3 msgs | "CONFIRMED (revised)" | **[INDUCTIVE]** — likely Type S > 10% | Effect near zero relative to variance. Sign may be wrong. |

---

## §10 EXIT CRITERIA (METHODOLOGY PLAN)

This plan is NOT judged by feature-plan criteria (deployment, captures, N pairs).
It is judged by **adoption**:

| # | Criterion | Evidence |
|---|-----------|----------|
| M1 | Plan 8 §4.0 adopts the framework (reconciliation rules, N≥3, Type S/M) | §4.0 present and locked before unblinding |
| M2 | ≥3 existing claims reclassified as DEDUCTIVE/INDUCTIVE/EXPLORATORY | §9 table populated and reflected in audit_report.md |
| M3 | ≥1 inductive claim reports Type S/M with CI | Any plan's exit evidence includes posterior summary |
| M4 | ≥1 co-adaptation check run (R4 follow-up on H8) | **DONE.** `scripts/r4_co_adaptation_check.py` — held-out 3/4, perturbation 0 FP/FN. R4 cleared. |
| M5 | Independent-scorer pattern used for ≥1 metric | §6 table has at least one verified row |
| M6 | audit_report.md and pr_writeup.md use claim labels | All claims tagged [DEDUCTIVE]/[INDUCTIVE]/[EXPLORATORY] |

**Plan 9 is COMPLETE when M1-M5 pass.** M5 is required (not stretch) because the
independent-scorer is what makes the "two engines" framing literally true. Without
it, CTA has one engine looking at its own data two ways — valuable, but not the
dual-engine claim the plan aspires to. M6 is a stretch goal.

**Plan 9 is ABANDONED if:** the overhead of Bayesian modeling at N=3-4 produces
posteriors so wide they're uninformative. Quantitative definition of
"uninformative":

| Criterion | Threshold | Interpretation |
|-----------|-----------|----------------|
| **CrI width** | 95% CrI on β1 spans > 2.0 CPI units | The credible interval covers the entire plausible effect range (from "strongly hurts" to "strongly helps"). No decision can be made. |
| **Prior-posterior overlap** | > 90% overlap between prior and posterior on β1 | The data barely moved the prior. The experiment added negligible information. |
| **Type M ratio** | Type M > 3.0× | Any observed effect is expected to be a 3x exaggeration of truth. Reporting it would be misleading regardless of sign. |
| **P(sign correct)** | Type S > 25% | More than 1-in-4 chance the sign is wrong. Cannot even report direction. |

If ANY of these fire on the first N=3 analysis, the honest conclusion is: "N is
too small for any statistical claim at this effect size." CTA should then either:
(a) rely exclusively on deductive (mechanism) claims until N grows, or
(b) increase N until the posterior is informative (CrI width < 1.0, Type M < 2.0×).

**Note:** This is not a failure of the framework — it is the framework working
correctly. An uninformative posterior is an honest result. The alternative
(reporting point estimates from N=1 as if they're precise) is the actual failure
mode this plan prevents.

---

## §11 RELATIONSHIP TO OTHER PLANS

| Plan | Relationship |
|------|-------------|
| Plan 8 (§4.0) | First consumer. Gap 3 pre-registration IS this framework applied. |
| Plan 2 (CPI) | Backfill target. Bimodal CPI needs [EXPLORATORY] label at N=2. |
| Plan 1 (skill-effect) | Backfill target. Orientation speedup needs Type S/M. |
| Plan 7 (NDJSON) | Already [DEDUCTIVE] — mechanism elimination. No backfill needed. |
| compose-pkl | External reference. The dual-engine chain is the gold standard; this plan adapts it to CTA's scale. |

---

## §13 LIMITATIONS AND NAMED GAPS

Honest acknowledgment of what this framework cannot do, adapted from compose-pkl's
criticism audit (C1-C10) and gap summary.

### G9 — External replication (DOES NOT EXIST)

compose-pkl explicitly names this: "No external replication by independent
researchers. Internal dual-platform is strong but not third-party verification."

CTA has the same gap, more severely:
- All captures are produced by our own harness on our own machine.
- All metrics are computed by our own code.
- All classifications are made by our own criteria.
- No external party has independently replicated any CTA result.

**Mitigation (not a fix):** The independent-scorer pattern (§6) breaks the
same-codebase loop internally. A second agent classifying traces blind to
condition is the strongest available substitute. But it is NOT external
replication — it is internal cross-checking.

**Trajectory:** If CTA results are ever published or shared externally, the
minimum is: (a) release raw NDJSON captures, (b) release the scoring code,
(c) invite independent re-analysis. Until then, all CTA claims carry the
implicit caveat "internally validated; external replication pending."

### G10 — No posterior predictive check (PPC)

compose-pkl's Gate 5 validates that the fitted model can generate data resembling
the real data (PPC p=0.066, healthy range 0.05-0.95). Plan 9 has no equivalent.

**Why it matters:** A model can produce a precise β1 estimate that is nonetheless
wrong because the model's generative assumptions don't match reality. PPC catches
this: if simulated sessions from the posterior don't look like real sessions, the
model is misspecified.

**CTA-scale approximation:** After fitting the hierarchical model, simulate 100
session pairs from the posterior. Check: do the simulated message counts, error
rates, and CPI values fall within the range of observed values? If simulated
sessions look nothing like real ones, the model is wrong regardless of β1's CrI.

**Status:** Not yet implemented. Add as a diagnostic when the first N≥3 analysis
runs. Not a gate (too expensive to block on), but a sanity check.

### G11 — No automated enforcement

compose-pkl has `scripts/enforce-reconciliation.py` (compile-time blocker) and
`scripts/pre-register-claim.py` (FreeTSA timestamps). Plan 9's circuit breakers
are documentation-only — they rely on the analyst remembering to check R1-R6.

**Risk:** Under time pressure or enthusiasm bias, an analyst (human or agent) may
skip the circuit breaker checkpoint and report a claim that should have been
rejected.

**Mitigation:** The §4.1 pre-registration proof mechanism (git commit hash) is the
first step. A future `scripts/check_claim.py` that reads a claim + its evidence
and prints which circuit breakers pass/fail would be the second step. Not blocking
for v0.3.0, but the direction of travel.

### G12 — No mutation testing for metrics

compose-pkl runs 642 mutations across 136 files (100% killed, cron every 2h).
This verifies that the measurement code responds correctly to perturbations.

CTA's equivalent would be: systematically perturb NDJSON inputs (flip tool_result
labels, shuffle condition assignments, inject synthetic errors) and verify that
CPI/FI/ECR respond in the expected direction. This is related to §7's perturbation
test but more systematic — a regression suite, not a one-off check.

**Status:** Not implemented. The §7 perturbation test is the minimum viable
version. Full mutation testing is a stretch goal for when the metric codebase
stabilizes.

### Summary of named gaps

| Gap | Severity | Mitigation | Timeline |
|-----|----------|-----------|----------|
| G9 External replication | High (structural) | Independent-scorer (§6) as internal substitute | Only if publishing externally |
| G10 No PPC | Medium (model validation) | Simulate-from-posterior sanity check at first N≥3 | When first N≥3 analysis runs |
| G11 No automation | Medium (human error) | §4.1 git-commit proof now; `check_claim.py` later | Incremental |
| G12 No mutation testing | Low (code stability) | §7 perturbation test as minimum | When metrics stabilize |

**Operating principle (from compose-pkl):** "These gaps do not invalidate the
mechanism — but they define the compliance boundary. Claims beyond that boundary
are 'promising — requires replication' (Rule downgrade)."

---

## §14 FRAMEWORK TIERING (MVP vs CATHEDRAL)

The framework has two tiers. The MVP tier applies ALWAYS, at any N, for any claim.
The Cathedral tier is the aspirational standard that defines what we don't yet
know — not a tool we'll routinely run at N=1-2.

### MVP tier (apply always, zero statistical overhead)

| Component | What it does | Cost |
|-----------|-------------|------|
| **Claim labeling** (§1.1) | Every claim tagged [DEDUCTIVE]/[INDUCTIVE]/[EXPLORATORY] | Zero — a text label |
| **R6 construct validity** (§4, §1.2) | Before replicating, verify the experiment exercises the mechanism's antecedent | One question: "did the fire start?" |
| **Deductive/inductive split** (§1) | Never let mechanism-proof confidence leak into magnitude claims | A distinction, not a computation |
| **§1.3 measurement integrity** | Verify the instrument produced valid data before modeling | Checklist (4 items) |
| **R4 shared-input check** | If two metrics share a data source, their agreement is uninformative | One question: "same NDJSON?" |
| **Independent scorer** (§6) | At least one metric verified by a second computation path blind to condition | One blind classification per plan |

**The MVP tier is the plan's center of gravity.** It addresses CTA's actual failure
mode (construct validity, instrument failure, shared-input co-adaptation) at zero
statistical cost. It is always applicable regardless of N.

### Cathedral tier (aspirational standard, requires N≥3)

| Component | What it does | When to invoke |
|-----------|-------------|----------------|
| **Type S/M** (§2) | Quantify sign-error probability and magnitude exaggeration | N≥3 valid pairs |
| **Hierarchical Bayes** (§3) | Isolate skill_effect from pair noise with posterior distributions | N≥3 (minimal model) or N≥5 (full model) |
| **Robustness gates G1-G8** (§5) | 8-point checklist for confirmatory claims | Before closing a hypothesis |
| **PPC** (§13 G10) | Verify model generates plausible data | After first N≥3 fit |
| **Quantitative abandonment** (§10) | Pre-committed thresholds for "posterior uninformative" | If N≥3 analysis produces wide CrI |

**The Cathedral tier defines the standard, not the routine.** At N=1-2, these tools
produce uninformative outputs. They exist so that when N grows, the framework is
ready. Present them as "what we would do with more data" — not "what we must do
before any claim." The MVP tier is sufficient for honest reporting at CTA's current
scale.

**The reframing:** The plan stops looking like it's under-using its own machinery,
and starts looking like what it is — a discipline for being honest about a small
evidence base. The Cathedral is the north star; the MVP is the ground underfoot.

---

## §15 SKILL.md EVALUATION METHODOLOGY

Lessons from Gap 3 (Runs 1-2) applied to future SKILL.md evaluations.

### §15.1 What Gap 3 taught us about skill evaluation

| Lesson | Evidence | Implication for future evals |
|--------|----------|------------------------------|
| **The skill's own guidance can prevent the failure it targets** | Probe run 2: mode-selection table ("Default to -p") already prevents exit-42; neither arm attempted `-i`. This is NOT native adaptation (where control encounters and solves the problem) — the antecedent is unreachable under the skill's own design. | Before testing a prescription, verify the failure condition is reachable under the BASE skill (control). If the skill's general guidance already preempts the failure, the prescription is untestable without a deliberately worse skill. |
| **Inner agents self-heal environment friction** | Run 1: qodercli wrote stdlib jwt_compat.py; friction never surfaced to Hermes | Environment-friction prescriptions target a layer the inner agent operates below. Test at the layer the prescription actually operates at. |
| **Instrument ≠ prescription** | H8 proves detection works; nothing proved recovery works | Separate "can we detect the problem?" from "does acting on the detection help?" These are different claims requiring different evidence. |
| **The decisive evidence is often deductive** | Probe run 2: "did exit-42 fire?" is a yes/no mechanism fact from the trace; CPI is secondary context | Design experiments where the primary outcome is a mechanism fact (deductive), with magnitude (inductive) as supporting context. |

### §15.2 Protocol for future SKILL.md evaluations

Before running a paired ±skill experiment:

1. **Construct-validity check (R6):** State the mechanism's antecedent explicitly.
   Verify the control arm WILL encounter the failure condition. If the base skill
   already prevents it, the experiment is construct-invalid — redesign or abandon.

2. **Layer check:** At what layer does the prescription operate? (Hermes monitoring
   layer? Inner-agent code layer? Invocation-mode layer?) Design friction that
   surfaces at THAT layer, not a different one.

3. **Reachability check:** Can a capable inner agent with full Bash self-heal this
   friction silently? If yes, it won't surface to the detection layer. Choose
   friction that CANNOT be code-around (mode failures, permission walls, timeout
   cascades).

4. **Primary outcome = mechanism fact:** The experiment's verdict should rest on a
   deductive observation (did the mechanism fire? did the agent change behavior?)
   not solely on a CPI difference at N=1.

5. **Behavioral trace required:** CPI alone cannot disambiguate outcomes. Always
   extract the process() sequence from state.db to determine WHY the result
   occurred (native adaptation vs guidance-driven vs stuck).

6. **Scope the claim to the tested domain:** If the prescription works for exit-42,
   claim exit-42. Do not generalize to "environment friction" without testing
   environment friction that actually surfaces.

### §15.3 SKILL.md version history (evidence-linked)

| Version | Change | Evidence | Label |
|---------|--------|----------|-------|
| v2.4.0 | Base skill (no friction block) | — | — |
| v2.5.0 | Added friction index + regime-response protocol | H8 9/9 [DEDUCTIVE + R4] | Instrument proven; prescription unproven |
| v2.5.1 | Added exit-42 guidance, mild/heavy distinction | Bgmode test [DEDUCTIVE] | Model compliance proven |
| v2.5.2 | Scope-reduced: removed 5-step protocol, kept instrument + exit-42 note | Probe run 2 [DEDUCTIVE + EXPLORATORY]: antecedent unreachable under skill's own design, prescription redundant | Instrument retained; prescription removed |

**The pattern:** Each version's change is linked to specific evidence with a Plan 9
label. No change ships without evidence. No evidence is over-claimed.

---

## §16 CHANGELOG

| Version | Date | Change |
|---------|------|--------|
| 0.4.0 | 2026-07-22 | Structural realignment per sibling reflection: (1) §0 reframed — construct validity is CTA's primary failure mode, not statistical power. (2) §1 reframed as "aspirational discipline" — CTA has one engine looking at data two ways, not a literal dual-engine system. (3) §1.1 allows mixed labels [DEDUCTIVE + EXPLORATORY]. (4) R4 fixed — objection is shared input, not perfect agreement per se. (5) R5 honestly stated as honor-system (disciplines attention, not tamper-proof). (6) M5 (independent-scorer) promoted from stretch to required. (7) §14 added — framework tiering (MVP always-apply vs Cathedral aspirational). (8) §15 added — SKILL.md evaluation methodology (lessons from Gap 3 Runs 1-2). Probe run 2 result: native adaptation, SKILL.md v2.5.2 scope-reduced. |
| 0.3.0 | 2026-07-22 | Added §1.3 (measurement integrity / abduction stage). Fixed §3 Stan model (declared K, added N=3-4 minimal model). Reframed §4 as circuit breakers (sequential mandatory checkpoint). Added §4.1 (R5 pre-registration proof mechanism). Added §4.2 (R6 concrete example — Gap 3 Run 1). Refined §10 with quantitative "uninformative posterior" thresholds. Added §13 (limitations and named gaps). |
| 0.2.0 | 2026-07-22 | Added §1.2 (construct validity — "extinguisher had no fire" lesson from Gap 3 Run 1). Added R6 (construct-validity reconciliation rule). Updated §8 backfill: Gap 3 Run 1 is construct-invalid (R6 fires), N≥3 blocked pending probe with Hermes-visible friction. Probe-before-replication principle established. |
| 0.1.0 | 2026-07-22 | Initial draft. Two-engine separation, Type S/M, Bayesian hierarchical model, reconciliation rules R1-R5, robustness gates G1-G8, independent-scorer pattern, co-adaptation check, backfill schedule, claim reclassification. First consumer: Plan 8 §4.0 (already locked). |
