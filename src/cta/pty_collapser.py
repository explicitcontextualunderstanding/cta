"""PTYCollapser — preprocessing pass for interactive-mode traces.

Groups scattered process(poll/write/log/kill) calls into composite EXECUTE
events representing coherent interactive qodercli sessions.

A PTY session starts with terminal(background=true, pty=true) containing
"qodercli" and ends with process(action="kill") or the next non-process
tool call after a gap. All intermediate process() calls are collapsed into
the parent EXECUTE event's content as a structured sub-trace.

This runs between G1 adapter output and Module 2 (segmentation) input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .data_models import Event, EventType, EventOutcome


@dataclass
class PTYSession:
    """A collapsed interactive PTY session."""
    parent_event_id: int
    command: str
    session_id: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    total_polls: int = 0
    total_writes: int = 0
    total_logs: int = 0
    killed: bool = False
    trust_dialog_handled: bool = False


def collapse_pty_sessions(events: list[Event]) -> tuple[list[Event], list[PTYSession]]:
    """Collapse process() scatter into composite EXECUTE events.

    Returns (collapsed_events, pty_sessions) where collapsed_events replaces
    the parent terminal + all child process() calls with a single composite
    EXECUTE event, and pty_sessions carries the structured sub-traces for
    H3 analysis (trust dialog detection).
    """
    pty_sessions: list[PTYSession] = []
    result: list[Event] = []

    i = 0
    while i < len(events):
        event = events[i]

        is_pty_parent = (
            event.type == EventType.EXECUTE
            and "qodercli" in (event.target or "")
            and _is_background_pty(event)
        )

        if not is_pty_parent:
            result.append(event)
            i += 1
            continue

        # Found a PTY parent — collect subsequent process() events
        session = PTYSession(
            parent_event_id=event.event_id,
            command=event.target or "",
        )

        # Extract session_id from the observation (background process receipt)
        if event.content:
            try:
                receipt = json.loads(event.content)
                session.session_id = receipt.get("session_id")
            except (json.JSONDecodeError, TypeError):
                pass

        # Scan forward for process() calls
        j = i + 1
        while j < len(events):
            child = events[j]
            if child.type == EventType.TOOL_CALL and "process" in (child.target or ""):
                action_info = _parse_process_action(child)
                session.actions.append(action_info)

                if action_info["action"] == "poll":
                    session.total_polls += 1
                elif action_info["action"] == "write":
                    session.total_writes += 1
                    if _is_trust_response(action_info):
                        session.trust_dialog_handled = True
                elif action_info["action"] == "log":
                    session.total_logs += 1
                elif action_info["action"] == "kill":
                    session.killed = True
                    j += 1
                    break
                j += 1
            elif child.type == EventType.TOOL_CALL and "process" not in (child.target or ""):
                # Non-process tool call — PTY session ended implicitly
                break
            elif child.type == EventType.REASON:
                # Reasoning between process calls — skip but don't break
                j += 1
            else:
                break

        # Build composite event
        sub_trace_summary = (
            f"Interactive qodercli session: "
            f"{session.total_polls} polls, {session.total_writes} writes, "
            f"{session.total_logs} logs. "
            f"Trust dialog: {'handled' if session.trust_dialog_handled else 'not observed'}. "
            f"Terminated: {'kill' if session.killed else 'implicit'}."
        )

        composite = Event(
            event_id=event.event_id,
            type=EventType.EXECUTE,
            target=event.target,
            content=sub_trace_summary,
            reasoning=event.reasoning,
            outcome=EventOutcome.SUCCESS if session.killed or session.total_polls > 0 else EventOutcome.PARTIAL,
        )
        result.append(composite)
        pty_sessions.append(session)
        i = j

    return result, pty_sessions


def _is_background_pty(event: Event) -> bool:
    """Check if an EXECUTE event is a background PTY launch."""
    content = event.content or ""
    target = event.target or ""
    # The observation for background launches contains "Background process started"
    # or the target command contains background/pty indicators
    return (
        "background process started" in content.lower()
        or "session_id" in content
        or "background" in target.lower()
    )


def _parse_process_action(event: Event) -> dict[str, Any]:
    """Extract action type and data from a process() TOOL_CALL event."""
    info = {"action": "unknown", "data": None, "observation": event.content or ""}
    target = event.target or ""

    # Try to parse action from target or content
    if "poll" in target:
        info["action"] = "poll"
    elif "submit" in target or "write" in target:
        info["action"] = "write"
    elif "log" in target:
        info["action"] = "log"
    elif "kill" in target:
        info["action"] = "kill"
    elif "wait" in target:
        info["action"] = "wait"
    elif "list" in target:
        info["action"] = "list"

    # Try to extract the write data from content
    try:
        parsed = json.loads(event.content) if event.content else {}
        if isinstance(parsed, dict):
            info["data"] = parsed.get("data")
            if not info["action"] or info["action"] == "unknown":
                action = parsed.get("action", "unknown")
                # Normalize: submit → write (model uses submit, skill documents write)
                info["action"] = "write" if action == "submit" else action
    except (json.JSONDecodeError, TypeError):
        pass

    return info


def _is_trust_response(action_info: dict[str, Any]) -> bool:
    """Detect if a write action is the folder-trust dialog response (1 or 1\\n)."""
    data = action_info.get("data", "")
    if isinstance(data, str):
        return data.strip() in ("1", "1\n", "1\\n", "y", "yes")
    return False


def h3_verdict(pty_sessions: list[PTYSession]) -> dict[str, Any]:
    """Evaluate H3 (Interactive Blockade Resolution) from collapsed sessions.

    H3: Hermes detects folder trust prompt and sends `1\\n`.
    Disconfirmation: ≥5 consecutive polls without resolution.
    """
    if not pty_sessions:
        return {"status": "UNTESTABLE", "reason": "No PTY sessions found in trace"}

    results = []
    for s in pty_sessions:
        # Check for blockade: many polls without any writes
        blockade = s.total_polls >= 5 and s.total_writes == 0
        results.append({
            "session_id": s.session_id,
            "trust_dialog_handled": s.trust_dialog_handled,
            "total_polls": s.total_polls,
            "total_writes": s.total_writes,
            "blockade_detected": blockade,
            "killed": s.killed,
        })

    any_handled = any(r["trust_dialog_handled"] for r in results)
    any_blockade = any(r["blockade_detected"] for r in results)

    if any_blockade:
        status = "DISCONFIRMED"
    elif any_handled:
        status = "CONFIRMED"
    else:
        status = "INCONCLUSIVE (trust dialog may not have appeared)"

    return {"status": status, "sessions": results}
