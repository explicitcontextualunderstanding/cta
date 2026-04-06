"""
Module 5: Predictive Skill Quality Assessment
Predicts skill utility from skill document and project features
"""

import json
from typing import List, Dict, Tuple, Any, Optional
from pathlib import Path
import numpy as np
from collections import Counter

from .data_models import SkillQualityScore, SIPRecord, SIPType


class SkillQualityPredictor:
    """
    Predicts skill quality and utility using static features.

    Predicts whether a skill will be positive, neutral, or negative for a given task.
    """

    def __init__(self):
        """Initialize predictor"""
        self.model = None
        self.feature_names = []
        self.scaler = None

    def extract_skill_features(self, skill_doc: str) -> Dict[str, float]:
        """
        Extract features from skill document.

        Args:
            skill_doc: Skill document text

        Returns:
            Feature dictionary
        """
        features = {}

        # Template specificity: hardcoded values (versions, IPs, ports)
        lines = skill_doc.split('\n')
        hardcoded_lines = sum(1 for line in lines
                             if any(c.isdigit() for c in line) and
                                any(x in line.lower() for x in ['version', 'ip', 'port', 'url']))
        features['template_specificity'] = hardcoded_lines / max(1, len(lines))

        # Abstraction level: placeholder/variable references
        placeholder_count = skill_doc.count('<') + skill_doc.count('$') + skill_doc.count('{')
        features['abstraction_level'] = placeholder_count / max(1, len(skill_doc))

        # Coverage breadth: heading count and topic diversity
        heading_count = skill_doc.count('#')
        features['coverage_breadth'] = min(heading_count / 10.0, 1.0)  # Normalize

        # Document length
        token_count = len(skill_doc.split())
        features['document_length'] = min(token_count / 5000.0, 1.0)  # Normalize

        # Code-to-prose ratio
        code_lines = sum(1 for line in lines if line.strip().startswith(('```', '    ')))
        features['code_to_prose_ratio'] = code_lines / max(1, len(lines))

        # Instruction density (imperative sentences)
        instructions = sum(1 for line in lines
                          if any(x in line.lower() for x in ['use ', 'do ', 'avoid ', 'ensure ', 'must']))
        features['instruction_density'] = instructions / max(1, len(lines))

        return features

    def extract_project_features(self, task_metadata: Dict[str, Any], baseline_pass_rate: float) -> Dict[str, float]:
        """
        Extract features from project metadata.

        Args:
            task_metadata: Task metadata dictionary
            baseline_pass_rate: without-skill pass rate

        Returns:
            Feature dictionary
        """
        features = {}

        # Tech stack match: skill mentions vs project dependencies
        skill_techs = task_metadata.get('skill_techs', [])
        project_deps = task_metadata.get('dependencies', [])
        intersection = len(set(skill_techs) & set(project_deps))
        union = len(set(skill_techs) | set(project_deps))
        features['tech_stack_match'] = intersection / max(1, union)

        # Version alignment
        version_mismatch_count = task_metadata.get('version_mismatches', 0)
        features['version_alignment'] = max(0, 1.0 - version_mismatch_count * 0.1)

        # Project complexity
        file_count = task_metadata.get('file_count', 0)
        loc = task_metadata.get('loc', 0)
        dep_count = task_metadata.get('dependency_count', 0)
        complexity = min((file_count + loc / 100 + dep_count) / 100, 1.0)
        features['project_complexity'] = complexity

        # Baseline difficulty
        features['baseline_difficulty'] = baseline_pass_rate

        # Semantic relevance
        features['semantic_relevance'] = task_metadata.get('semantic_relevance', 0.5)

        # API overlap
        features['api_overlap'] = task_metadata.get('api_overlap', 0.5)

        return features

    def combine_features(self, skill_features: Dict[str, float],
                        project_features: Dict[str, float]) -> Dict[str, float]:
        """
        Combine skill and project features.

        Args:
            skill_features: Skill document features
            project_features: Project features

        Returns:
            Combined feature vector
        """
        combined = {}
        combined.update(skill_features)
        combined.update(project_features)

        # Add interaction features
        combined['specificity_complexity'] = \
            skill_features.get('template_specificity', 0) / \
            max(project_features.get('project_complexity', 1), 0.1)

        combined['coverage_complexity'] = \
            skill_features.get('coverage_breadth', 0) * \
            project_features.get('project_complexity', 1)

        return combined

    def predict_utility(self, skill_doc: str, task_metadata: Dict[str, Any],
                       baseline_pass_rate: float = 0.5) -> SkillQualityScore:
        """
        Predict skill utility for a task.

        Args:
            skill_doc: Skill document text
            task_metadata: Task metadata
            baseline_pass_rate: without-skill pass rate

        Returns:
            SkillQualityScore with predictions
        """
        # Extract features
        skill_features = self.extract_skill_features(skill_doc)
        project_features = self.extract_project_features(task_metadata, baseline_pass_rate)
        combined_features = self.combine_features(skill_features, project_features)

        # Rule-based prediction
        utility_class, probabilities = self._predict_utility_rules(skill_features, project_features)

        # Extract skill_id from metadata
        skill_id = task_metadata.get('skill_id', 'unknown')

        score = SkillQualityScore(
            skill_id=skill_id,
            utility_class=utility_class,
            probability=probabilities,
            feature_importance=self._get_feature_importance(skill_features),
            recommendation=self._generate_recommendation(utility_class, skill_features),
            confidence=max(probabilities.values()) if probabilities else 0.0
        )

        return score

    def _predict_utility_rules(self, skill_features: Dict[str, float],
                               project_features: Dict[str, float]) -> Tuple[str, Dict[str, float]]:
        """
        Rule-based utility prediction.

        Returns:
            (utility_class, probabilities_dict)
        """
        # Calculate scores
        pos_score = 0.0
        neg_score = 0.0

        # Positive signals
        if skill_features.get('abstraction_level', 0) > 0.3:  # High abstraction
            pos_score += 0.3
        if skill_features.get('instruction_density', 0) > 0.2:  # Clear instructions
            pos_score += 0.2
        if project_features.get('tech_stack_match', 0) > 0.5:  # Good match
            pos_score += 0.3

        # Negative signals
        if skill_features.get('template_specificity', 0) > 0.6:  # Hardcoded values
            neg_score += 0.4
        if skill_features.get('document_length', 0) > 0.8:  # Very long
            neg_score += 0.2
        if skill_features.get('coverage_breadth', 0) > 0.7:  # Too broad
            neg_score += 0.2
        if project_features.get('baseline_difficulty', 0) > 0.9:  # Already easy
            neg_score += 0.2

        # Neutral (high version mismatch but otherwise OK)
        if project_features.get('version_alignment', 0) < 0.5:
            neg_score += 0.1

        # Normalize scores
        total = pos_score + neg_score + 0.1  # Add small constant to avoid division by zero
        pos_prob = pos_score / total
        neg_prob = neg_score / total
        neu_prob = 0.1 / total

        probabilities = {
            'positive': pos_prob,
            'neutral': neu_prob,
            'negative': neg_prob
        }

        # Determine class
        if neg_prob > 0.4:
            utility_class = 'negative'
        elif pos_prob > 0.4:
            utility_class = 'positive'
        else:
            utility_class = 'neutral'

        return utility_class, probabilities

    def _get_feature_importance(self, skill_features: Dict[str, float]) -> Dict[str, float]:
        """Get feature importance scores"""
        importance = {}
        for key, value in skill_features.items():
            # Normalize importance
            if key == 'template_specificity':
                importance[key] = abs(0.6 - value)  # Peaks at 0.6
            elif key == 'abstraction_level':
                importance[key] = value  # Higher is better
            elif key == 'coverage_breadth':
                importance[key] = abs(0.5 - value)  # Optimal at 0.5
            else:
                importance[key] = abs(0.5 - value)

        # Normalize to 0-1
        max_importance = max(importance.values()) if importance else 1
        for key in importance:
            importance[key] /= max(max_importance, 0.1)

        return importance

    def _generate_recommendation(self, utility_class: str, skill_features: Dict[str, float]) -> str:
        """Generate recommendation text"""
        if utility_class == 'positive':
            return "✓ Skill likely beneficial - has good abstraction and clear instructions"
        elif utility_class == 'negative':
            if skill_features.get('template_specificity', 0) > 0.6:
                return "✗ High risk: Skill contains hardcoded values that may conflict with project"
            elif skill_features.get('coverage_breadth', 0) > 0.7:
                return "✗ Skill too broad - may cause concept bleed"
            else:
                return "✗ Skill likely detrimental"
        else:
            return "≈ Skill impact uncertain - consider careful evaluation"

    def predict_batch(self, skill_docs: Dict[str, str],
                     task_metadata_list: List[Dict[str, Any]]) -> Dict[str, SkillQualityScore]:
        """
        Predict utility for multiple skills.

        Args:
            skill_docs: Mapping of skill_id to skill document
            task_metadata_list: List of task metadata

        Returns:
            Mapping of skill_id to SkillQualityScore
        """
        results = {}

        for task_meta in task_metadata_list:
            skill_id = task_meta.get('skill_id')
            if not skill_id or skill_id not in skill_docs:
                continue

            skill_doc = skill_docs[skill_id]
            baseline_pass_rate = task_meta.get('baseline_pass_rate', 0.5)

            score = self.predict_utility(skill_doc, task_meta, baseline_pass_rate)
            results[skill_id] = score

        return results

    def rank_by_utility(self, scores: Dict[str, SkillQualityScore]) -> List[Tuple[str, str, float]]:
        """
        Rank skills by predicted utility.

        Args:
            scores: Dictionary of skill predictions

        Returns:
            List of (skill_id, utility_class, confidence) sorted by quality
        """
        ranked = []
        for skill_id, score in scores.items():
            ranked.append((skill_id, score.utility_class, score.confidence))

        # Sort by confidence (descending)
        ranked.sort(key=lambda x: x[2], reverse=True)

        return ranked

    def analyze_skill_risks(self, skill_doc: str, skill_id: str) -> Dict[str, Any]:
        """
        Analyze specific risks in skill document.

        Args:
            skill_doc: Skill document text
            skill_id: Skill identifier

        Returns:
            Risk analysis dictionary
        """
        analysis = {
            'skill_id': skill_id,
            'risks': []
        }

        features = self.extract_skill_features(skill_doc)

        # Check for Surface Anchoring risk
        if features.get('template_specificity', 0) > 0.5:
            analysis['risks'].append({
                'type': 'surface_anchoring',
                'severity': 'high',
                'description': 'Skill contains hardcoded values that may not match target project',
                'score': features.get('template_specificity', 0)
            })

        # Check for Concept Bleed risk
        if features.get('coverage_breadth', 0) > 0.6:
            analysis['risks'].append({
                'type': 'concept_bleed',
                'severity': 'medium',
                'description': 'Skill covers too many topics - may confuse agent about requirements',
                'score': features.get('coverage_breadth', 0)
            })

        # Check for Context Displacement risk
        if features.get('document_length', 0) > 0.7:
            analysis['risks'].append({
                'type': 'context_displacement',
                'severity': 'medium',
                'description': 'Skill document is very long - may crowd out task requirements',
                'score': features.get('document_length', 0)
            })

        return analysis
