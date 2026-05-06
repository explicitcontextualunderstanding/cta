#!/usr/bin/env python
"""
CTA Results Summarizer
Aggregates and analyzes CTA analysis results
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
import argparse
from collections import defaultdict

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def load_results(results_dir: Path) -> Dict[str, Dict]:
    """Load CTA analysis results from directory.

    Each pipeline run produces a timestamped file (``cta_analysis_<task>_<ts>.json``).
    To avoid mixing results from older runs that may use a stale SIP schema,
    we keep only the *most recent* file per task_id (by mtime).
    """
    files_by_task: Dict[str, Path] = {}
    mtimes_by_task: Dict[str, float] = {}

    for result_file in results_dir.glob('cta_analysis_*.json'):
        try:
            with open(result_file, 'r') as f:
                data = json.load(f)
            task_id = data.get('task_id')
            if not task_id:
                continue
            mtime = result_file.stat().st_mtime
            if task_id not in mtimes_by_task or mtime > mtimes_by_task[task_id]:
                files_by_task[task_id] = result_file
                mtimes_by_task[task_id] = mtime
        except Exception as e:
            print(f"Warning: Could not load {result_file}: {e}")

    results: Dict[str, Dict] = {}
    for task_id, latest_file in files_by_task.items():
        with open(latest_file, 'r') as f:
            results[task_id] = json.load(f)

    return results


def aggregate_sips(results: Dict[str, Dict]) -> Dict[str, Any]:
    """Aggregate SIP statistics across all tasks"""
    sip_stats = defaultdict(lambda: {'count': 0, 'tasks': []})

    for task_id, result in results.items():
        sips = result.get('modules', {}).get('sip_detection', {}).get('sip_statistics', {}).get('by_type', {})

        for sip_type, stats in sips.items():
            count = stats.get('count', 0)
            sip_stats[sip_type]['count'] += count
            if count > 0:
                sip_stats[sip_type]['tasks'].append(task_id)

    return dict(sip_stats)


def aggregate_divergences(results: Dict[str, Dict]) -> Dict[str, Any]:
    """Aggregate divergence statistics"""
    total_divergences = 0
    div_by_type = defaultdict(int)
    div_by_phase = defaultdict(int)

    for result in results.values():
        div_stats = result.get('modules', {}).get('alignment', {}).get('divergence_statistics', {})

        total_divergences += div_stats.get('total_divergences', 0)

        for div_type, count in div_stats.get('by_type', {}).items():
            div_by_type[div_type] += count

        for phase, count in div_stats.get('by_phase', {}).items():
            div_by_phase[phase] += count

    return {
        'total_divergences': total_divergences,
        'by_type': dict(div_by_type),
        'by_phase': dict(div_by_phase)
    }


def analyze_skill_utility(results: Dict[str, Dict]) -> Dict[str, Any]:
    """Analyze skill utility predictions"""
    utility_dist = {'positive': [], 'neutral': [], 'negative': []}
    avg_confidence_by_class = defaultdict(list)

    for task_id, result in results.items():
        summary = result.get('summary', {})
        utility = summary.get('skill_utility')
        confidence = summary.get('skill_confidence', 0.0)

        if utility in utility_dist:
            utility_dist[utility].append(task_id)
            avg_confidence_by_class[utility].append(confidence)

    # Calculate averages
    avg_confidence = {}
    for utility_class, confidences in avg_confidence_by_class.items():
        avg_confidence[utility_class] = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        'distribution': {k: len(v) for k, v in utility_dist.items()},
        'by_class': utility_dist,
        'avg_confidence': avg_confidence
    }


def identify_case_studies(results: Dict[str, Dict]) -> Dict[str, Any]:
    """Identify case studies mentioned in research plan"""
    case_studies = {
        'best_positive': {'skill_id': 'risk-metrics-calculation'},
        'worst_negative': {'skill_id': 'springboot-tdd'},
        'max_token_overhead': {'skill_id': 'service-mesh-observability'},
        'context_interference': {'skill_id': 'linkerd-patterns'}
    }

    for case_name, case_info in case_studies.items():
        skill_id = case_info['skill_id']
        if skill_id in results:
            result = results[skill_id]
            case_info['result'] = result
            case_info['utility'] = result.get('summary', {}).get('skill_utility')
            case_info['dominant_sips'] = result.get('summary', {}).get('dominant_sips', [])

    return case_studies


def print_summary_report(results: Dict[str, Dict]):
    """Print comprehensive summary report"""
    print("\n" + "="*80)
    print("CTA ANALYSIS SUMMARY REPORT")
    print("="*80)

    # Overall statistics
    print(f"\n1. OVERALL STATISTICS")
    print("-" * 80)
    print(f"   Total tasks analyzed: {len(results)}")

    successful = sum(1 for r in results.values()
                    if r.get('summary', {}).get('analysis_complete', False))
    print(f"   Successful analyses: {successful}")
    print(f"   Success rate: {successful/len(results)*100:.1f}%")

    # Skill utility distribution
    print(f"\n2. SKILL UTILITY DISTRIBUTION")
    print("-" * 80)
    utility_stats = analyze_skill_utility(results)

    for utility_class in ['positive', 'neutral', 'negative']:
        count = utility_stats['distribution'][utility_class]
        tasks = utility_stats['by_class'][utility_class]
        avg_conf = utility_stats['avg_confidence'].get(utility_class, 0.0)

        pct = count / len(results) * 100 if results else 0
        print(f"   {utility_class.upper():10} : {count:3} tasks ({pct:5.1f}%) | Avg Confidence: {avg_conf:.3f}")

        if count > 0 and count <= 5:
            print(f"              {', '.join(tasks)}")

    # SIP statistics
    print(f"\n3. SKILL INFLUENCE PATTERNS (SIPs)")
    print("-" * 80)
    sip_stats = aggregate_sips(results)

    # Categorize by type (v2 schema)
    constructive = ['procedural_scaffolding', 'edge_case_prompting']
    neutral = ['redundant_exploration']
    destructive = ['surface_anchoring', 'concept_bleed']

    print("   CONSTRUCTIVE:")
    for sip_type in constructive:
        if sip_type in sip_stats:
            count = sip_stats[sip_type]['count']
            print(f"      - {sip_type:35} : {count:4} detections")

    print("\n   NEUTRAL:")
    for sip_type in neutral:
        if sip_type in sip_stats:
            count = sip_stats[sip_type]['count']
            print(f"      - {sip_type:35} : {count:4} detections")

    print("\n   DESTRUCTIVE:")
    for sip_type in destructive:
        if sip_type in sip_stats:
            count = sip_stats[sip_type]['count']
            print(f"      - {sip_type:35} : {count:4} detections")

    # Divergence statistics
    print(f"\n4. DIVERGENCE STATISTICS")
    print("-" * 80)
    div_stats = aggregate_divergences(results)

    print(f"   Total divergences: {div_stats['total_divergences']}")
    print(f"   By type:")
    for div_type, count in sorted(div_stats['by_type'].items()):
        print(f"      - {div_type:30} : {count:4} divergences")

    print(f"   By phase:")
    for phase, count in sorted(div_stats['by_phase'].items()):
        print(f"      - {phase:30} : {count:4} divergences")

    # Case studies
    print(f"\n5. CASE STUDIES")
    print("-" * 80)
    case_studies = identify_case_studies(results)

    for case_name, case_info in case_studies.items():
        skill_id = case_info['skill_id']
        if 'result' in case_info:
            utility = case_info.get('utility', 'unknown')
            sips = case_info.get('dominant_sips', [])
            print(f"   {case_name:25} ({skill_id})")
            print(f"      Utility: {utility}")
            if sips:
                print(f"      Dominant SIPs: {', '.join(sips)}")
        else:
            print(f"   {case_name:25} ({skill_id}) - NOT ANALYZED")

    print("\n" + "="*80)


def save_summary_json(results: Dict[str, Dict], output_file: str):
    """Save summary as JSON"""
    summary = {
        'total_tasks': len(results),
        'skill_utility': analyze_skill_utility(results),
        'divergences': aggregate_divergences(results),
        'sips': aggregate_sips(results),
        'case_studies': identify_case_studies(results)
    }

    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"✓ Summary saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='CTA Results Summarizer - Aggregate and analyze CTA outputs'
    )

    parser.add_argument(
        '--results-dir', '-r',
        default='./cta_output',
        help='Directory containing CTA analysis results'
    )

    parser.add_argument(
        '--output', '-o',
        default='./cta_output/cta_summary.json',
        help='Output file for summary (default: ./cta_output/cta_summary.json)'
    )

    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}")
        sys.exit(1)

    # Load results
    print(f"Loading results from {results_dir}...")
    results = load_results(results_dir)

    if not results:
        print("Error: No results found")
        sys.exit(1)

    print(f"Loaded {len(results)} analysis results\n")

    # Print summary
    print_summary_report(results)

    # Save summary
    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    save_summary_json(results, args.output)


if __name__ == '__main__':
    main()
