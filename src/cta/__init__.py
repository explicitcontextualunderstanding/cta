"""
Counterfactual Trace Auditing (CTA) Framework
Audits agent skill effectiveness through execution trace analysis.
"""

from .data_models import (
    Event,
    Trace,
    Phase,
    PhasedTrace,
    Intent,
    DivergenceRecord,
    SIPRecord,
    SkillQualityScore,
)
from .module1_parser import TraceParser
from .module2_segmenter import PhaseSegmenter
from .module3_aligner import TraceAligner
from .module4_detector import SIPDetector
from .module5_predictor import SkillQualityPredictor

__all__ = [
    "Event",
    "Trace",
    "Phase",
    "PhasedTrace",
    "Intent",
    "DivergenceRecord",
    "SIPRecord",
    "SkillQualityScore",
    "TraceParser",
    "PhaseSegmenter",
    "TraceAligner",
    "SIPDetector",
    "SkillQualityPredictor",
]
