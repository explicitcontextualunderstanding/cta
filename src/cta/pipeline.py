"""
CTA Pipeline
Orchestrates the complete Counterfactual Trace Auditing workflow
"""

import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from pathlib import Path
import yaml

from .module1_parser import TraceParser
from .module2_segmenter import PhaseSegmenter
from .module3_aligner import TraceAligner
from .module4_detector import SIPDetector
from .module5_predictor import SkillQualityPredictor
from .data_models import Trace, PhasedTrace, DivergenceRecord, SIPRecord, SkillQualityScore


logger = logging.getLogger(__name__)


class CTAPipeline:
    """
    Complete CTA analysis pipeline.

    Executes all five modules in sequence for comprehensive skill auditing.
    """

    def __init__(self, config_file: str):
        """
        Initialize pipeline.

        Args:
            config_file: Path to CTA configuration YAML file
        """
        self.config = self._load_config(config_file)
        self.output_dir = Path(self.config['data']['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize modules. Both Module 3 (skill_region resolution) and
        # Module 4 (Surface Anchoring detection) need the full skill
        # document; wire the pipeline's loader to both so they can resolve
        # docs by task_id.
        self.parser = TraceParser()
        self.segmenter = PhaseSegmenter()
        self.aligner = TraceAligner(
            intent_similarity_threshold=self.config['modules']['trace_aligner']['intent_similarity_threshold'],
            skill_doc_provider=self._load_skill_document,
        )
        self.sip_detector = SIPDetector(
            skill_doc_provider=self._load_skill_document,
        )
        self.predictor = SkillQualityPredictor()

        logger.info("CTA Pipeline initialized")

    def run_full_analysis(self, task_id: str) -> Dict[str, Any]:
        """
        Run complete analysis for a task.

        Args:
            task_id: Task identifier

        Returns:
            Analysis results dictionary
        """
        logger.info(f"Starting full CTA analysis for task: {task_id}")

        results = {
            'task_id': task_id,
            'modules': {}
        }

        try:
            # Module 1: Parse traces
            traces_plus, traces_minus = self._run_module1(task_id)
            results['modules']['parsing'] = {
                'traces_with_skill': len(traces_plus),
                'traces_without_skill': len(traces_minus)
            }

            if not traces_plus or not traces_minus:
                logger.warning(f"No traces found for task {task_id}")
                return results

            # Module 2: Segment into phases
            phased_traces_plus = self._run_module2(traces_plus)
            phased_traces_minus = self._run_module2(traces_minus)
            results['modules']['segmentation'] = {
                'phased_traces_with_skill': len(phased_traces_plus),
                'phased_traces_without_skill': len(phased_traces_minus)
            }

            # Module 3: Align and detect divergences (passes task_id so the
            # aligner can resolve the real skill_region from SKILL.md).
            divergences = self._run_module3(
                phased_traces_plus, phased_traces_minus, task_id=task_id
            )
            results['modules']['alignment'] = {
                'total_divergences': len(divergences),
                'divergence_statistics': self._get_divergence_stats(divergences)
            }

            # Module 4: Detect SIPs (passing task_id so SA can look up the skill doc)
            sips = self._run_module4(divergences, task_id=task_id)
            results['modules']['sip_detection'] = {
                'total_sips': len(sips),
                'sip_statistics': self._get_sip_stats(sips)
            }

            # Module 5: Predict skill quality
            quality_score = self._run_module5(task_id)
            results['modules']['quality_prediction'] = quality_score.to_dict() if quality_score else {}

            # Aggregate results
            results['summary'] = self._aggregate_results(results)

            logger.info(f"Analysis complete for task {task_id}")

        except Exception as e:
            logger.error(f"Error in analysis pipeline: {e}", exc_info=True)
            results['error'] = str(e)

        return results

    def _run_module1(self, task_id: str) -> Tuple[List[Trace], List[Trace]]:
        """Run Module 1: Trace Parsing"""
        logger.info("Module 1: Parsing execution traces...")

        trace_logs_dir = Path(self.config['data']['trace_logs_dir'])

        traces_plus = []
        traces_minus = []

        # Find and parse trace files. Primary source is the Claude Code
        # stream-json ``.jsonl`` written by claude_code_proxy.py; we also
        # pick up any legacy ``*.json`` traces if present.
        trace_candidates = list(trace_logs_dir.glob('**/claude_thinking/*.jsonl'))
        trace_candidates += list(trace_logs_dir.glob('**/claude_output/*.json'))
        for trace_file in trace_candidates:
            try:
                trace = self.parser.parse_trace_file(str(trace_file))
                if trace.task_id == task_id:
                    if trace.with_skill:
                        traces_plus.append(trace)
                    else:
                        traces_minus.append(trace)
            except Exception as e:
                logger.debug(f"Could not parse {trace_file}: {e}")

        logger.info(f"Parsed {len(traces_plus)} with-skill traces, {len(traces_minus)} without-skill traces")
        return traces_plus, traces_minus

    def _run_module2(self, traces: List[Trace]) -> List[PhasedTrace]:
        """Run Module 2: Phase Segmentation"""
        logger.info(f"Module 2: Segmenting {len(traces)} traces into phases...")

        phased_traces = self.segmenter.segment_batch(traces)
        logger.info(f"Segmented into {len(phased_traces)} phased traces")

        return phased_traces

    def _run_module3(
        self,
        phased_traces_plus: List[PhasedTrace],
        phased_traces_minus: List[PhasedTrace],
        task_id: Optional[str] = None,
    ) -> List[DivergenceRecord]:
        """Run Module 3: Trace Alignment and Divergence Detection.

        ``task_id`` is forwarded so the aligner can pull the real SKILL.md
        and populate each divergence's ``skill_region`` field, which is
        required by Module 4's Surface Anchoring detector.
        """
        logger.info("Module 3: Aligning traces and detecting divergences...")

        divergences = []
        min_runs = min(len(phased_traces_plus), len(phased_traces_minus))
        for i in range(min_runs):
            trace_plus = phased_traces_plus[i]
            trace_minus = phased_traces_minus[i]

            run_divergences = self.aligner.align_traces(
                trace_plus, trace_minus, task_id=task_id
            )
            divergences.extend(run_divergences)

        logger.info(f"Detected {len(divergences)} divergences")
        return divergences

    def _run_module4(
        self,
        divergences: List[DivergenceRecord],
        task_id: Optional[str] = None,
    ) -> List[SIPRecord]:
        """Run Module 4: SIP Detection.

        ``task_id`` is forwarded so the Surface Anchoring detector can pull
        the full skill document via the registered ``skill_doc_provider``.
        """
        logger.info(f"Module 4: Detecting SIPs in {len(divergences)} divergences...")

        sips = self.sip_detector.batch_detect(divergences, task_id=task_id)
        logger.info(f"Detected {len(sips)} skill influence patterns")

        return sips

    def _run_module5(self, task_id: str) -> Optional[SkillQualityScore]:
        """Run Module 5: Skill Quality Prediction"""
        logger.info("Module 5: Predicting skill quality...")

        # Load task metadata and skill document
        try:
            task_metadata = self._load_task_metadata(task_id)
            skill_doc = self._load_skill_document(task_id)

            if not task_metadata or not skill_doc:
                logger.warning(f"Could not load metadata for task {task_id}")
                return None

            baseline_pass_rate = task_metadata.get('baseline_pass_rate', 0.5)
            score = self.predictor.predict_utility(skill_doc, task_metadata, baseline_pass_rate)

            logger.info(f"Skill utility prediction: {score.utility_class}")
            return score

        except Exception as e:
            logger.error(f"Error in Module 5: {e}")
            return None

    def _get_divergence_stats(self, divergences: List[DivergenceRecord]) -> Dict[str, Any]:
        """Get statistics about divergences"""
        return self.aligner.get_divergence_statistics(divergences)

    def _get_sip_stats(self, sips: List[SIPRecord]) -> Dict[str, Any]:
        """Get statistics about SIPs"""
        return self.sip_detector.get_sip_statistics(sips)

    def _aggregate_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate analysis results"""
        summary = {
            'task_id': results['task_id'],
            'analysis_complete': 'error' not in results,
            'modules_executed': list(results.get('modules', {}).keys())
        }

        # Add key findings
        if 'sip_detection' in results['modules']:
            sip_stats = results['modules']['sip_detection'].get('sip_statistics', {})
            if sip_stats:
                summary['dominant_sips'] = self._get_dominant_sips(sip_stats)

        if 'quality_prediction' in results['modules']:
            quality = results['modules']['quality_prediction']
            if quality:
                summary['skill_utility'] = quality.get('utility_class')
                summary['skill_confidence'] = quality.get('confidence')

        return summary

    def _get_dominant_sips(self, sip_stats: Dict[str, Any]) -> List[str]:
        """Get dominant SIP types"""
        if not sip_stats.get('by_type'):
            return []

        by_count = sorted(
            sip_stats['by_type'].items(),
            key=lambda x: x[1].get('count', 0),
            reverse=True
        )

        return [sip_type for sip_type, _ in by_count[:3]]

    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """Load configuration file"""
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

    def _load_task_metadata(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Load task metadata"""
        metadata_file = self.config['data']['task_metadata_file']
        try:
            with open(metadata_file, 'r') as f:
                tasks = json.load(f)
            return tasks.get(task_id)
        except Exception as e:
            logger.debug(f"Could not load task metadata: {e}")
            return None

    def _load_skill_document(self, task_id: str) -> Optional[str]:
        """Load skill document.

        Supports two layouts:
          1. ``skills/<task_id>.md`` (single-file skill)
          2. ``skills/<task_id>/SKILL.md`` (directory-style skill, current convention)
        """
        skills_dir = Path(self.config['data']['skills_dir'])
        candidates = [
            skills_dir / f"{task_id}.md",
            skills_dir / task_id / "SKILL.md",
        ]

        for skill_file in candidates:
            try:
                if skill_file.exists():
                    with open(skill_file, 'r') as f:
                        return f.read()
            except Exception as e:
                logger.debug(f"Could not load skill document {skill_file}: {e}")

        return None

    def save_results(self, results: Dict[str, Any], format: str = 'json'):
        """Save analysis results"""
        task_id = results['task_id']
        timestamp = self._get_timestamp()

        if format == 'json':
            output_file = self.output_dir / f"cta_analysis_{task_id}_{timestamp}.json"
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)

        elif format == 'html':
            output_file = self.output_dir / f"cta_analysis_{task_id}_{timestamp}.html"
            self._save_html_report(results, output_file)

        elif format == 'markdown':
            output_file = self.output_dir / f"cta_analysis_{task_id}_{timestamp}.md"
            self._save_markdown_report(results, output_file)

        logger.info(f"Results saved to {output_file}")

    def _save_html_report(self, results: Dict[str, Any], filepath: Path):
        """Save HTML report"""
        html_content = f"""
        <html>
        <head><title>CTA Analysis - {results['task_id']}</title></head>
        <body>
            <h1>CTA Analysis Report</h1>
            <h2>Task: {results['task_id']}</h2>
            <pre>{json.dumps(results, indent=2)}</pre>
        </body>
        </html>
        """
        with open(filepath, 'w') as f:
            f.write(html_content)

    def _save_markdown_report(self, results: Dict[str, Any], filepath: Path):
        """Save Markdown report"""
        md_content = f"""# CTA Analysis Report

## Task: {results['task_id']}

### Summary
- Analysis Complete: {results['summary'].get('analysis_complete', False)}
- Modules Executed: {', '.join(results['summary'].get('modules_executed', []))}

### Module Results

"""

        for module_name, module_results in results['modules'].items():
            md_content += f"## {module_name.title()}\n\n"
            md_content += f"```json\n{json.dumps(module_results, indent=2)}\n```\n\n"

        with open(filepath, 'w') as f:
            f.write(md_content)

    @staticmethod
    def _get_timestamp() -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().strftime('%Y%m%d_%H%M%S')
