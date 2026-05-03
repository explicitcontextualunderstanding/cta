"""
Module 4: Skill Influence Pattern Detection and Outcome Analysis

Implements the v2 SIP taxonomy (5 categories):
    Constructive: PS (Procedural Scaffolding), EP (Edge-case Prompting)
    Neutral:      RE (Redundant Exploration)
    Destructive:  SA (Surface Anchoring), CB (Concept Bleed)

See plan.md §2.5.1 for the design rationale and the v1 -> v2 migration notes.
"""

import json
import re
from typing import List, Dict, Tuple, Any, Optional, Set
from pathlib import Path

import numpy as np

from .data_models import (
    DivergenceRecord,
    DivergenceType,
    SIPRecord,
    SIPType,
    Event,
    EventType,
)


# --------------------------------------------------------------------------- #
# Surface Anchoring detection helpers
# --------------------------------------------------------------------------- #

# Patterns that indicate a "version-like" or "literal-config-like" token. We
# consider these tokens high-risk for Surface Anchoring because copying them
# verbatim from a skill template is the dominant failure mode reported in
# SWE-Skills-Bench (Han et al., 2026).
_VERSION_RE = re.compile(
    r"""
    \b(
        \d+\.\d+(?:\.\d+){0,2}            # 1.2 / 1.2.3 / 1.2.3.4
        | v\d+(?:\.\d+){0,3}              # v1 / v1.2.3
        | \d+\.\d+\.\d+[-+][\w.]+         # 1.2.3-rc1 / 1.2.3+build5
    )\b
    """,
    re.VERBOSE,
)

_LITERAL_PATTERNS = [
    re.compile(r"\b[a-zA-Z_][\w-]*[/.][\w./_-]+\b"),     # paths / dotted module ids
    re.compile(r"['\"][^'\"\n]{4,80}['\"]"),             # string literals
    re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b"),               # SHOUT_CASE constants
]

# Skill-region tokens shorter than this are too generic (e.g. "import",
# "return") and would cause false positives.
_MIN_LITERAL_LEN = 6

# n-gram size for the literal-token n-gram match used as a secondary signal.
_NGRAM_N = 4


def _extract_literal_candidates(text: str) -> Set[str]:
    """Extract literal tokens from text that are plausible SA copy-targets.

    Returns the set of unique candidate strings. Filters out tokens shorter
    than ``_MIN_LITERAL_LEN`` to avoid generic keywords.
    """
    if not text:
        return set()

    candidates: Set[str] = set()

    for m in _VERSION_RE.finditer(text):
        candidates.add(m.group(0))

    for pat in _LITERAL_PATTERNS:
        for m in pat.finditer(text):
            tok = m.group(0).strip("'\"")
            if len(tok) >= _MIN_LITERAL_LEN:
                candidates.add(tok)

    return candidates


def _ngrams(tokens: List[str], n: int) -> Set[Tuple[str, ...]]:
    """Return the set of n-grams from a token list."""
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _word_tokens(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #


class SIPDetector:
    """Detects Skill Influence Patterns (v2: 5 categories).

    The detector exposes two parallel paths:
        * Path A (rule-based, this class): cheap, fully deterministic, used
          for large-scale screening over all ~3K divergences.
        * Path B (LLM-as-classifier, separate module): higher quality on
          ambiguous cases; not implemented here.

    Each rule-based detector returns a confidence score in [0, 1]. A SIP is
    emitted only when its confidence exceeds a per-type threshold.
    """

    # Per-type emission thresholds. Tuned against pilot data (49 tasks).
    # Note: thresholds are intentionally lower for RE because Module 3 in
    # the current pipeline often returns empty ``actions_plus`` for some
    # divergences, which deflates content/target features. Once Module 3 is
    # upgraded to surface real actions on both sides, these can be retuned.
    THRESHOLDS = {
        SIPType.PROCEDURAL_SCAFFOLDING: 0.55,
        SIPType.EDGE_CASE_PROMPTING: 0.50,
        SIPType.REDUNDANT_EXPLORATION: 0.45,
        SIPType.SURFACE_ANCHORING: 0.40,
        SIPType.CONCEPT_BLEED: 0.55,
    }

    def __init__(
        self,
        annotation_file: Optional[str] = None,
        skill_doc_provider=None,
    ):
        """Initialize the detector.

        Args:
            annotation_file: Optional path to gold-set annotations (used by
                ``train_classifier`` for supervised refinement).
            skill_doc_provider: Optional callable ``task_id -> skill_doc_str``
                that returns the full skill document. Required for the SA
                detector's literal n-gram match against skill templates.
        """
        self.annotation_file = annotation_file
        self.manual_annotations: Dict[str, Any] = {}
        self.classifier = None
        self.skill_doc_provider = skill_doc_provider

        # Cache: task_id -> (literal_set, ngram_set) extracted from skill doc.
        self._skill_literal_cache: Dict[str, Tuple[Set[str], Set[Tuple[str, ...]]]] = {}

        if annotation_file and Path(annotation_file).exists():
            self._load_annotations(annotation_file)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def detect(
        self,
        divergence: DivergenceRecord,
        task_id: Optional[str] = None,
    ) -> List[SIPRecord]:
        """Classify a single divergence into one or more SIPs.

        Args:
            divergence: The divergence record to classify.
            task_id: Optional task identifier. When provided, the SA detector
                will pull the full skill document via ``skill_doc_provider``
                for literal-template matching.

        Returns:
            A list of ``SIPRecord``; empty if no SIP fires above its threshold.
        """
        features = self._extract_features(divergence, task_id=task_id)
        scored = self._rule_based_detection(divergence, features, task_id=task_id)

        sip_records: List[SIPRecord] = []
        sip_id = 0
        for sip_type, confidence in scored.items():
            if confidence < self.THRESHOLDS.get(sip_type, 0.5):
                continue
            sip_id += 1
            sip_records.append(
                SIPRecord(
                    sip_id=sip_id,
                    sip_type=sip_type,
                    divergence_id=divergence.divergence_id,
                    task_id=task_id or divergence.intent_pair[0].text[:30],
                    confidence=float(confidence),
                    evidence=features,
                )
            )
        return sip_records

    def batch_detect(
        self,
        divergences: List[DivergenceRecord],
        task_id: Optional[str] = None,
    ) -> List[SIPRecord]:
        """Detect SIPs across a list of divergences."""
        all_sips: List[SIPRecord] = []
        for div in divergences:
            all_sips.extend(self.detect(div, task_id=task_id))
        return all_sips

    # --------------------------------------------------------------------- #
    # Feature extraction
    # --------------------------------------------------------------------- #

    def _extract_features(
        self,
        divergence: DivergenceRecord,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        f: Dict[str, Any] = {}

        f["num_events_plus"] = len(divergence.actions_plus)
        f["num_events_minus"] = len(divergence.actions_minus)
        f["event_count_ratio"] = (len(divergence.actions_plus) + 1) / (
            len(divergence.actions_minus) + 1
        )

        types_plus = [e.type for e in divergence.actions_plus]
        types_minus = [e.type for e in divergence.actions_minus]

        f["write_events_plus"] = types_plus.count(EventType.WRITE)
        f["write_events_minus"] = types_minus.count(EventType.WRITE)
        f["execute_events_plus"] = types_plus.count(EventType.EXECUTE)
        f["execute_events_minus"] = types_minus.count(EventType.EXECUTE)
        f["error_events_plus"] = types_plus.count(EventType.ERROR)
        f["error_events_minus"] = types_minus.count(EventType.ERROR)

        targets_plus = {e.target for e in divergence.actions_plus if e.target}
        targets_minus = {e.target for e in divergence.actions_minus if e.target}
        intersection = len(targets_plus & targets_minus)
        union = len(targets_plus | targets_minus)
        f["target_jaccard"] = intersection / union if union else 0.0
        f["new_targets_in_plus"] = len(targets_plus - targets_minus)

        content_plus = "".join(e.content for e in divergence.actions_plus)
        content_minus = "".join(e.content for e in divergence.actions_minus)
        f["content_similarity"] = self._string_similarity(content_plus, content_minus)
        f["content_len_plus"] = len(content_plus)
        f["content_len_minus"] = len(content_minus)

        f["skill_similarity"] = divergence.skill_similarity
        f["intent_similarity"] = divergence.intent_pair[0].cosine_similarity(
            divergence.intent_pair[1]
        )

        # SA-specific features (computed if a skill doc is reachable).
        sa_signals = self._compute_sa_signals(divergence, task_id=task_id)
        f.update(sa_signals)

        # EP-specific: count edge-case keyword occurrences in with-skill writes.
        f["edge_case_keyword_count_plus"] = self._count_edge_case_keywords(
            divergence.actions_plus
        )
        f["edge_case_keyword_count_minus"] = self._count_edge_case_keywords(
            divergence.actions_minus
        )

        return f

    # --------------------------------------------------------------------- #
    # Rule-based detection
    # --------------------------------------------------------------------- #

    def _rule_based_detection(
        self,
        divergence: DivergenceRecord,
        features: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> Dict[SIPType, float]:
        """Score each of the 5 SIPs based on extracted features."""
        scores: Dict[SIPType, float] = {}

        is_unilateral = divergence.divergence_type == DivergenceType.UNILATERAL_ACTION

        # ---------------- Procedural Scaffolding (PS) ---------------- #
        # Heuristic: with-skill produces *more* implementation events whose
        # content aligns with the skill region (the skill provided steps the
        # baseline lacked). Signals:
        #   - more write/execute events on the with-skill side
        #   - moderate-to-high skill_similarity (skill content is being used)
        #   - similar set of targets (same task scope, more steps)
        #
        # PS is intentionally skipped for UNILATERAL_ACTION divergences:
        # the symmetric features (event_count_ratio, target_jaccard,
        # write_events_minus) are structurally biased toward firing whenever
        # the baseline window is empty, so PS would systematically over-fire.
        # PS is about *more steps in service of the same intent*, not about
        # *creating an artifact the baseline never produced* -- the latter is
        # the EP / CB regime, handled below.
        if not is_unilateral:
            ps_score = 0.0
            if features["event_count_ratio"] > 1.3:
                ps_score += 0.3
            if features["skill_similarity"] >= 0.4:
                ps_score += 0.25
            if features["target_jaccard"] >= 0.4:
                ps_score += 0.2
            if features["write_events_plus"] > features["write_events_minus"]:
                ps_score += 0.15
            if ps_score > 0:
                scores[SIPType.PROCEDURAL_SCAFFOLDING] = min(ps_score, 0.95)

        # ---------------- Edge-case Prompting (EP) ---------------- #
        # Heuristic: with-skill writes contain more edge-case-handling
        # constructs (try/except, null check, version branch).
        #
        # For UNILATERAL_ACTION divergences EP is the dominant SIP: the skill
        # prompted the agent to author an artifact (typically a test or
        # defensive check) that the baseline never produced. We give EP a
        # baseline boost in that case, then add the keyword bonus on top --
        # the artifact still has to *contain* relevant guard-rail content
        # for high confidence.
        ep_score = 0.0
        delta_kw = (
            features["edge_case_keyword_count_plus"]
            - features["edge_case_keyword_count_minus"]
        )
        if is_unilateral:
            # Base evidence: the with-skill agent created an artifact on a
            # target the baseline never touched, which is the structural
            # signature of EP / "Unilateral Artifact" (plan.md §2.4.2 case 4).
            # The base alone clears the EP threshold (0.50) so that artifacts
            # without explicit guard-rail keywords (e.g. defensive shell
            # scripts that use `set -e` rather than try/except) still fire.
            ep_score += 0.55
            if features["edge_case_keyword_count_plus"] >= 1:
                ep_score += 0.15
            if features["edge_case_keyword_count_plus"] >= 3:
                ep_score += 0.15
            # If the new artifact is also tied back to a specific skill
            # section we have stronger provenance than the noise floor.
            if features["skill_similarity"] >= 0.30:
                ep_score += 0.10
        else:
            if delta_kw >= 1:
                ep_score += 0.4
            if delta_kw >= 3:
                ep_score += 0.2
            if features["write_events_plus"] > features["write_events_minus"]:
                ep_score += 0.2
            if features["target_jaccard"] >= 0.5:
                ep_score += 0.1
        if ep_score > 0:
            scores[SIPType.EDGE_CASE_PROMPTING] = min(ep_score, 0.95)

        # ---------------- Redundant Exploration (RE) ---------------- #
        # Heuristic: high intent similarity AND content largely equivalent,
        # but with-skill spent more events to get there (i.e. skill triggered
        # a detour that returned to the same answer).
        re_score = 0.0
        if features["intent_similarity"] >= 0.75:
            re_score += 0.3
        if features["content_similarity"] >= 0.7:
            re_score += 0.25
        if features["event_count_ratio"] >= 1.2:
            re_score += 0.2
        if features["target_jaccard"] >= 0.6:
            re_score += 0.15
        if re_score > 0:
            scores[SIPType.REDUNDANT_EXPLORATION] = min(re_score, 0.95)

        # ---------------- Surface Anchoring (SA) ---------------- #
        # Primary detector: literal-token / n-gram match between the *skill
        # document* and the *with-skill write events*, that does NOT appear in
        # the without-skill writes. This is the SA signature defined in
        # plan.md §2.5.1.
        sa_score = self._score_surface_anchoring(features)
        if sa_score > 0:
            scores[SIPType.SURFACE_ANCHORING] = min(sa_score, 0.95)

        # ---------------- Concept Bleed (CB) ---------------- #
        # Heuristic: the with-skill agent introduces *substantially* more
        # new targets / writes than the baseline AND the extras are
        # traceable to the skill via skill_similarity. CB is the
        # destructive failure mode where a broad skill convinces the agent
        # to add irrelevant content, so we need both:
        #   (a) a structural signal: more writes / more targets touched
        #   (b) a provenance signal: the matched skill region is
        #       genuinely similar (skill_similarity well above the noise
        #       floor of TF-IDF on small corpora).
        # A divergence with merely-different filenames but no extra writes
        # and no strong skill match is more likely PS or RE than CB.
        cb_score = 0.0
        # Provenance signal (gate). With small TF-IDF corpora most pairs
        # land in [0.05, 0.25]; a real CB case shows alignment to a
        # *specific* skill section, so we ask for >= 0.30.
        if features["skill_similarity"] < 0.30:
            scores  # noop placeholder; keep CB at 0
        else:
            if features["new_targets_in_plus"] >= 2:
                cb_score += 0.30
            if features["new_targets_in_plus"] >= 4:
                cb_score += 0.15
            if features["target_jaccard"] < 0.30:
                cb_score += 0.15
            if features["num_events_plus"] >= features["num_events_minus"] + 4:
                cb_score += 0.20
            if features["skill_similarity"] >= 0.50:
                cb_score += 0.15
            # Hard structural gate: CB needs at least one extra new target
            # to be credible; pure rewriting is not concept bleed.
            if features["new_targets_in_plus"] < 1:
                cb_score = 0.0
        if cb_score > 0:
            scores[SIPType.CONCEPT_BLEED] = min(cb_score, 0.95)

        return scores

    # --------------------------------------------------------------------- #
    # Surface Anchoring core logic
    # --------------------------------------------------------------------- #

    def _compute_sa_signals(
        self,
        divergence: DivergenceRecord,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract SA-specific evidence features.

        Returns a dict with the following keys (all numeric or list-of-str):
            sa_literal_matches:        list of literals copied verbatim from
                                       skill region into with-skill writes
                                       but absent from without-skill writes
            sa_literal_match_count:    int, len(sa_literal_matches)
            sa_skill_doc_literal_count: literals matched against the *full*
                                       skill document (broader than region)
            sa_ngram_overlap_ratio:    fraction of with-skill word-4-grams
                                       that also appear in the skill region
                                       AND are absent from without-skill text
            sa_evidence_quote:         a representative literal (for logging)
        """
        # 1) Build the union of "skill text" we'll match against.
        skill_texts: List[str] = []
        if divergence.skill_region:
            skill_texts.append(divergence.skill_region)

        full_skill_doc = None
        if task_id and self.skill_doc_provider is not None:
            full_skill_doc = self._get_skill_doc(task_id)
            if full_skill_doc:
                skill_texts.append(full_skill_doc)

        skill_blob = "\n".join(skill_texts)

        # 2) Concatenate with-skill / without-skill written content. We only
        #    look at WRITE events, because SA is about *generated artifacts*,
        #    not about agent reasoning.
        plus_write_content = "\n".join(
            e.content for e in divergence.actions_plus if e.type == EventType.WRITE
        )
        minus_write_content = "\n".join(
            e.content for e in divergence.actions_minus if e.type == EventType.WRITE
        )

        # 3) Literal-token match: tokens that appear in skill AND with-skill
        #    writes but NOT in without-skill writes are SA candidates.
        skill_literals = _extract_literal_candidates(skill_blob)
        plus_literals = _extract_literal_candidates(plus_write_content)
        minus_literals = _extract_literal_candidates(minus_write_content)

        copied = (skill_literals & plus_literals) - minus_literals

        # 4) Region-only count (stricter signal): same as above but limited to
        #    the divergence's own skill_region rather than the full document.
        if divergence.skill_region:
            region_literals = _extract_literal_candidates(divergence.skill_region)
            region_copied = (region_literals & plus_literals) - minus_literals
        else:
            region_copied = set()

        # 5) n-gram overlap: catches multi-word phrases (e.g. specific config
        #    snippets) even when single tokens are too short to be candidates.
        skill_grams = _ngrams(_word_tokens(skill_blob), _NGRAM_N)
        plus_grams = _ngrams(_word_tokens(plus_write_content), _NGRAM_N)
        minus_grams = _ngrams(_word_tokens(minus_write_content), _NGRAM_N)

        copied_grams = (skill_grams & plus_grams) - minus_grams
        ngram_overlap_ratio = (
            len(copied_grams) / len(plus_grams) if plus_grams else 0.0
        )

        # Pick a representative quote for the evidence log.
        evidence_quote = ""
        if region_copied:
            evidence_quote = sorted(region_copied, key=len, reverse=True)[0]
        elif copied:
            evidence_quote = sorted(copied, key=len, reverse=True)[0]
        elif copied_grams:
            evidence_quote = " ".join(next(iter(copied_grams)))

        return {
            "sa_literal_matches": sorted(copied),
            "sa_literal_match_count": len(copied),
            "sa_region_literal_match_count": len(region_copied),
            "sa_skill_doc_literal_count": len(skill_literals),
            "sa_ngram_overlap_count": len(copied_grams),
            "sa_ngram_overlap_ratio": float(ngram_overlap_ratio),
            "sa_evidence_quote": evidence_quote,
        }

    def _score_surface_anchoring(self, features: Dict[str, Any]) -> float:
        """Combine SA signals into a single confidence score in [0, 1].

        Three signals contribute:
            (a) Full-skill-doc literal matches: tokens like specific version
                numbers, paths, or class names that appear in SKILL.md AND
                in the with-skill writes but NOT in the baseline writes.
                This is the *primary* SA signature and is independent of
                whether Module 3 found the right skill region.
            (b) Region-restricted literal matches: stronger precision when
                Module 3's TF-IDF section alignment happens to be correct.
            (c) n-gram overlap: catches multi-word literal copies (e.g.
                a config snippet, a 3-step shell command sequence).

        We weight (a) most heavily because Module 3's region alignment is
        fragile on small reasoning corpora, and the full-doc literal-set
        match is what actually identifies "the agent copied a value out of
        SKILL.md verbatim".
        """
        score = 0.0

        region_hits = features.get("sa_region_literal_match_count", 0)
        all_hits = features.get("sa_literal_match_count", 0)
        ngram_count = features.get("sa_ngram_overlap_count", 0)
        ngram_ratio = features.get("sa_ngram_overlap_ratio", 0.0)

        # Full-doc literal copies are the primary SA signal.
        if all_hits >= 1:
            score += 0.35
        if all_hits >= 3:
            score += 0.20
        if all_hits >= 6:
            score += 0.10

        # Region-restricted matches add precision when available.
        if region_hits >= 1:
            score += 0.15
        if region_hits >= 3:
            score += 0.10

        # n-gram phrase copies add an independent line of evidence.
        if ngram_count >= 2:
            score += 0.10
        if ngram_ratio >= 0.05:
            score += 0.10
        if ngram_ratio >= 0.15:
            score += 0.10

        # Skill_similarity is a useful prior but should not by itself trigger
        # SA (otherwise we'd over-fire on legitimate PS).
        if features.get("skill_similarity", 0.0) >= 0.4 and (
            region_hits or all_hits
        ):
            score += 0.05

        return score

    def _get_skill_doc(self, task_id: str) -> Optional[str]:
        """Resolve the full skill document for a task, with caching."""
        if task_id in self._skill_literal_cache:
            # Already resolved (possibly None); we cache only the literals,
            # not the raw doc. Use a sentinel re-fetch policy: the literals
            # cache is sufficient for our use, so just trigger a recomputation.
            pass
        if self.skill_doc_provider is None:
            return None
        try:
            return self.skill_doc_provider(task_id)
        except Exception:
            return None

    # --------------------------------------------------------------------- #
    # Edge-case Prompting helpers
    # --------------------------------------------------------------------- #

    _EDGE_CASE_PATTERNS = [
        re.compile(r"\btry\s*[:{(]"),
        re.compile(r"\bexcept\b"),
        re.compile(r"\bcatch\s*\("),
        re.compile(r"\bif\s+[^:\n]{0,40}\b(is\s+None|== ?None|!= ?None)\b"),
        re.compile(r"\bnull\s*(check|guard)\b", re.IGNORECASE),
        re.compile(r"\bassert\b"),
        re.compile(r"\braise\s+\w+"),
        re.compile(r"\bedge\s*case\b", re.IGNORECASE),
        re.compile(r"\bboundary\b", re.IGNORECASE),
    ]

    @classmethod
    def _count_edge_case_keywords(cls, events: List[Event]) -> int:
        total = 0
        for e in events:
            if e.type != EventType.WRITE:
                continue
            for pat in cls._EDGE_CASE_PATTERNS:
                total += len(pat.findall(e.content))
        return total

    # --------------------------------------------------------------------- #
    # Misc utilities
    # --------------------------------------------------------------------- #

    @staticmethod
    def _string_similarity(s1: str, s2: str) -> float:
        """Cheap character-level similarity (kept for back-compat).

        Note: this is *not* an alignment-quality similarity, just a sanity
        check used by the RE detector.
        """
        if not s1 or not s2:
            return 0.0
        # Use Jaccard on word sets to avoid the position-sensitive bug of the
        # original zip-based implementation (which returned ~0 for permuted
        # but otherwise identical content).
        w1 = set(_word_tokens(s1))
        w2 = set(_word_tokens(s2))
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)

    def _load_annotations(self, filepath: str):
        with open(filepath, "r") as f:
            self.manual_annotations = json.load(f)

    # --------------------------------------------------------------------- #
    # Optional supervised refinement (used only when a gold set is available)
    # --------------------------------------------------------------------- #

    def train_classifier(
        self, annotated_divergences: List[Tuple[DivergenceRecord, SIPType]]
    ):
        """Fit a multinomial logistic regression on the gold set."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        X, y = [], []
        for div, sip in annotated_divergences:
            feats = self._extract_features(div)
            X.append(self._features_to_vector(feats))
            y.append(sip.value)

        X = np.array(X)
        y = np.array(y)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        self.classifier = LogisticRegression(
            multi_class="multinomial",
            max_iter=1000,
            random_state=42,
        )
        self.classifier.fit(X_scaled, y)

    def _features_to_vector(self, features: Dict[str, Any]) -> np.ndarray:
        keys = [
            "event_count_ratio",
            "write_events_plus",
            "execute_events_plus",
            "error_events_plus",
            "target_jaccard",
            "new_targets_in_plus",
            "content_similarity",
            "skill_similarity",
            "intent_similarity",
            "edge_case_keyword_count_plus",
            "sa_literal_match_count",
            "sa_region_literal_match_count",
            "sa_ngram_overlap_ratio",
        ]
        return np.array([float(features.get(k, 0.0)) for k in keys])

    # --------------------------------------------------------------------- #
    # Aggregation / reporting
    # --------------------------------------------------------------------- #

    def analyze_outcome_relationship(
        self,
        sips: List[SIPRecord],
        outcomes_plus: List[bool],
        outcomes_minus: List[bool],
    ) -> Dict[str, Any]:
        """Aggregate SIP statistics, grouped by SIP type."""
        analysis: Dict[str, Any] = {}
        for sip_type in SIPType:
            of_type = [s for s in sips if s.sip_type == sip_type]
            if not of_type:
                continue
            analysis[sip_type.value] = {
                "count": len(of_type),
                "avg_confidence": float(np.mean([s.confidence for s in of_type])),
                "category": self.categorize_sip(sip_type),
            }
        return analysis

    def get_sip_statistics(self, sips: List[SIPRecord]) -> Dict[str, Any]:
        if not sips:
            return {"total_sips": 0, "by_type": {}}

        stats = {
            "total_sips": len(sips),
            "by_type": {},
            "avg_confidence": float(np.mean([s.confidence for s in sips])),
        }
        for sip_type in SIPType:
            of_type = [s for s in sips if s.sip_type == sip_type]
            if of_type:
                stats["by_type"][sip_type.value] = {
                    "count": len(of_type),
                    "avg_confidence": float(np.mean([s.confidence for s in of_type])),
                    "category": self.categorize_sip(sip_type),
                }
        return stats

    @staticmethod
    def categorize_sip(sip_type: SIPType) -> str:
        constructive = {
            SIPType.PROCEDURAL_SCAFFOLDING,
            SIPType.EDGE_CASE_PROMPTING,
        }
        neutral = {SIPType.REDUNDANT_EXPLORATION}
        destructive = {
            SIPType.SURFACE_ANCHORING,
            SIPType.CONCEPT_BLEED,
        }
        if sip_type in constructive:
            return "constructive"
        if sip_type in neutral:
            return "neutral"
        if sip_type in destructive:
            return "destructive"
        return "unknown"
