"""
Module 3: Trace Alignment and Divergence Detection
Aligns paired traces (with_skill vs without_skill) and identifies divergences.

This module is the bridge between raw phased traces and the SIP detector.
Its outputs MUST satisfy two correctness properties for downstream analysis
(especially for Surface Anchoring detection in Module 4):

    (P1) ``DivergenceRecord.actions_plus`` contains the events that the
         with-skill agent actually executed in service of ``intent_plus``,
         not the events of an unrelated downstream phase.
    (P2) ``DivergenceRecord.skill_region`` is the *real* most-similar slice
         of the skill document, not a placeholder string.

The previous implementation violated both: every intent in a phase shared
``event_indices = range(phase.start_idx, phase.end_idx + 1)``, so the
"actions after intent" extraction always pointed past the end of the phase
(returning empty for the final phase, or events from the next phase
otherwise); and ``_find_skill_region`` returned a hardcoded constant.
This rewrite anchors each intent to the specific event whose reasoning text
produced it, and resolves the skill region against the actual SKILL.md
document via TF-IDF cosine similarity.
"""

import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .data_models import (
    Event, EventType, Trace, PhasedTrace, Phase, Intent, DivergenceRecord,
    DivergenceType, PhaseType
)


logger = logging.getLogger(__name__)


# Markdown header regex: matches lines like "# foo", "## bar baz", up to h6.
_MD_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# A reasonably greedy sentence splitter that respects code/markdown punctuation.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'`])|\n{2,}")


class TraceAligner:
    """
    Aligns paired execution traces (with skill vs without skill) and detects divergences.

    Two-level alignment:
    1. Phase-level: DTW alignment of phase sequences
    2. Intent-level: Semantic alignment of agent intents within phases

    The aligner can optionally take a ``skill_doc_provider`` callback so that
    each divergence's ``skill_region`` is populated with the section of the
    actual SKILL.md document that is most similar to the with-skill intent.
    Without the provider, ``skill_region`` falls back to the empty string and
    SA detection in Module 4 will see no signal -- this is the failure mode
    we are explicitly fixing here.
    """

    # Minimum length for a sentence to be considered an intent. Below this we
    # filter out noise like "OK." or "Yes.".
    MIN_INTENT_LEN = 12

    # Maximum number of trailing events used to populate actions_plus /
    # actions_minus for a single intent. This keeps each divergence's window
    # bounded so that Module 4 features remain well-scaled.
    ACTION_WINDOW = 12

    def __init__(
        self,
        intent_similarity_threshold: float = 0.7,
        skill_doc_provider: Optional[Callable[[str], Optional[str]]] = None,
    ):
        """
        Initialize aligner.

        Args:
            intent_similarity_threshold: Threshold for considering intents aligned
            skill_doc_provider: Optional callable ``task_id -> skill_doc_str``.
                When provided, ``align_traces`` will resolve the most-similar
                section of the skill document for each divergence. When None,
                ``skill_region`` will be the empty string.
        """
        self.intent_similarity_threshold = intent_similarity_threshold
        self.skill_doc_provider = skill_doc_provider
        self.divergence_id_counter = 0

        # Per-task cache of (sections, section_embeddings, vectorizer) so we
        # only parse SKILL.md once per task.
        self._skill_index_cache: Dict[
            str, Tuple[List[str], np.ndarray, "TfidfVectorizer"]
        ] = {}

    def align_traces(
        self,
        trace_plus: PhasedTrace,
        trace_minus: PhasedTrace,
        task_id: Optional[str] = None,
    ) -> List[DivergenceRecord]:
        """
        Align two paired traces and extract divergences.

        Args:
            trace_plus: with_skill trace
            trace_minus: without_skill trace
            task_id: Optional task identifier; if provided AND
                ``skill_doc_provider`` is configured, ``skill_region`` will
                be filled with the actual most-similar section of SKILL.md.

        Returns:
            List of DivergenceRecord
        """
        self.divergence_id_counter = 0
        divergences: List[DivergenceRecord] = []

        # Module 2's FSM segmenter requires the first event to be a READ to
        # leave INIT state, so traces that begin with EXECUTE / WRITE (common
        # for shell-tool-driven tasks like ``bash-defensive-patterns``) come
        # back with zero phases. Without a fallback, this loop would never
        # execute and *every* divergence -- bilateral or unilateral -- would
        # be silently dropped. Synthesize a single IMPLEMENTATION phase
        # covering the whole trace so downstream alignment still runs.
        trace_plus = self._ensure_phases(trace_plus)
        trace_minus = self._ensure_phases(trace_minus)

        # Resolve and cache the skill index for this task once.
        skill_index = self._get_skill_index(task_id) if task_id else None

        # Build a shared text vocabulary for intent embeddings. Fitting a
        # single TF-IDF vectorizer on the union of both sides' reasoning
        # gives meaningful cosine similarities (the legacy hash-bucket
        # embedding produced near-random scores).
        intent_corpus = self._collect_reasoning_corpus(trace_plus, trace_minus)
        intent_vectorizer = self._fit_intent_vectorizer(intent_corpus)

        # Set of every WRITE target ever touched by the without-skill agent.
        # Used by the unilateral-action pass below to decide whether a
        # with-skill artifact has *any* counterpart in the baseline trace.
        minus_write_targets = self._collect_write_targets(trace_minus.trace)

        # Phase-level alignment using DTW
        phase_alignment = self._align_phases(trace_plus.phases, trace_minus.phases)

        # Track which with-skill intents successfully aligned to a baseline
        # intent during the symmetric pass. Anything *not* in this set is a
        # candidate for the unilateral-action pass.
        aligned_plus_intent_ids: set = set()

        for phase_plus_idx, phase_minus_idx in phase_alignment:
            if phase_plus_idx is None or phase_minus_idx is None:
                continue

            phase_plus = trace_plus.phases[phase_plus_idx]
            phase_minus = trace_minus.phases[phase_minus_idx]

            intents_plus = self._extract_intents(
                phase_plus, trace_plus.trace, vectorizer=intent_vectorizer
            )
            intents_minus = self._extract_intents(
                phase_minus, trace_minus.trace, vectorizer=intent_vectorizer
            )

            intent_alignment = self._align_intents(intents_plus, intents_minus)

            aligned_plus_idx_in_phase: set = set()
            for intent_plus_idx, intent_minus_idx in intent_alignment:
                if intent_plus_idx is None or intent_minus_idx is None:
                    continue

                intent_plus = intents_plus[intent_plus_idx]
                intent_minus = intents_minus[intent_minus_idx]

                divergence = self._create_divergence_record(
                    intent_plus,
                    intent_minus,
                    trace_plus,
                    trace_minus,
                    phase_plus,
                    skill_index=skill_index,
                )

                if divergence:
                    divergences.append(divergence)

                aligned_plus_idx_in_phase.add(intent_plus_idx)
                aligned_plus_intent_ids.add(id(intent_plus))

            # ----- Unilateral-action pass (per phase) ----- #
            # For each with-skill intent in this phase that had no aligned
            # baseline intent, see whether it produced a Write/Edit on a
            # target the baseline trace never touched. If so, emit a
            # UNILATERAL_ACTION divergence with empty actions_minus.
            divergences.extend(
                self._extract_unilateral_divergences(
                    intents_plus=intents_plus,
                    aligned_plus_idx=aligned_plus_idx_in_phase,
                    trace_plus=trace_plus,
                    minus_write_targets=minus_write_targets,
                    phase=phase_plus,
                    skill_index=skill_index,
                )
            )

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

        # Backtrack from (n, m) until we reach (1, 1), and always include
        # the starting cell. The original `while i > 1 or j > 1` exit check
        # caused the loop to terminate *before* appending the very first
        # alignment cell, which made DTW return an empty path whenever both
        # sides had a single phase (a common case for unilateral-action
        # traces). The corrected loop appends the current cell first, then
        # tries to step back; once we're already at (1, 1) we have no more
        # predecessors to explore and stop.
        path: List[Tuple[int, int]] = []
        i, j = n, m
        while i >= 1 and j >= 1:
            path.append((i - 1, j - 1))
            if i == 1 and j == 1:
                break
            candidates = []
            if i > 1 and j > 1:
                candidates.append((i - 1, j - 1, dtw_matrix[i - 1, j - 1]))
            if i > 1:
                candidates.append((i - 1, j, dtw_matrix[i - 1, j]))
            if j > 1:
                candidates.append((i, j - 1, dtw_matrix[i, j - 1]))
            if not candidates:
                break
            i, j, _ = min(candidates, key=lambda x: x[2])

        path.reverse()
        return dtw_matrix[n, m], path

    def _extract_intents(
        self,
        phase: Phase,
        trace: Trace,
        vectorizer: Optional["TfidfVectorizer"] = None,
    ) -> List[Intent]:
        """
        Extract intents from a phase by analyzing reasoning text.

        Each intent is anchored to the *specific event* whose reasoning text
        produced it, by storing that event's positional index (in
        ``trace.events``) in ``intent.event_indices``. This is what allows
        ``_extract_actions_after_intent`` to return the events that the
        agent ran in service of the intent, rather than the whole tail of
        the phase.

        Args:
            phase: Phase to extract intents from.
            trace: Parent trace (used to resolve positional indices).
            vectorizer: Optional fitted TF-IDF vectorizer for embeddings.

        Returns:
            List of ``Intent`` with anchored ``event_indices``.
        """
        intents: List[Intent] = []
        intent_id_base = hash((trace.trace_id, phase.type.value)) % 10000
        intent_idx = 0

        for offset, event in enumerate(phase.events):
            if not event.reasoning:
                continue

            event_pos = phase.start_idx + offset

            for sent in self._split_into_sentences(event.reasoning):
                sent = sent.strip()
                if len(sent) < self.MIN_INTENT_LEN:
                    continue

                intents.append(
                    Intent(
                        intent_id=intent_id_base + intent_idx,
                        text=sent,
                        phase=phase.type,
                        event_indices=[event_pos],
                        embedding=self._get_sentence_embedding(
                            sent, vectorizer=vectorizer
                        ),
                    )
                )
                intent_idx += 1

        # Fallback: if a phase produced no anchored intents at all but does
        # contain events, emit a single phase-level intent so the phase is
        # not entirely lost from divergence analysis. This is the legacy
        # behavior, preserved for completeness.
        if not intents and phase.events:
            phase_text = " ".join(
                e.reasoning for e in phase.events if e.reasoning
            ).strip()
            if len(phase_text) >= self.MIN_INTENT_LEN:
                intents.append(
                    Intent(
                        intent_id=intent_id_base + intent_idx,
                        text=phase_text[:300],
                        phase=phase.type,
                        event_indices=[phase.start_idx],
                        embedding=self._get_sentence_embedding(
                            phase_text[:300], vectorizer=vectorizer
                        ),
                    )
                )

        return intents

    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """Split a reasoning blob into sentence-like units."""
        if not text:
            return []
        parts = _SENTENCE_SPLIT_RE.split(text)
        # Final fallback: also split on simple periods if no boundaries fired.
        if len(parts) == 1 and "." in text:
            parts = [s for s in text.split(".") if s.strip()]
        return parts

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

    def _create_divergence_record(
        self,
        intent_plus: Intent,
        intent_minus: Intent,
        trace_plus: PhasedTrace,
        trace_minus: PhasedTrace,
        phase: Phase,
        skill_index: Optional[Tuple[List[str], np.ndarray, "TfidfVectorizer"]] = None,
    ) -> Optional[DivergenceRecord]:
        """Create a divergence record for an intent pair.

        Returns None if the divergence is not worth keeping (e.g. both sides
        produced exactly the same window of actions).
        """
        actions_plus = self._extract_actions_after_intent(trace_plus.trace, intent_plus)
        actions_minus = self._extract_actions_after_intent(trace_minus.trace, intent_minus)

        # Skip vacuous divergences where neither side took any action.
        if not actions_plus and not actions_minus:
            return None

        divergence_type = self._determine_divergence_type(actions_plus, actions_minus)
        skill_region, skill_similarity = self._find_skill_region(
            intent_plus, skill_index=skill_index
        )

        self.divergence_id_counter += 1

        return DivergenceRecord(
            divergence_id=self.divergence_id_counter,
            intent_pair=(intent_plus, intent_minus),
            phase=phase.type,
            actions_plus=actions_plus,
            actions_minus=actions_minus,
            divergence_type=divergence_type,
            skill_region=skill_region,
            skill_similarity=skill_similarity,
        )

    @staticmethod
    def _ensure_phases(phased: PhasedTrace) -> PhasedTrace:
        """Guarantee at least one Phase is present.

        When Module 2 returns an empty phase list (e.g. the FSM never left
        INIT because the trace's first event was not a READ), wrap the
        entire event sequence in a single synthetic IMPLEMENTATION phase
        so Module 3's loop still has something to iterate over. The
        behavior is a no-op when the segmenter produced phases normally.
        """
        if phased.phases or not phased.trace.events:
            return phased
        events = phased.trace.events
        synthetic = Phase(
            type=PhaseType.IMPLEMENTATION,
            start_idx=0,
            end_idx=len(events) - 1,
            events=list(events),
        )
        return PhasedTrace(trace=phased.trace, phases=[synthetic])

    # ------------------------------------------------------------------ #
    # Unilateral-action detection
    # ------------------------------------------------------------------ #

    # Event types that count as "artifact-producing" for the purposes of
    # unilateral-action detection. We deliberately exclude EXECUTE, READ,
    # SEARCH, REASON: those produce no durable artifact, and are routinely
    # asymmetric (e.g. one side runs `ls` and the other doesn't) without
    # any skill-level interpretation.
    _UNILATERAL_EVENT_TYPES = {EventType.WRITE}

    @staticmethod
    def _collect_write_targets(trace: Trace) -> set:
        """Return the set of non-empty WRITE/Edit targets in ``trace``.

        Used as the "baseline coverage" set against which with-skill writes
        are checked for unilateral artifact creation.
        """
        targets = set()
        for event in trace.events:
            if event.type in TraceAligner._UNILATERAL_EVENT_TYPES and event.target:
                targets.add(event.target)
        return targets

    def _extract_unilateral_divergences(
        self,
        intents_plus: List[Intent],
        aligned_plus_idx: set,
        trace_plus: PhasedTrace,
        minus_write_targets: set,
        phase: Phase,
        skill_index: Optional[Tuple[List[str], np.ndarray, "TfidfVectorizer"]] = None,
    ) -> List[DivergenceRecord]:
        """Emit ``UNILATERAL_ACTION`` divergences for unaligned plus intents.

        Algorithm:
          1. For each ``intent_plus`` in this phase that did NOT match any
             baseline intent (index not in ``aligned_plus_idx``):
          2. Pull the actions in its window (same helper used for the
             symmetric path) and keep only WRITE events whose ``target`` is
             absent from ``minus_write_targets`` (i.e. the baseline never
             wrote that file).
          3. If at least one such write remains, emit a divergence record
             with ``actions_minus = []`` and a sentinel empty intent so the
             downstream record schema (``intent_pair`` is a 2-tuple) is
             preserved.
          4. Deduplicate by target so we don't emit one divergence per
             redundant edit of the same new file.
        """
        if not intents_plus:
            return []

        out: List[DivergenceRecord] = []
        seen_targets: set = set()

        for plus_idx, intent_plus in enumerate(intents_plus):
            if plus_idx in aligned_plus_idx:
                continue

            window = self._extract_actions_after_intent(
                trace_plus.trace, intent_plus
            )
            unilateral_writes = [
                e
                for e in window
                if e.type in self._UNILATERAL_EVENT_TYPES
                and e.target
                and e.target not in minus_write_targets
                and e.target not in seen_targets
            ]
            if not unilateral_writes:
                continue

            for e in unilateral_writes:
                seen_targets.add(e.target)

            skill_region, skill_similarity = self._find_skill_region(
                intent_plus, skill_index=skill_index
            )

            sentinel_intent = Intent(
                intent_id=-1,
                text="",
                phase=phase.type,
                event_indices=[],
                embedding=[],
            )

            self.divergence_id_counter += 1
            out.append(
                DivergenceRecord(
                    divergence_id=self.divergence_id_counter,
                    intent_pair=(intent_plus, sentinel_intent),
                    phase=phase.type,
                    actions_plus=unilateral_writes,
                    actions_minus=[],
                    divergence_type=DivergenceType.UNILATERAL_ACTION,
                    skill_region=skill_region,
                    skill_similarity=skill_similarity,
                )
            )

        return out

    def _extract_actions_after_intent(self, trace: Trace, intent: Intent) -> List[Event]:
        """Extract the events the agent executed *in service of* the intent.

        Each intent is anchored to the positional index of the event that
        produced it (see ``_extract_intents``). The "actions after intent"
        are the next ``ACTION_WINDOW`` events in the trace. We include the
        anchor event itself, because for tool-call style traces the anchor
        event *is* the action that the reasoning is announcing (e.g. a
        ``write`` event preceded by reasoning "Now I'll create the
        controller").
        """
        if not intent.event_indices:
            return []

        anchor_pos = max(intent.event_indices)
        start_idx = max(0, anchor_pos)
        end_idx = min(start_idx + self.ACTION_WINDOW, len(trace.events))
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

    # ------------------------------------------------------------------ #
    # Skill-region resolution
    # ------------------------------------------------------------------ #

    def _get_skill_index(
        self, task_id: str
    ) -> Optional[Tuple[List[str], np.ndarray, "TfidfVectorizer"]]:
        """Build (or fetch from cache) a TF-IDF index over skill sections.

        Returns (sections, section_vectors, fitted_vectorizer), or None if no
        skill document is reachable for ``task_id``.
        """
        if task_id in self._skill_index_cache:
            return self._skill_index_cache[task_id]

        if self.skill_doc_provider is None:
            return None

        try:
            skill_doc = self.skill_doc_provider(task_id)
        except Exception as exc:
            logger.debug("skill_doc_provider failed for %s: %s", task_id, exc)
            return None

        if not skill_doc:
            return None

        sections = self._split_skill_into_sections(skill_doc)
        if not sections:
            return None

        # Use sklearn's TfidfVectorizer on the union of sections + a placeholder
        # so that single-section skills still produce a valid IDF.
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(
            lowercase=True,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_-]{1,}\b",
            max_features=4096,
        )
        try:
            section_vectors = vectorizer.fit_transform(sections).toarray()
        except ValueError:
            # Empty vocabulary (e.g. all sections are punctuation).
            return None

        index = (sections, section_vectors, vectorizer)
        self._skill_index_cache[task_id] = index
        return index

    @staticmethod
    def _split_skill_into_sections(skill_doc: str) -> List[str]:
        """Split a SKILL.md into sections at markdown headers.

        Each section is the header line plus the body text up to (but not
        including) the next header of any level. Code blocks are kept in
        place. If no headers exist, the entire document is returned as a
        single section.
        """
        if not skill_doc:
            return []

        # Find header positions; if none, return the whole doc.
        header_positions = [
            (m.start(), m.group(0)) for m in _MD_HEADER_RE.finditer(skill_doc)
        ]
        if not header_positions:
            return [skill_doc.strip()]

        sections: List[str] = []
        # Pre-header preamble (before the first header) is its own section.
        if header_positions[0][0] > 0:
            preamble = skill_doc[: header_positions[0][0]].strip()
            if preamble:
                sections.append(preamble)

        for i, (pos, _header_line) in enumerate(header_positions):
            end = (
                header_positions[i + 1][0]
                if i + 1 < len(header_positions)
                else len(skill_doc)
            )
            section = skill_doc[pos:end].strip()
            if section:
                sections.append(section)
        return sections

    def _find_skill_region(
        self,
        intent: Intent,
        skill_index: Optional[
            Tuple[List[str], np.ndarray, "TfidfVectorizer"]
        ] = None,
    ) -> Tuple[str, float]:
        """Find the section of SKILL.md most similar to the given intent.

        Returns a (section_text, cosine_similarity) pair. When no skill index
        is available, returns ("", 0.0) so downstream code can detect the
        absence (Module 4's SA detector treats empty ``skill_region`` as
        "no SA evidence available", which is the correct behavior).
        """
        if skill_index is None:
            return ("", 0.0)

        sections, section_vectors, vectorizer = skill_index
        if not sections:
            return ("", 0.0)

        try:
            intent_vec = vectorizer.transform([intent.text]).toarray()[0]
        except Exception:
            return ("", 0.0)

        norm_intent = np.linalg.norm(intent_vec)
        if norm_intent == 0.0:
            return ("", 0.0)

        # Cosine similarity against each section.
        norms_sec = np.linalg.norm(section_vectors, axis=1)
        denom = norms_sec * norm_intent
        denom[denom == 0] = 1.0  # avoid division by zero
        sims = (section_vectors @ intent_vec) / denom

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        return (sections[best_idx], best_sim)

    # ------------------------------------------------------------------ #
    # Embeddings
    # ------------------------------------------------------------------ #

    def _collect_reasoning_corpus(
        self, trace_plus: PhasedTrace, trace_minus: PhasedTrace
    ) -> List[str]:
        """Collect all non-empty reasoning blobs from both traces."""
        corpus: List[str] = []
        for trace in (trace_plus.trace, trace_minus.trace):
            for event in trace.events:
                if event.reasoning:
                    for sent in self._split_into_sentences(event.reasoning):
                        sent = sent.strip()
                        if len(sent) >= self.MIN_INTENT_LEN:
                            corpus.append(sent)
        return corpus

    def _fit_intent_vectorizer(
        self, corpus: List[str]
    ) -> Optional["TfidfVectorizer"]:
        """Fit a TF-IDF vectorizer on the per-pair reasoning corpus.

        Falls back to None on empty corpus, in which case
        ``_get_sentence_embedding`` uses a deterministic hash bag-of-words.
        """
        if not corpus:
            return None
        from sklearn.feature_extraction.text import TfidfVectorizer

        vectorizer = TfidfVectorizer(
            lowercase=True,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_-]{1,}\b",
            max_features=2048,
        )
        try:
            vectorizer.fit(corpus)
        except ValueError:
            return None
        return vectorizer

    def _get_sentence_embedding(
        self,
        text: str,
        vectorizer: Optional["TfidfVectorizer"] = None,
    ) -> List[float]:
        """Embed a sentence to a fixed-length vector for cosine alignment.

        Preferred path: TF-IDF transform using a vectorizer fitted on this
        pair's reasoning corpus. This produces meaningful cosine
        similarities, which is critical for the ``intent_similarity_threshold``
        gate in ``_align_intents``.

        Fallback path: deterministic 100-dim hashed bag-of-words. This is
        only used when no vectorizer is available (e.g. both traces have
        empty reasoning text), and reproduces the legacy behavior so the
        pipeline never crashes.
        """
        if vectorizer is not None:
            try:
                vec = vectorizer.transform([text]).toarray()[0]
                norm = np.linalg.norm(vec)
                if norm > 0:
                    return (vec / norm).tolist()
            except Exception:
                pass

        # Fallback: hashed bag-of-words.
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
