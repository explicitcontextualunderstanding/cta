"""
Data models for CTA framework
Defines core data structures for trace analysis
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
import json


class EventType(Enum):
    """Types of events in an execution trace"""
    READ = "read"           # File read
    WRITE = "write"         # File write
    EXECUTE = "execute"     # Command execution
    SEARCH = "search"       # Code search
    REASON = "reason"       # Agent reasoning
    ERROR = "error"         # Error event
    TOOL_CALL = "tool_call" # Generic tool call


class EventOutcome(Enum):
    """Outcome of an event"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class PhaseType(Enum):
    """SWE task execution phases"""
    ORIENTATION = "orientation"      # Understanding project structure
    PLANNING = "planning"            # Strategy planning
    IMPLEMENTATION = "implementation" # Code writing
    VALIDATION = "validation"        # Testing/building
    DEBUGGING = "debugging"          # Error fixing
    FINALIZATION = "finalization"    # Final adjustments


class DivergenceType(Enum):
    """Types of divergence between paired traces.

    The first three are *bilateral*: both with-skill and without-skill agents
    expressed an aligned intent and produced an action window, but the
    actions/targets/outcomes differ.

    ``UNILATERAL_ACTION`` is *asymmetric*: the with-skill agent took an
    action (typically a Write/Edit on a file the baseline never touched)
    that has no aligned counterpart in the without-skill trace at all.
    This is the signature of skill-induced artifact creation -- e.g.
    ``bash-defensive-patterns`` prompting the agent to author a new
    ``test_scripts.bats`` that the baseline never produced. Without this
    type, those cases are silently dropped by the symmetric alignment
    in Module 3 (see plan.md §2.4.2 "case 4: Unilateral Artifact").
    """
    TARGET_MISMATCH = "target_mismatch"           # Different files/targets
    CONTENT_MISMATCH = "content_mismatch"         # Different code changes
    OUTCOME_MISMATCH = "outcome_mismatch"         # Different results
    UNILATERAL_ACTION = "unilateral_action"       # Plus-only action; no minus counterpart


class SIPType(Enum):
    """Skill Influence Pattern types (v2 schema, 5 categories).

    Design rationale (see plan.md §2.5.1):
        - Constructive: PS (Procedural Scaffolding), EP (Edge-case Prompting)
        - Neutral:      RE (Redundant Exploration, merges legacy RR + PE)
        - Destructive:  SA (Surface Anchoring), CB (Concept Bleed)

    Deprecated v1 categories (retained as aliases for back-compat with old
    serialized data, but emit DeprecationWarning when used):
        CONSTRAINT_NARROWING -> merged into PROCEDURAL_SCAFFOLDING
        REDUNDANT_REITERATION -> alias of REDUNDANT_EXPLORATION
        PARALLEL_EXPLORATION  -> alias of REDUNDANT_EXPLORATION
        CONTEXT_DISPLACEMENT  -> dropped (covered by skill `document_length` feature in M5)
    """

    # Constructive
    PROCEDURAL_SCAFFOLDING = "procedural_scaffolding"
    EDGE_CASE_PROMPTING = "edge_case_prompting"

    # Neutral (RE = merged RR + PE)
    REDUNDANT_EXPLORATION = "redundant_exploration"

    # Destructive
    SURFACE_ANCHORING = "surface_anchoring"
    CONCEPT_BLEED = "concept_bleed"

    @classmethod
    def _missing_(cls, value):
        """Handle deprecated v1 category strings for back-compat."""
        import warnings

        legacy_map = {
            "constraint_narrowing": cls.PROCEDURAL_SCAFFOLDING,
            "redundant_reiteration": cls.REDUNDANT_EXPLORATION,
            "parallel_exploration": cls.REDUNDANT_EXPLORATION,
            "context_displacement": None,
        }
        if value in legacy_map:
            mapped = legacy_map[value]
            if mapped is None:
                raise ValueError(
                    f"SIP category '{value}' was removed in v2 schema "
                    f"(see plan.md §2.5.1 for rationale)"
                )
            warnings.warn(
                f"SIP category '{value}' is deprecated; mapping to '{mapped.value}'",
                DeprecationWarning,
                stacklevel=2,
            )
            return mapped
        return None


@dataclass
class Event:
    """Structured event from execution trace"""
    event_id: int
    type: EventType
    target: str                    # File path, command, tool name
    content: str                   # File content, diff, command output
    reasoning: str = ""            # Agent's reasoning before this step
    outcome: EventOutcome = EventOutcome.SUCCESS
    token_count: int = 0
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        d = asdict(self)
        d['type'] = self.type.value
        d['outcome'] = self.outcome.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Event':
        """Create from dictionary"""
        d = d.copy()
        d['type'] = EventType(d['type'])
        d['outcome'] = EventOutcome(d['outcome'])
        return cls(**d)


@dataclass
class Trace:
    """Complete execution trace"""
    trace_id: str
    events: List[Event] = field(default_factory=list)
    task_id: str = ""
    with_skill: bool = False
    temperature: float = 0.0
    run_number: int = 0
    total_tokens: int = 0
    duration_sec: float = 0.0
    final_outcome: bool = False    # pass/fail

    def to_json(self, filepath: str):
        """Save to JSON"""
        data = {
            'trace_id': self.trace_id,
            'task_id': self.task_id,
            'with_skill': self.with_skill,
            'temperature': self.temperature,
            'run_number': self.run_number,
            'total_tokens': self.total_tokens,
            'duration_sec': self.duration_sec,
            'final_outcome': self.final_outcome,
            'events': [e.to_dict() for e in self.events]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> 'Trace':
        """Load from JSON"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        events = [Event.from_dict(e) for e in data.pop('events', [])]
        return cls(events=events, **data)


@dataclass
class Phase:
    """A phase in the execution trace"""
    type: PhaseType
    start_idx: int            # Start event index
    end_idx: int              # End event index (inclusive)
    events: List[Event] = field(default_factory=list)

    @property
    def duration_events(self) -> int:
        """Number of events in this phase"""
        return self.end_idx - self.start_idx + 1


@dataclass
class PhasedTrace:
    """Trace segmented into phases"""
    trace: Trace
    phases: List[Phase] = field(default_factory=list)


@dataclass
class Intent:
    """Extracted intent from agent reasoning"""
    intent_id: int
    text: str                 # Natural language intent description
    phase: PhaseType
    event_indices: List[int]  # Indices of events related to this intent
    embedding: List[float] = field(default_factory=list)

    def cosine_similarity(self, other: 'Intent') -> float:
        """Cosine similarity between embeddings"""
        if not self.embedding or not other.embedding:
            return 0.0

        import numpy as np
        a = np.array(self.embedding)
        b = np.array(other.embedding)

        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.dot(a, b) / (norm_a * norm_b))


@dataclass
class DivergenceRecord:
    """Record of divergence between paired traces"""
    divergence_id: int
    intent_pair: Tuple[Intent, Intent]  # (with_skill_intent, without_skill_intent)
    phase: PhaseType
    actions_plus: List[Event]           # with_skill actions
    actions_minus: List[Event]          # without_skill actions
    divergence_type: DivergenceType
    skill_region: str                   # Most similar region in skill doc
    skill_similarity: float             # Similarity score

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'divergence_id': self.divergence_id,
            'intent_pair': (
                self.intent_pair[0].text,
                self.intent_pair[1].text
            ),
            'phase': self.phase.value,
            'actions_plus_count': len(self.actions_plus),
            'actions_minus_count': len(self.actions_minus),
            'divergence_type': self.divergence_type.value,
            'skill_region': self.skill_region,
            'skill_similarity': self.skill_similarity
        }


@dataclass
class SIPRecord:
    """Skill Influence Pattern record"""
    sip_id: int
    sip_type: SIPType
    divergence_id: int
    task_id: str
    confidence: float         # Classification confidence
    evidence: Dict[str, Any] = field(default_factory=dict)  # Features supporting this SIP

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'sip_id': self.sip_id,
            'sip_type': self.sip_type.value,
            'divergence_id': self.divergence_id,
            'task_id': self.task_id,
            'confidence': self.confidence,
            'evidence': self.evidence
        }


@dataclass
class SkillQualityScore:
    """Skill quality prediction result"""
    skill_id: str
    utility_class: str        # "positive" / "neutral" / "negative"
    probability: Dict[str, float]  # Class probabilities
    feature_importance: Dict[str, float] = field(default_factory=dict)
    recommendation: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'skill_id': self.skill_id,
            'utility_class': self.utility_class,
            'probability': self.probability,
            'feature_importance': self.feature_importance,
            'recommendation': self.recommendation,
            'confidence': self.confidence
        }
