"""
Module 2: Phase Segmentation
Segments execution traces into SWE lifecycle phases using FSM
"""

from typing import List, Dict, Tuple, Optional
from enum import Enum

from .data_models import (
    Event, Trace, Phase, PhasedTrace, PhaseType, EventType
)


class FSMState(Enum):
    """FSM states for phase segmentation"""
    INIT = "init"
    ORIENTATION = "orientation"
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    DEBUGGING = "debugging"
    FINALIZATION = "finalization"


class PhaseSegmenter:
    """
    Segments execution traces into SWE phases using a finite state machine.

    Phases:
    - Orientation: Understanding project structure (read events on config/docs)
    - Planning: Strategy planning (reasoning events with planning keywords)
    - Implementation: Writing code (write events on source files)
    - Validation: Testing/building (execute events with test/build commands)
    - Debugging: Error fixing (error-triggered loops)
    - Finalization: Final adjustments (write events after passing tests)
    """

    # Keywords for planning phase detection
    PLANNING_KEYWORDS = [
        'i will', 'i\'ll', 'the approach', 'steps:', 'strategy',
        'plan', 'solution', 'next', 'first', 'then', 'let me'
    ]

    # Keywords for test/build detection
    TEST_BUILD_KEYWORDS = [
        'test', 'pytest', 'npm test', 'npm run', 'build', 'make',
        'cargo test', 'go test', 'gradle', 'maven', 'pytest',
        'unittest', 'jest', 'mocha', 'jasmine', 'rspec'
    ]

    def __init__(self):
        self.state = FSMState.INIT
        self.phase_sequence: List[Tuple[PhaseType, int, int]] = []

    def segment(self, trace: Trace) -> PhasedTrace:
        """
        Segment a trace into phases.

        Args:
            trace: Execution trace

        Returns:
            PhasedTrace with phase information
        """
        self.state = FSMState.INIT
        self.phase_sequence = []

        events = trace.events
        phases = []

        i = 0
        phase_start = 0

        while i < len(events):
            event = events[i]

            # State machine transitions
            transition = self._get_transition(event, events, i)

            if transition and transition != self.state:
                # Save previous phase if not init
                if self.state != FSMState.INIT and self.state != FSMState.FINALIZATION:
                    phase_type = self._fsm_state_to_phase_type(self.state)
                    if phase_type:
                        phases.append(Phase(
                            type=phase_type,
                            start_idx=phase_start,
                            end_idx=i - 1,
                            events=events[phase_start:i]
                        ))
                    phase_start = i

                # Handle special transitions
                if transition == FSMState.DEBUGGING and self.state != FSMState.VALIDATION:
                    # Entered debugging without validation first (rare)
                    if self.state in (FSMState.IMPLEMENTATION, FSMState.INIT):
                        # Add implicit validation phase
                        pass

                self.state = transition

            i += 1

        # Finalize last phase
        if self.state != FSMState.INIT:
            phase_type = self._fsm_state_to_phase_type(self.state)
            if phase_type:
                phases.append(Phase(
                    type=phase_type,
                    start_idx=phase_start,
                    end_idx=len(events) - 1,
                    events=events[phase_start:]
                ))

        return PhasedTrace(trace=trace, phases=phases)

    def _get_transition(self, event: Event, events: List[Event], idx: int) -> Optional[FSMState]:
        """
        Determine next state based on current event and state.

        Returns:
            Next FSMState or None if no transition
        """
        if self.state == FSMState.INIT:
            if event.type == EventType.READ:
                return FSMState.ORIENTATION
            return None

        elif self.state == FSMState.ORIENTATION:
            if event.type == EventType.REASON and self._has_planning_keywords(event.reasoning):
                return FSMState.PLANNING
            elif event.type == EventType.WRITE:
                return FSMState.IMPLEMENTATION
            return None

        elif self.state == FSMState.PLANNING:
            if event.type == EventType.WRITE:
                return FSMState.IMPLEMENTATION
            return None

        elif self.state == FSMState.IMPLEMENTATION:
            if event.type == EventType.EXECUTE and self._is_test_build_command(event.target):
                return FSMState.VALIDATION
            return None

        elif self.state == FSMState.VALIDATION:
            if event.type == EventType.ERROR or \
               (event.type == EventType.EXECUTE and not self._is_test_build_command(event.target)):
                return FSMState.DEBUGGING
            elif event.type == EventType.WRITE:
                # Could be finalization
                return FSMState.FINALIZATION
            return None

        elif self.state == FSMState.DEBUGGING:
            if event.type == EventType.WRITE:
                return FSMState.IMPLEMENTATION
            return None

        elif self.state == FSMState.FINALIZATION:
            return None

        return None

    def _fsm_state_to_phase_type(self, state: FSMState) -> Optional[PhaseType]:
        """Map FSM state to phase type"""
        mapping = {
            FSMState.ORIENTATION: PhaseType.ORIENTATION,
            FSMState.PLANNING: PhaseType.PLANNING,
            FSMState.IMPLEMENTATION: PhaseType.IMPLEMENTATION,
            FSMState.VALIDATION: PhaseType.VALIDATION,
            FSMState.DEBUGGING: PhaseType.DEBUGGING,
            FSMState.FINALIZATION: PhaseType.FINALIZATION,
        }
        return mapping.get(state)

    def _has_planning_keywords(self, text: str) -> bool:
        """Check if text contains planning keywords"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.PLANNING_KEYWORDS)

    def _is_test_build_command(self, command: str) -> bool:
        """Check if command is a test/build command"""
        cmd_lower = command.lower()
        return any(keyword in cmd_lower for keyword in self.TEST_BUILD_KEYWORDS)

    def segment_batch(self, traces: List[Trace]) -> List[PhasedTrace]:
        """
        Segment multiple traces.

        Args:
            traces: List of traces

        Returns:
            List of phased traces
        """
        return [self.segment(trace) for trace in traces]

    @staticmethod
    def validate_phases(phased_trace: PhasedTrace, min_phase_f1: float = 0.85) -> float:
        """
        Validate phase segmentation quality.

        Args:
            phased_trace: PhasedTrace to validate
            min_phase_f1: Minimum acceptable F1 score

        Returns:
            Validation F1 score
        """
        # This would compare against manually annotated phases
        # For now, return a placeholder
        return 0.0

    def get_phase_sequence(self, phased_trace: PhasedTrace) -> List[str]:
        """Get sequence of phase types"""
        return [phase.type.value for phase in phased_trace.phases]

    def get_phase_statistics(self, phased_trace: PhasedTrace) -> Dict[str, int]:
        """Get statistics about phases"""
        stats = {}
        for phase in phased_trace.phases:
            phase_name = phase.type.value
            if phase_name not in stats:
                stats[phase_name] = 0
            stats[phase_name] += phase.duration_events

        return stats
