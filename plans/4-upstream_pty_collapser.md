# Plan 4 — Upstream PR: PTY Session Collapser

Status: **DRAFT** — awaiting Phase 0 results before submitting
Target: WillChow66/CTA (origin)
Parent: [3: plans/3-upstream_hermes_adapter.md]
Depends on: Plan 3 (hermes_adapter.py must land first)

---

## Summary

Interactive-mode Hermes sessions use background PTY processes (`terminal` with
`pty=true, background=true` followed by N `process(poll/log/write/kill)` calls).
Without collapsing, a single delegation produces 50-70 granular poll events that
drown the alignment module (Module 3) in noise.

This PR adds a preprocessing pass that collapses scattered `process()` calls into
composite EXECUTE events representing coherent interactive sessions.

---

## Files

| File | Purpose |
|------|---------|
| `src/cta/pty_collapser.py` | Collapse PTY poll/write/log/kill into parent EXECUTE event |

---

## Key design decisions

1. **Session boundary detection**: PTY session starts with `terminal(command, pty=true,
   background=true)` and ends with `process(action="kill")` or trace end.

2. **Composite event**: All `process()` calls matching the session_id are collapsed
   into the parent EXECUTE event's content as structured JSON sub-trace. Preserves
   poll count, write count, and timing for downstream analysis.

3. **Drop-in superset**: For traces without PTY sessions, output is identical to
   `hermes_session_to_trace`. No behavior change for print-mode traces.

4. **PTYSession metadata**: Exposes `total_polls`, `total_writes`, `actions[]` for
   SIP detectors that need interactive-mode signals (e.g., monitoring impatience).

5. **Observation field preserved**: Each `process()` action retains its tool-result
   JSON (`_process_action`, line 225), containing `output_preview` (grid-rendered,
   ANSI-stripped, max ~658 chars). Plan 7 proposes a regex stop-gap to extract
   liveness signals (ctx% at 47% hit-rate), but note: output is grid-rendered not
   raw bytes, spaces are dropped, and P1 (SDK activation check) is a hard gate
   before building the parser. See
   [Plan 7: plans/7-subagent_progress_observation.md].

---

## Scope boundary

- General: works for ANY skill that uses background PTY sessions (not just qodercli)
- Does NOT include qodercli-specific SIP detectors
- Does NOT include the interactive harness (`m3_interactive_harness.py`)

---

## Pre-submission checklist

- [ ] Plan 3 merged (adapter dependency)
- [ ] Unit tests: PTY collapse, no-PTY passthrough, multi-session traces
- [ ] Demonstrate with non-qodercli PTY session (e.g., any background process)
- [ ] 34 existing PTYCollapser tests pass
