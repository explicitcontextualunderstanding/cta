"""qodercli-specific SIP detectors (G3: rule-based, no trained classifier).

Three deterministic detectors for failure modes unique to delegation-via-PTY
that native CTA heuristics cannot see.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .data_models import Event, EventType


@dataclass
class SIPFinding:
    """A single SIP detection result."""
    sip_type: str
    valence: str  # constructive | neutral | destructive
    event_id: int
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)


def detect_pty_omission(events: List[Event]) -> List[SIPFinding]:
    """Flag EXECUTE events invoking qodercli without pty=true.

    Note: M4 reclassified this as NEUTRAL for print-mode foreground calls
    (pty is a no-op on that path). Retained for interactive-mode detection.
    """
    findings = []
    for e in events:
        if e.type != EventType.EXECUTE:
            continue
        if "qodercli" not in (e.target or ""):
            continue
        try:
            args = json.loads(e.content) if e.content else {}
        except (json.JSONDecodeError, ValueError):
            args = {}
        if not args.get("pty", False):
            findings.append(SIPFinding(
                sip_type="PTY_OMISSION",
                valence="neutral",
                event_id=e.event_id,
                description="qodercli invoked without pty=true (neutral for print mode)",
                evidence={"target": e.target},
            ))
    return findings


def detect_interactive_blockade(
    events: List[Event], threshold: int = 3
) -> List[SIPFinding]:
    """Flag consecutive identical process(poll/log) without text variation.

    Indicates the agent is stuck polling a blocked interactive session
    (e.g., folder-trust dialog awaiting input).
    """
    findings = []
    poll_streak = 0
    last_content = None

    for e in events:
        if e.type == EventType.TOOL_CALL and "process" in (e.target or ""):
            if e.content == last_content:
                poll_streak += 1
            else:
                poll_streak = 1
            last_content = e.content
            if poll_streak >= threshold:
                findings.append(SIPFinding(
                    sip_type="INTERACTIVE_BLOCKADE",
                    valence="destructive",
                    event_id=e.event_id,
                    description=f"{poll_streak} identical poll/log calls; likely stalled session",
                    evidence={"streak": poll_streak, "threshold": threshold},
                ))
        else:
            poll_streak = 0
            last_content = None

    return findings


VAGUE_PATTERNS = [
    r"qodercli\s+-i\s+'[^']{0,20}'",
    r"qodercli\s+-p\s+'(fix|update|improve|clean)\s+(bugs|code|things|stuff)",
]


def detect_vague_prompt(events: List[Event]) -> List[SIPFinding]:
    """Flag qodercli invocations without explicit target paths or done-criteria."""
    findings = []
    for e in events:
        if e.type != EventType.EXECUTE:
            continue
        command = e.target or ""
        if "qodercli" not in command:
            continue
        for pattern in VAGUE_PATTERNS:
            if re.search(pattern, command):
                findings.append(SIPFinding(
                    sip_type="VAGUE_PROMPT_DRAIN",
                    valence="destructive",
                    event_id=e.event_id,
                    description="Open-ended qodercli prompt without target paths; credit drain risk",
                    evidence={"pattern": pattern, "target": command[:100]},
                ))
                break
    return findings


def run_all_detectors(events: List[Event]) -> List[SIPFinding]:
    """Run all three qodercli-specific detectors."""
    findings = []
    findings.extend(detect_pty_omission(events))
    findings.extend(detect_interactive_blockade(events))
    findings.extend(detect_vague_prompt(events))
    return findings
