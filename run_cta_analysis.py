#!/usr/bin/env python
"""
CTA (Counterfactual Trace Auditing) Analysis Runner
Comprehensive skill auditing framework

Usage:
    python run_cta_analysis.py [options]
"""

import sys
import logging
from pathlib import Path
import argparse
import json
from typing import List

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from src.cta.pipeline import CTAPipeline


def setup_logging(verbose: bool = False):
    """Setup logging configuration"""
    log_level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main():
    parser = argparse.ArgumentParser(
        description='CTA (Counterfactual Trace Auditing) Analysis Framework',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a single task
  python run_cta_analysis.py --task risk-metrics-calculation

  # Analyze all tasks
  python run_cta_analysis.py --all

  # Analyze and save results
  python run_cta_analysis.py --task springboot-tdd --output json --output html

  # Verbose logging
  python run_cta_analysis.py --task test-task -v
        """
    )

    parser.add_argument(
        '--config', '-c',
        default='cta_config.yaml',
        help='Path to CTA configuration file (default: cta_config.yaml)'
    )

    parser.add_argument(
        '--task', '-t',
        help='Task ID to analyze. Use --list-tasks to see available tasks'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all tasks'
    )

    parser.add_argument(
        '--output', '-o',
        action='append',
        choices=['json', 'html', 'markdown'],
        help='Output format(s) for results (can be specified multiple times)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose logging'
    )

    parser.add_argument(
        '--list-tasks',
        action='store_true',
        help='List available tasks'
    )

    parser.add_argument(
        '--module1-only',
        action='store_true',
        help='Run only Module 1 (Trace Parsing)'
    )

    parser.add_argument(
        '--module2-only',
        action='store_true',
        help='Run only Module 2 (Phase Segmentation)'
    )

    parser.add_argument(
        '--module3-only',
        action='store_true',
        help='Run only Module 3 (Trace Alignment)'
    )

    parser.add_argument(
        '--module4-only',
        action='store_true',
        help='Run only Module 4 (SIP Detection)'
    )

    parser.add_argument(
        '--module5-only',
        action='store_true',
        help='Run only Module 5 (Quality Prediction)'
    )

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Check if config exists
    if not Path(args.config).exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Initialize pipeline
    try:
        pipeline = CTAPipeline(args.config)
    except Exception as e:
        logger.error(f"Failed to initialize pipeline: {e}")
        sys.exit(1)

    # List tasks
    if args.list_tasks:
        print_available_tasks()
        return

    # Determine which tasks to analyze
    tasks_to_analyze = []

    if args.all:
        tasks_to_analyze = get_all_tasks()
    elif args.task:
        tasks_to_analyze = [args.task]
    else:
        parser.print_help()
        sys.exit(1)

    # Set output formats
    output_formats = args.output or ['json']

    # Run analysis
    logger.info(f"Starting CTA analysis for {len(tasks_to_analyze)} task(s)")
    all_results = {}

    for task_id in tasks_to_analyze:
        logger.info(f"\n{'='*60}")
        logger.info(f"Analyzing task: {task_id}")
        logger.info(f"{'='*60}")

        try:
            results = pipeline.run_full_analysis(task_id)
            all_results[task_id] = results

            # Save results
            for fmt in output_formats:
                pipeline.save_results(results, format=fmt)

            # Print summary
            print_analysis_summary(results)

        except Exception as e:
            logger.error(f"Error analyzing {task_id}: {e}", exc_info=True)

    # Print overall summary
    logger.info(f"\n{'='*60}")
    logger.info("CTA Analysis Complete")
    logger.info(f"{'='*60}")

    print_overall_summary(all_results)

    # Save combined results
    combined_file = Path(pipeline.output_dir) / 'cta_combined_results.json'
    with open(combined_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    logger.info(f"Combined results saved to {combined_file}")


def get_all_tasks() -> List[str]:
    """Get list of all available tasks"""
    # This would load from the benchmark config
    # For now, return the tasks from the plan
    tasks = [
        "add-uint-support",
        "fix",
        "tdd-workflow",
        "security-review",
        "springboot-tdd",
        "add-admin-api-endpoint",
        "mcp-builder",
        "python-resilience",
        "xlsx",
        "turborepo",
        "github-actions-templates",
        "analytics-events",
        "prometheus-configuration",
        "python-anti-patterns",
        "implementing-jsc-classes-zig",
        "add-malli-schemas",
        "clojure-write",
        "django-patterns",
        "python-background-jobs",
        "python-configuration",
        "creating-financial-models",
        "prompt-engineering-patterns",
        "risk-metrics-calculation",
        "vector-index-tuning",
        "rag-implementation",
        "spark-optimization",
        "similarity-search-patterns",
        "llm-evaluation",
        "analyze-ci",
        "python-packaging",
        "gitops-workflow",
        "linkerd-patterns",
        "changelog-automation",
        "k8s-manifest-generator",
        "nx-workspace-patterns",
        "bazel-build-optimization",
        "istio-traffic-management",
        "bash-defensive-patterns",
        "gitlab-ci-patterns",
        "implementing-agent-modes",
        "python-observability",
        "distributed-tracing",
        "service-mesh-observability",
        "slo-implementation",
        "python-performance-optimization",
        "grafana-dashboards",
        "dbt-transformation-patterns",
        "langsmith-fetch",
        "v3-performance-optimization",
    ]
    return tasks


def print_available_tasks():
    """Print available tasks"""
    tasks = get_all_tasks()
    print("\nAvailable Tasks:")
    print("-" * 40)
    for i, task in enumerate(tasks, 1):
        print(f"{i:2}. {task}")
    print(f"\nTotal: {len(tasks)} tasks\n")


def print_analysis_summary(results: dict):
    """Print summary of analysis results"""
    print(f"\nTask: {results['task_id']}")
    print("-" * 40)

    summary = results.get('summary', {})
    print(f"✓ Analysis Complete: {summary.get('analysis_complete', False)}")

    modules = results.get('modules', {})
    for module_name in summary.get('modules_executed', []):
        if module_name in modules:
            print(f"  - {module_name}: OK")

    if summary.get('skill_utility'):
        print(f"Skill Utility: {summary['skill_utility']} (confidence: {summary.get('skill_confidence', 0):.2f})")

    if summary.get('dominant_sips'):
        print(f"Dominant SIPs: {', '.join(summary['dominant_sips'])}")

    if 'error' in results:
        print(f"✗ Error: {results['error']}")


def print_overall_summary(all_results: dict):
    """Print overall summary"""
    print("\nOverall Summary:")
    print("=" * 60)

    total_tasks = len(all_results)
    successful = sum(1 for r in all_results.values() if r.get('summary', {}).get('analysis_complete', False))

    print(f"Total tasks analyzed: {total_tasks}")
    print(f"Successful analyses: {successful}")
    print(f"Failed analyses: {total_tasks - successful}")

    # Count by utility class
    utility_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    for result in all_results.values():
        utility = result.get('summary', {}).get('skill_utility')
        if utility in utility_counts:
            utility_counts[utility] += 1

    print(f"\nSkill Utility Distribution:")
    for utility, count in utility_counts.items():
        if count > 0:
            pct = count / total_tasks * 100
            print(f"  {utility}: {count} ({pct:.1f}%)")

    print(f"\nResults saved to: cta_output/")
    print("=" * 60)


if __name__ == '__main__':
    main()
