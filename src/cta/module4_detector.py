"""
Module 4: Skill Influence Pattern Detection and Outcome Analysis
Classifies divergences into Skill Influence Patterns (SIPs) and analyzes their impact
"""

import json
from typing import List, Dict, Tuple, Any, Optional
import numpy as np
from pathlib import Path

from .data_models import (
    DivergenceRecord, SIPRecord, SIPType, Event, EventType
)


class SIPDetector:
    """
    Detects Skill Influence Patterns from divergence records.

    SIP types:
    - Constructive: PS (Procedural Scaffolding), CN (Constraint Narrowing), EP (Edge-case Prompting)
    - Neutral: RR (Redundant Reiteration), PE (Parallel Exploration)
    - Destructive: SA (Surface Anchoring), CB (Concept Bleed), CD (Context Displacement)
    """

    def __init__(self, annotation_file: Optional[str] = None):
        """
        Initialize SIP detector.

        Args:
            annotation_file: Path to manual annotations for training (optional)
        """
        self.annotation_file = annotation_file
        self.manual_annotations = {}
        self.classifier = None

        if annotation_file and Path(annotation_file).exists():
            self._load_annotations(annotation_file)

    def detect(self, divergence: DivergenceRecord) -> List[SIPRecord]:
        """
        Classify a divergence into SIP types.

        Args:
            divergence: DivergenceRecord to classify

        Returns:
            List of SIPRecord with detected patterns
        """
        sip_records = []

        # Extract features from divergence
        features = self._extract_features(divergence)

        # Rule-based detection
        detected_sips = self._rule_based_detection(divergence, features)

        sip_id = 0
        for sip_type, confidence in detected_sips.items():
            sip_id += 1
            record = SIPRecord(
                sip_id=sip_id,
                sip_type=sip_type,
                divergence_id=divergence.divergence_id,
                task_id=divergence.intent_pair[0].text[:30],  # Proxy for task_id
                confidence=confidence,
                evidence=features
            )
            sip_records.append(record)

        return sip_records

    def batch_detect(self, divergences: List[DivergenceRecord]) -> List[SIPRecord]:
        """
        Detect SIPs for multiple divergences.

        Args:
            divergences: List of divergences

        Returns:
            List of all detected SIPs
        """
        all_sips = []
        for div in divergences:
            sips = self.detect(div)
            all_sips.extend(sips)
        return all_sips

    def _extract_features(self, divergence: DivergenceRecord) -> Dict[str, Any]:
        """
        Extract features from a divergence record.

        Args:
            divergence: DivergenceRecord

        Returns:
            Feature dictionary
        """
        features = {}

        # Basic counts
        features['num_events_plus'] = len(divergence.actions_plus)
        features['num_events_minus'] = len(divergence.actions_minus)
        features['event_count_ratio'] = (len(divergence.actions_plus) + 1) / (len(divergence.actions_minus) + 1)

        # Event type distribution
        types_plus = [e.type for e in divergence.actions_plus]
        types_minus = [e.type for e in divergence.actions_minus]

        features['write_events_plus'] = types_plus.count(EventType.WRITE)
        features['write_events_minus'] = types_minus.count(EventType.WRITE)
        features['execute_events_plus'] = types_plus.count(EventType.EXECUTE)
        features['execute_events_minus'] = types_minus.count(EventType.EXECUTE)
        features['error_events_plus'] = types_plus.count(EventType.ERROR)
        features['error_events_minus'] = types_minus.count(EventType.ERROR)

        # Target/file overlap
        targets_plus = {e.target for e in divergence.actions_plus if e.target}
        targets_minus = {e.target for e in divergence.actions_minus if e.target}

        intersection = len(targets_plus & targets_minus)
        union = len(targets_plus | targets_minus)
        features['target_jaccard'] = intersection / union if union > 0 else 0.0

        # Content similarity (simple character-level)
        content_plus = ''.join(e.content for e in divergence.actions_plus)
        content_minus = ''.join(e.content for e in divergence.actions_minus)

        features['content_similarity'] = self._string_similarity(content_plus, content_minus)

        # Skill similarity
        features['skill_similarity'] = divergence.skill_similarity

        # Intent similarity
        intent_sim = divergence.intent_pair[0].cosine_similarity(divergence.intent_pair[1])
        features['intent_similarity'] = intent_sim

        return features

    def _rule_based_detection(self, divergence: DivergenceRecord,
                             features: Dict[str, Any]) -> Dict[SIPType, float]:
        """
        Rule-based SIP detection using feature heuristics.

        Args:
            divergence: DivergenceRecord
            features: Extracted features

        Returns:
            Dictionary mapping SIPType to confidence
        """
        sips = {}

        # Procedural Scaffolding: Different phase sequences, more events
        if features['event_count_ratio'] > 1.5 and features['target_jaccard'] > 0.5:
            sips[SIPType.PROCEDURAL_SCAFFOLDING] = 0.7

        # Constraint Narrowing: Fewer errors, shorter error-fix cycles
        if features['error_events_minus'] > features['error_events_plus']:
            sips[SIPType.CONSTRAINT_NARROWING] = 0.6

        # Edge-case Prompting: More write events, higher coverage
        if features['write_events_plus'] > features['write_events_minus']:
            sips[SIPType.EDGE_CASE_PROMPTING] = 0.5

        # Redundant Reiteration: High intent/content similarity, low event count diff
        if features['intent_similarity'] > 0.8 and abs(features['event_count_ratio'] - 1) < 0.3:
            sips[SIPType.REDUNDANT_REITERATION] = 0.75

        # Parallel Exploration: More events but same content
        if features['event_count_ratio'] > 1.3 and features['content_similarity'] > 0.8:
            sips[SIPType.PARALLEL_EXPLORATION] = 0.65

        # Surface Anchoring: High skill similarity, literal content matches
        if features['skill_similarity'] > 0.7 and self._has_literal_matches(divergence):
            sips[SIPType.SURFACE_ANCHORING] = 0.8

        # Concept Bleed: Different targets, more events
        if features['target_jaccard'] < 0.3 and features['num_events_plus'] > features['num_events_minus'] + 2:
            sips[SIPType.CONCEPT_BLEED] = 0.6

        # Context Displacement: Lower content similarity, missing elements
        if features['content_similarity'] < 0.5 and features['intent_similarity'] < 0.6:
            sips[SIPType.CONTEXT_DISPLACEMENT] = 0.55

        return sips

    def _has_literal_matches(self, divergence: DivergenceRecord) -> bool:
        """Check if skill region content appears literally in actions"""
        skill_content = divergence.skill_region.lower()

        for event in divergence.actions_plus:
            if skill_content in event.content.lower():
                return True

        return False

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Simple string similarity (character-level)"""
        if not s1 or not s2:
            return 0.0

        matches = sum(1 for c1, c2 in zip(s1, s2) if c1 == c2)
        return 2 * matches / (len(s1) + len(s2))

    def _load_annotations(self, filepath: str):
        """Load manual annotations for training"""
        with open(filepath, 'r') as f:
            self.manual_annotations = json.load(f)

    def train_classifier(self, annotated_divergences: List[Tuple[DivergenceRecord, SIPType]]):
        """
        Train classifier on annotated divergences.

        Args:
            annotated_divergences: List of (divergence, sip_type) pairs
        """
        # Extract features for training
        X = []
        y = []

        for divergence, sip_type in annotated_divergences:
            features = self._extract_features(divergence)
            X.append(self._features_to_vector(features))
            y.append(sip_type.value)

        X = np.array(X)
        y = np.array(y)

        # Simple logistic regression
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        self.classifier = LogisticRegression(
            multi_class='multinomial',
            max_iter=1000,
            random_state=42
        )
        self.classifier.fit(X_scaled, y)

    def _features_to_vector(self, features: Dict[str, Any]) -> np.ndarray:
        """Convert feature dict to vector for ML models"""
        feature_keys = [
            'event_count_ratio',
            'write_events_plus',
            'execute_events_plus',
            'error_events_plus',
            'target_jaccard',
            'content_similarity',
            'skill_similarity',
            'intent_similarity'
        ]

        vector = []
        for key in feature_keys:
            vector.append(features.get(key, 0.0))

        return np.array(vector)

    def analyze_outcome_relationship(self, sips: List[SIPRecord],
                                    outcomes_plus: List[bool],
                                    outcomes_minus: List[bool]) -> Dict[str, Any]:
        """
        Analyze relationship between SIPs and task outcomes.

        Args:
            sips: List of detected SIPs
            outcomes_plus: Task outcomes with skill
            outcomes_minus: Task outcomes without skill

        Returns:
            Analysis results including coefficients
        """
        analysis = {}

        # Count SIPs by outcome
        for sip_type in SIPType:
            sip_count = sum(1 for s in sips if s.sip_type == sip_type)
            if sip_count == 0:
                continue

            # Calculate effect on outcome
            success_rate = 0.0  # Placeholder for actual calculation
            analysis[sip_type.value] = {
                'count': sip_count,
                'avg_confidence': np.mean([s.confidence for s in sips if s.sip_type == sip_type]),
                'success_rate': success_rate
            }

        return analysis

    def get_sip_statistics(self, sips: List[SIPRecord]) -> Dict[str, Any]:
        """Get statistics about detected SIPs"""
        if not sips:
            return {'total_sips': 0, 'by_type': {}}

        stats = {
            'total_sips': len(sips),
            'by_type': {},
            'avg_confidence': np.mean([s.confidence for s in sips])
        }

        for sip_type in SIPType:
            sips_of_type = [s for s in sips if s.sip_type == sip_type]
            if sips_of_type:
                stats['by_type'][sip_type.value] = {
                    'count': len(sips_of_type),
                    'avg_confidence': np.mean([s.confidence for s in sips_of_type])
                }

        return stats

    def categorize_sip(self, sip_type: SIPType) -> str:
        """Categorize SIP as constructive, neutral, or destructive"""
        constructive = {
            SIPType.PROCEDURAL_SCAFFOLDING,
            SIPType.CONSTRAINT_NARROWING,
            SIPType.EDGE_CASE_PROMPTING
        }
        neutral = {
            SIPType.REDUNDANT_REITERATION,
            SIPType.PARALLEL_EXPLORATION
        }
        destructive = {
            SIPType.SURFACE_ANCHORING,
            SIPType.CONCEPT_BLEED,
            SIPType.CONTEXT_DISPLACEMENT
        }

        if sip_type in constructive:
            return "constructive"
        elif sip_type in neutral:
            return "neutral"
        elif sip_type in destructive:
            return "destructive"
        else:
            return "unknown"
