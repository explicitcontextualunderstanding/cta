"""
Module 3: Trace Alignment and Divergence Detection
Aligns paired traces (with_skill vs without_skill) and identifies divergences
"""

from typing import List, Dict, Tuple, Optional
import numpy as np
from scipy.spatial.distance import cdist

from .data_models import (
    Event, Trace, PhasedTrace, Phase, Intent, DivergenceRecord,
    DivergenceType, PhaseType
)


class TraceAligner:
    """
    Aligns paired execution traces (with skill vs without skill) and detects divergences.

    Two-level alignment:
    1. Phase-level: DTW alignment of phase sequences
    2. Intent-level: Semantic alignment of agent intents within phases
    """

    def __init__(self, intent_similarity_threshold: float = 0.7):
        """
        Initialize aligner.

        Args:
            intent_similarity_threshold: Threshold for considering intents aligned
        """
        self.intent_similarity_threshold = intent_similarity_threshold
        self.divergence_id_counter = 0

    def align_traces(self, trace_plus: PhasedTrace, trace_minus: PhasedTrace) -> List[DivergenceRecord]:
        """
        Align two paired traces and extract divergences.

        Args:
            trace_plus: with_skill trace
            trace_minus: without_skill trace

        Returns:
            List of DivergenceRecord
        """
        self.divergence_id_counter = 0
        divergences = []

        # Phase-level alignment using DTW
        phase_alignment = self._align_phases(trace_plus.phases, trace_minus.phases)

        # For each aligned phase pair, perform intent-level alignment
        for phase_plus_idx, phase_minus_idx in phase_alignment:
            if phase_plus_idx is None or phase_minus_idx is None:
                continue

            phase_plus = trace_plus.phases[phase_plus_idx]
            phase_minus = trace_minus.phases[phase_minus_idx]

            # Extract intents from each phase
            intents_plus = self._extract_intents(phase_plus, trace_plus.trace, is_plus=True)
            intents_minus = self._extract_intents(phase_minus, trace_minus.trace, is_plus=False)

            # Align intents
            intent_alignment = self._align_intents(intents_plus, intents_minus)

            # For each aligned intent pair, extract divergence
            for intent_plus_idx, intent_minus_idx in intent_alignment:
                if intent_plus_idx is None or intent_minus_idx is None:
                    continue

                intent_plus = intents_plus[intent_plus_idx]
                intent_minus = intents_minus[intent_minus_idx]

                divergence = self._create_divergence_record(
                    intent_plus, intent_minus,
                    trace_plus, trace_minus,
                    phase_plus
                )

                if divergence:
                    divergences.append(divergence)

        return divergences

    def _align_phases(self, phases_plus: List[Phase],
                      phases_minus: List[Phase]) -> List[Tuple[Optional[int], Optional[int]]]:
        """
        Align phase sequences using dynamic time warping.

        Args:
            phases_plus: with_skill phases
            phases_minus: without_skill phases

        Returns:
            List of (plus_idx, minus_idx) pairs
        """
        if not phases_plus or not phases_minus:
            return []

        # Create distance matrix
        n = len(phases_plus)
        m = len(phases_minus)
        dist_matrix = np.zeros((n, m))

        for i in range(n):
            for j in range(m):
                # Distance is 0 if same phase type, 1 otherwise
                dist_matrix[i, j] = 0.0 if phases_plus[i].type == phases_minus[j].type else 1.0

        # DTW alignment
        dtw_cost, dtw_path = self._dtw(dist_matrix)

        # Convert DTW path to alignment pairs
        alignment = []
        for i, j in dtw_path:
            alignment.append((i, j))

        return alignment

    def _dtw(self, dist_matrix: np.ndarray) -> Tuple[float, List[Tuple[int, int]]]:
        """
        Dynamic Time Warping alignment.

        Returns:
            (total_cost, alignment_path)
        """
        n, m = dist_matrix.shape
        dtw_matrix = np.full((n + 1, m + 1), np.inf)
        dtw_matrix[0, 0] = 0

        # Forward pass
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = dist_matrix[i - 1, j - 1]
                dtw_matrix[i, j] = cost + min(
                    dtw_matrix[i - 1, j],
                    dtw_matrix[i, j - 1],
                    dtw_matrix[i - 1, j - 1]
                )

        # Backtrack
        path = []
        i, j = n, m
        while i > 1 or j > 1:
            path.append((i - 1, j - 1))
            candidates = []
            if i > 1 and j > 1:
                candidates.append((i - 1, j - 1, dtw_matrix[i - 1, j - 1]))
            if i > 1:
                candidates.append((i - 1, j, dtw_matrix[i - 1, j]))
            if j > 1:
                candidates.append((i, j - 1, dtw_matrix[i, j - 1]))

            if candidates:
                i, j, _ = min(candidates, key=lambda x: x[2])

        path.reverse()
        return dtw_matrix[n, m], path

    def _extract_intents(self, phase: Phase, trace: Trace, is_plus: bool) -> List[Intent]:
        """
        Extract intents from a phase by analyzing reasoning text.

        Args:
            phase: Phase to extract intents from
            trace: Parent trace (for context)
            is_plus: Whether this is with_skill trace

        Returns:
            List of Intent objects
        """
        intents = []
        intent_id_base = hash((trace.trace_id, phase.type.value)) % 10000

        # Combine reasoning text from events in this phase
        reasoning_texts = []
        for event in phase.events:
            if event.reasoning:
                reasoning_texts.append(event.reasoning)

        full_reasoning = " ".join(reasoning_texts)

        # Split into sentences and create intents
        sentences = full_reasoning.split('.')
        for sent_idx, sent in enumerate(sentences):
            if len(sent.strip()) > 10:  # Skip very short sentences
                intent = Intent(
                    intent_id=intent_id_base + sent_idx,
                    text=sent.strip(),
                    phase=phase.type,
                    event_indices=list(range(phase.start_idx, phase.end_idx + 1)),
                    embedding=self._get_sentence_embedding(sent.strip())
                )
                intents.append(intent)

        return intents

    def _align_intents(self, intents_plus: List[Intent],
                      intents_minus: List[Intent]) -> List[Tuple[Optional[int], Optional[int]]]:
        """
        Align intents using semantic similarity.

        Args:
            intents_plus: with_skill intents
            intents_minus: without_skill intents

        Returns:
            List of (plus_idx, minus_idx) pairs
        """
        if not intents_plus or not intents_minus:
            return []

        alignment = []

        # Greedy matching: for each intent in plus, find best match in minus
        for plus_idx, intent_plus in enumerate(intents_plus):
            best_minus_idx = None
            best_similarity = 0.0

            for minus_idx, intent_minus in enumerate(intents_minus):
                sim = intent_plus.cosine_similarity(intent_minus)
                if sim > best_similarity:
                    best_similarity = sim
                    best_minus_idx = minus_idx

            # Only align if similarity exceeds threshold
            if best_similarity >= self.intent_similarity_threshold and best_minus_idx is not None:
                alignment.append((plus_idx, best_minus_idx))

        return alignment

    def _create_divergence_record(self, intent_plus: Intent, intent_minus: Intent,
                                 trace_plus: PhasedTrace, trace_minus: PhasedTrace,
                                 phase: Phase) -> Optional[DivergenceRecord]:
        """
        Create a divergence record for an intent pair.

        Args:
            intent_plus: with_skill intent
            intent_minus: without_skill intent
            trace_plus: with_skill trace
            trace_minus: without_skill trace
            phase: Phase context

        Returns:
            DivergenceRecord or None
        """
        # Extract actions following each intent
        actions_plus = self._extract_actions_after_intent(trace_plus.trace, intent_plus)
        actions_minus = self._extract_actions_after_intent(trace_minus.trace, intent_minus)

        # Determine divergence type
        divergence_type = self._determine_divergence_type(actions_plus, actions_minus)

        # Find most similar skill region
        skill_region, skill_similarity = self._find_skill_region(intent_plus, trace_plus.trace)

        self.divergence_id_counter += 1

        return DivergenceRecord(
            divergence_id=self.divergence_id_counter,
            intent_pair=(intent_plus, intent_minus),
            phase=phase.type,
            actions_plus=actions_plus,
            actions_minus=actions_minus,
            divergence_type=divergence_type,
            skill_region=skill_region,
            skill_similarity=skill_similarity
        )

    def _extract_actions_after_intent(self, trace: Trace, intent: Intent) -> List[Event]:
        """Extract events after an intent is expressed"""
        if not intent.event_indices:
            return []

        start_idx = max(intent.event_indices) + 1
        # Get next few events (limit to 20)
        end_idx = min(start_idx + 20, len(trace.events))

        return trace.events[start_idx:end_idx]

    def _determine_divergence_type(self, actions_plus: List[Event],
                                   actions_minus: List[Event]) -> DivergenceType:
        """Determine the type of divergence"""
        if not actions_plus or not actions_minus:
            return DivergenceType.TARGET_MISMATCH

        # Compare targets (files/commands)
        targets_plus = {e.target for e in actions_plus if e.target}
        targets_minus = {e.target for e in actions_minus if e.target}

        if targets_plus != targets_minus:
            return DivergenceType.TARGET_MISMATCH

        # Compare content
        content_plus = [e.content for e in actions_plus]
        content_minus = [e.content for e in actions_minus]

        if content_plus != content_minus:
            return DivergenceType.CONTENT_MISMATCH

        # Compare outcomes
        outcomes_plus = {e.outcome for e in actions_plus}
        outcomes_minus = {e.outcome for e in actions_minus}

        if outcomes_plus != outcomes_minus:
            return DivergenceType.OUTCOME_MISMATCH

        # Default
        return DivergenceType.CONTENT_MISMATCH

    def _find_skill_region(self, intent: Intent, trace: Trace) -> Tuple[str, float]:
        """Find most similar region in skill document"""
        # This would connect to the skill document
        # For now, return placeholder
        return ("skill_section_1", 0.5)

    def _get_sentence_embedding(self, text: str) -> List[float]:
        """
        Get sentence embedding.

        Uses a simple hash-based approach for now.
        In practice, would use sentence-transformers or similar.
        """
        # Simple embedding: word frequency vector (very crude approximation)
        words = text.lower().split()
        embedding = np.zeros(100)

        for word in words:
            idx = hash(word) % 100
            embedding[idx] += 1.0 / (len(words) + 1)

        return embedding.tolist()

    def get_divergence_statistics(self, divergences: List[DivergenceRecord]) -> Dict[str, any]:
        """Calculate statistics about divergences"""
        if not divergences:
            return {
                'total_divergences': 0,
                'by_type': {},
                'by_phase': {},
                'avg_skill_similarity': 0.0
            }

        stats = {
            'total_divergences': len(divergences),
            'by_type': {},
            'by_phase': {},
            'avg_skill_similarity': np.mean([d.skill_similarity for d in divergences])
        }

        # Count by divergence type
        for div_type in DivergenceType:
            count = sum(1 for d in divergences if d.divergence_type == div_type)
            if count > 0:
                stats['by_type'][div_type.value] = count

        # Count by phase
        for phase in PhaseType:
            count = sum(1 for d in divergences if d.phase == phase)
            if count > 0:
                stats['by_phase'][phase.value] = count

        return stats
