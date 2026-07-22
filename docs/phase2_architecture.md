# Phase 2: Config-Driven CTA Audit Architecture

Version: 1.0
Date: 2026-07-21
Status: Implementation in progress (2a complete, 2b-2e pending)

---

## Current Architecture

```
configs/qodercli.json          ← per-skill config (JSON)
        │
        ▼
src/cta/audit_config.py        ← dataclass loader (AuditConfig)
        │
        ▼
scripts/run_audit.py           ← orchestrator
   ├── load_session()          ← state.db → message list
   ├── analyze_run()           ← messages → metrics + CTA Trace
   │       └── hermes_adapter.hermes_session_to_trace()
   ├── evaluate_hypotheses()   ← config-driven metric thresholds
   ├── detect_sips()           ← skill_rules.run_detectors(names)
   ├── validate_controls()     ← config-driven pass criteria
   └── markdown_report()       ← config-driven report template
        │
        ▼
data/audit_report.json + data/audit_report.md
```

### What's already config-driven

| Component | Config field | Drives |
|-----------|-------------|--------|
| Tool filters | `tool_filters.*` | Delegation detection, write counting, binary resolution |
| SIP detectors | `sip_detectors[]` | Which detectors run (by registry name) |
| Hypotheses | `hypotheses.{H1..H4}` | Metric type + confirm/disconfirm thresholds |
| Controls | `controls.negative/edge_case` | Task ID + pass criteria |
| Report | `report.*` | Title, model label, design label |

### What's NOT yet config-driven

| Component | Hardcoded in | Needs |
|-----------|-------------|-------|
| Task prompts | capture harness only | `tasks:` block in config |
| Fixture path | capture harness only | `fixture:` field |
| Isolation settings | capture harness only | `isolation:` block |
| Metric selection | run_audit.py (all metrics always computed) | `metrics:` list |
| Structural scorer | standalone CLI (not wired into runner) | `--structural` flag |
| False success detection | not implemented | New SIP detector |

---

## Target Architecture

```
configs/<skill>.yaml            ← per-skill config (YAML, richer schema)
        │
        ▼
src/cta/audit_config.py         ← loader (YAML primary, JSON back-compat)
        │
        ├──► scripts/run_audit.py        ← post-hoc analysis (reads captures)
        │       ├── structural_scorer    ← inline metric computation
        │       ├── skill_rules          ← pluggable SIP detectors
        │       └── false_success        ← new: VFS diff vs claims
        │
        └──► scripts/capture_harness.py  ← session generation (reads tasks)
                ├── tasks from config
                ├── fixture from config
                └── isolation from config
```

### Design principles

1. **Config is the single source of truth.** A new skill audit requires only a new
   YAML file — no code changes to the runner or harness.

2. **Detectors are pluggable by name.** The `DETECTOR_REGISTRY` in `skill_rules.py`
   maps string names → callables. New detectors register themselves; config selects
   which ones run.

3. **Metrics are composable.** The `metrics:` list in config selects which metric
   modules contribute to the report. Each metric module has a standard interface.

4. **Capture and analysis are decoupled.** The capture harness generates sessions;
   the audit runner analyzes them. They share the config but run independently.
   You can re-analyze without re-capturing.

---

## Module Interfaces

### 1. Config Schema (YAML)

```yaml
# Required fields
skill:
  name: str           # skill identifier (used in reports)
  version: str        # skill version being audited
  path: str           # path to SKILL.md (for reference)

captures_dir: str     # relative path to session captures

tool_filters:
  delegation_call:
    tool_name: str    # Hermes tool that invokes the skill's binary
    command_contains: str  # substring identifying delegation
  manual_writes: [str]     # tool names that count as manual file edits
  skill_view: str          # tool name for loading skill content
  binary_resolution:
    tool_name: str
    command_regex: str     # regex for binary lookup commands
    command_contains: str
  pty_arg: str             # argument name for PTY flag (default: "pty")

sip_detectors: [str]       # registry names of detectors to run

hypotheses:
  <ID>:
    name: str
    metric: str            # metric type key (drives evaluation logic)
    confirm_threshold: float?
    disconfirm_threshold: float?
    note: str?             # "untestable" triggers skip

controls:
  negative:
    task_id: str
    pass_criteria: str     # "zero_delegation_calls" | "zero_writes"
  edge_case:
    task_id: str
    pass_criteria: str

report:
  title: str               # supports {skill_name} interpolation
  model: str
  design: str

# New fields (Phase 2b/2c)
fixture: str               # path to test project directory
tasks:
  positive:
    - id: str
      prompt: str          # supports {skill} interpolation
      expect: str          # human-readable expected behavior
  negative_control:
    - id: str
      prompt: str
      expect: str
  edge_case:
    - id: str
      prompt: str
      expect: str

metrics: [str]             # which metric modules to include in report
isolation:
  container: bool
  wal_checkpoint: bool
  skill_toggle: str        # "physical_mount" | "profile_install"
runs_per_condition: int
```

### 2. SIP Detector Interface

```python
# Registration: add to DETECTOR_REGISTRY in skill_rules.py
DETECTOR_REGISTRY: Dict[str, Callable] = {
    "pty_omission": detect_pty_omission,
    "interactive_blockade": detect_interactive_blockade,
    ...
}

# Detector signature (two variants):
def detect_x(events: List[Event]) -> List[SIPFinding]: ...
def detect_y(events: List[Event], context: Dict[str, Any] | None = None) -> List[SIPFinding]: ...

# SIPFinding output:
@dataclass
class SIPFinding:
    sip_type: str       # e.g. "PTY_OMISSION"
    valence: str        # "constructive" | "neutral" | "destructive"
    event_id: int       # triggering event (0 for run-level findings)
    description: str
    evidence: Dict[str, Any]
```

To add a new detector:
1. Write the function in `skill_rules.py` (or a new module that registers into the dict)
2. Add its name to `DETECTOR_REGISTRY`
3. Reference it by name in the config's `sip_detectors` list

### 3. Structural Scorer Interface (Phase 3A, complete)

```python
# CLI
python -m cta.structural_scorer treatment.db baseline.db [-o output.json]
python -m cta.structural_scorer -t t1/ t2/ -b b1/ b2/ [--compact] [-o output.json]

# Programmatic
from cta.structural_scorer import score_pair, score_batch
result = score_pair(Path("treatment.db"), Path("baseline.db"))
# result["metrics"] → {event_count_ratio, write_compression, entropy_*, unilateral_actions}

# Batch (all T×B pairs)
result = score_batch([t1, t2, t3], [b1, b2])
# result["aggregate"] → {event_count_ratio: {mean, variance, min, max, n}, ...}
```

### 4. Hypothesis Metric Types

| Metric key | Evaluation logic | Config fields used |
|------------|-----------------|-------------------|
| `tool_call_compression` | Compare avg tool calls T vs B; write compression | confirm_threshold, disconfirm_threshold |
| `pty_compliance` | Count pty_set vs pty_missing across treatment runs | confirm_threshold (1.0 = zero missing) |
| `binary_resolution_rate` | Fraction of treatment runs with binary resolution > 0 | confirm_threshold (0.67 = 2/3) |
| `interactive_blockade` | Always UNTESTABLE (deferred) | note |

New metric types can be added to `evaluate_hypotheses()` by matching on `hcfg.metric`.

### 5. False Success Detector (Phase 2d, pending)

```python
# New detector: detect_false_success
# Signature: (events, context) -> List[SIPFinding]
# Logic:
#   1. Find final assistant message (last REASON event or last message content)
#   2. Extract file-modification claims via regex:
#      r"(created|modified|implemented|wrote|updated)\s+.*?([\w/]+\.\w{1,4})"
#   3. Compare against context["vfs_diff"] (git diff --stat output)
#   4. Flag: claimed files not in actual diff → FALSE_SUCCESS_REPORTING
#   5. Flag: error patterns in process(log) output omitted from summary

# Requires: capture harness to record `git diff --stat` in result.json
# Config: add "false_success" to sip_detectors list
```

---

## Migration Path

### Step 2a: Structural Scorer CLI (COMPLETE)

`src/cta/structural_scorer.py` — standalone, tested on M2 + M3 data.

### Step 2b: YAML Config Migration

1. Add `pyyaml` dependency (or use stdlib `json` with `.yaml` extension detection)
2. Extend `load_config()` to detect file extension:
   - `.json` → existing JSON parser (back-compat)
   - `.yaml`/`.yml` → YAML parser with richer schema
3. Convert `configs/qodercli.json` → `configs/qodercli.yaml` (add new fields)
4. New fields are optional — missing fields get defaults

### Step 2c: Task Definitions

1. Add `tasks:` parsing to `AuditConfig` (new dataclass: `TaskConfig`)
2. Capture harness reads tasks from config instead of hardcoded prompts
3. `expect:` field is documentation only (human-readable); actual pass/fail
   logic remains in `validate_controls()` and `evaluate_hypotheses()`

### Step 2d: False Success Detector

1. Add `detect_false_success()` to `skill_rules.py`
2. Register in `DETECTOR_REGISTRY`
3. Capture harness: add `git diff --stat` to result.json post-run
4. `run_audit.py`: pass `vfs_diff` in context when available

### Step 2e: Second-Skill Validation

1. Pick a Hermes skill with scope constraints (candidate: `delegate_task` or
   any skill that says "Do NOT use for X")
2. Write `configs/<skill>.yaml` with appropriate tool_filters + detectors
3. Run capture harness (or use existing sessions if available)
4. Run `run_audit.py --config configs/<skill>.yaml`
5. Verify: report generates, controls pass, detectors fire correctly

---

## Integration: run_audit.py + structural_scorer

When config includes `structural_scorer` in the `metrics:` list (or when
`--structural` flag is passed):

```python
# In run_audit.py, after loading all runs:
if "structural_scorer" in config.metrics or args.structural:
    from cta.structural_scorer import score_batch
    t_dirs = [d for d in run_dirs if "treatment" in d.name and (d / "state.db").exists()]
    b_dirs = [d for d in run_dirs if "baseline" in d.name and (d / "state.db").exists()]
    structural = score_batch(t_dirs, b_dirs)
    report["structural_metrics"] = structural
```

This adds the full metric matrix (per-pair + aggregate) to `audit_report.json`.

---

## File Inventory

| File | Role | Status |
|------|------|--------|
| `src/cta/audit_config.py` | Config loader (JSON → dataclasses) | Exists, needs YAML extension |
| `src/cta/skill_rules.py` | SIP detector registry + 10 detectors | Exists, complete |
| `src/cta/structural_metrics.py` | Core metric functions | Exists, complete |
| `src/cta/structural_scorer.py` | Standalone CLI scorer | **New (this session)** |
| `src/cta/hermes_adapter.py` | state.db → CTA Trace conversion | Exists, complete |
| `scripts/run_audit.py` | Post-hoc analysis orchestrator | Exists, needs --structural flag |
| `scripts/capture_harness.py` | Session generation (M2) | Exists, needs config-driven tasks |
| `scripts/m3_interactive_harness.py` | Session generation (M3 interactive) | Exists, separate from Phase 2 |
| `configs/qodercli.json` | Current config | Exists, migrate to YAML |
| `configs/qodercli.yaml` | Target config (richer schema) | Pending |

---

## Success Criteria (from Plan 2)

- [x] `python -m cta.structural_scorer treatment.db baseline.db` emits JSON metrics
- [ ] `run_audit.py --config configs/qodercli.yaml` works (YAML loader)
- [ ] `run_audit.py --config configs/<other-skill>.yaml` works on a non-qodercli skill
- [ ] False success detector fires on P1-treatment-1 (canonical case)
- [ ] Capture harness reads task prompts from config (no hardcoded strings)
