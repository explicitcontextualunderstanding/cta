"""Integration tests for detect_regime_adaptation (Plan 8 §Phase 3).

6 scenarios covering the two-phase detection logic, valence semantics,
context-flag shortcut, and registry dispatch.
"""

import sys
sys.path.insert(0, "src")

from cta.data_models import Event, EventType
from cta.skill_rules import detect_regime_adaptation, DETECTOR_REGISTRY, run_detectors


def make_event(eid, etype, target="", content=""):
    return Event(event_id=eid, type=etype, target=target, content=content)


def test_friction_plus_kill_constructive():
    events = [
        make_event(1, EventType.TOOL_CALL, "process(poll)", "⚠ Friction: HIGH-ERROR (5/10) | RETRY Bash x5"),
        make_event(2, EventType.TOOL_CALL, "process", 'process(action="kill", session_id="abc")'),
    ]
    findings = detect_regime_adaptation(events)
    assert len(findings) == 1
    assert findings[0].valence == "constructive"
    assert findings[0].evidence["switch_type"] == "killed_session"


def test_friction_plus_print_switch_constructive():
    events = [
        make_event(1, EventType.EXECUTE, "terminal", "⚠ Friction: HIGH-ERROR (4/6) | CTX-VELOCITY +3.1%/ev"),
        make_event(2, EventType.EXECUTE, "terminal", 'qodercli -p "fix the auth bug" --permission-mode bypass_permissions'),
    ]
    findings = detect_regime_adaptation(events)
    assert len(findings) == 1
    assert findings[0].valence == "constructive"
    assert findings[0].evidence["switch_type"] == "switched_to_print"


def test_friction_no_switch_neutral():
    events = [
        make_event(1, EventType.TOOL_CALL, "process(poll)", "⚠ Friction: HIGH-ERROR (6/8) | RETRY Bash x6"),
        make_event(2, EventType.TOOL_CALL, "process(poll)", "Tools used: Bash (npm test) | Thinking..."),
        make_event(3, EventType.TOOL_CALL, "process(poll)", "Completed (success, 10 turns, 120s)"),
    ]
    findings = detect_regime_adaptation(events, context={"friction_index": 0.55})
    assert len(findings) == 1
    assert findings[0].valence == "neutral"


def test_clean_session_empty():
    events = [
        make_event(1, EventType.EXECUTE, "terminal", 'qodercli -p "add error handling" --permission-mode bypass_permissions'),
        make_event(2, EventType.EXECUTE, "terminal", "Completed (success, 4 turns, 19s)"),
    ]
    findings = detect_regime_adaptation(events)
    assert len(findings) == 0


def test_context_flag_detection():
    events = [
        make_event(1, EventType.EXECUTE, "terminal", 'qodercli -p "retry task" --permission-mode bypass_permissions'),
    ]
    findings = detect_regime_adaptation(events, context={"friction_detected": True, "friction_index": 0.45})
    assert len(findings) == 1
    assert findings[0].valence == "constructive"
    assert findings[0].evidence["switch_type"] == "switched_to_print"


def test_registry_dispatch():
    findings = run_detectors(
        [
            make_event(1, EventType.TOOL_CALL, "process(poll)", "⚠ Friction: HIGH-ERROR (3/5)"),
            make_event(2, EventType.EXECUTE, "terminal", 'qodercli -p "task"'),
        ],
        ["regime_adaptation", "nonexistent_detector"],
    )
    assert len(findings) == 1
    assert findings[0].sip_type == "REGIME_ADAPTATION"


def test_registry_has_10_detectors():
    assert len(DETECTOR_REGISTRY) == 10
    expected = {
        "pty_omission", "interactive_blockade", "vague_prompt",
        "procedural_scaffolding", "delegation_redirect", "concept_bleed",
        "false_success", "secret_exposure", "forbidden_flag_usage",
        "regime_adaptation",
    }
    assert set(DETECTOR_REGISTRY.keys()) == expected


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
