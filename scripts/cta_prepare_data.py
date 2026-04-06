#!/usr/bin/env python
"""
CTA Data Preparation
Prepares and validates data for CTA analysis
"""

import json
import sys
from pathlib import Path
import argparse
from typing import Dict, List, Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cta import TraceParser


def validate_trace_structure(trace_file: Path) -> bool:
    """Validate trace file structure"""
    try:
        with open(trace_file, 'r') as f:
            data = json.load(f)

        # Check required fields
        required = ['task_id', 'with_skill', 'messages']
        for field in required:
            if field not in data:
                print(f"  ✗ Missing field: {field}")
                return False

        print(f"  ✓ Valid structure")
        return True

    except Exception as e:
        print(f"  ✗ Parse error: {e}")
        return False


def validate_traces_dir(traces_dir: Path) -> Dict[str, List[Path]]:
    """
    Validate all traces in directory.

    Returns:
        Dictionary with validation results
    """
    print(f"\nValidating traces in: {traces_dir}")
    print("-" * 60)

    valid_traces = []
    invalid_traces = []

    trace_files = list(traces_dir.glob('**/*.json'))
    print(f"Found {len(trace_files)} trace files\n")

    for trace_file in trace_files:
        print(f"Checking {trace_file.name}...", end=' ')
        if validate_trace_structure(trace_file):
            valid_traces.append(trace_file)
        else:
            invalid_traces.append(trace_file)

    print(f"\n{'='*60}")
    print(f"Valid traces: {len(valid_traces)}")
    print(f"Invalid traces: {len(invalid_traces)}")

    return {
        'valid': valid_traces,
        'invalid': invalid_traces
    }


def analyze_trace_coverage(valid_traces: List[Path]) -> Dict[str, Any]:
    """
    Analyze coverage of traces across tasks and conditions.

    Returns:
        Coverage statistics
    """
    print(f"\nAnalyzing trace coverage...")
    print("-" * 60)

    parser = TraceParser()
    coverage = {}

    for trace_file in valid_traces:
        try:
            trace = parser.parse_trace_file(str(trace_file))

            task_id = trace.task_id
            condition = "with_skill" if trace.with_skill else "without_skill"

            if task_id not in coverage:
                coverage[task_id] = {'with_skill': [], 'without_skill': []}

            coverage[task_id][condition].append({
                'trace_id': trace.trace_id,
                'events': len(trace.events),
                'tokens': trace.total_tokens,
                'outcome': trace.final_outcome
            })

        except Exception as e:
            print(f"Error processing {trace_file}: {e}")

    # Print coverage summary
    print(f"\nCoverage by task:")
    print("-" * 60)

    for task_id in sorted(coverage.keys()):
        with_skill = len(coverage[task_id]['with_skill'])
        without_skill = len(coverage[task_id]['without_skill'])

        status = "✓" if with_skill > 0 and without_skill > 0 else "✗"
        print(f"{status} {task_id:40} | with: {with_skill} | without: {without_skill}")

    # Summary statistics
    total_tasks = len(coverage)
    complete_pairs = sum(1 for c in coverage.values()
                        if len(c['with_skill']) > 0 and len(c['without_skill']) > 0)

    print(f"\n{'='*60}")
    print(f"Total tasks: {total_tasks}")
    print(f"Complete pairs (both conditions): {complete_pairs}")
    print(f"Coverage: {complete_pairs/total_tasks*100:.1f}%")

    return coverage


def generate_task_metadata(coverage: Dict[str, Any], output_file: str):
    """
    Generate task metadata file.

    Creates a JSON file with task-level statistics for Module 5.
    """
    print(f"\nGenerating task metadata...")
    print("-" * 60)

    metadata = {}

    for task_id, conditions in coverage.items():
        with_skill_traces = conditions['with_skill']
        without_skill_traces = conditions['without_skill']

        # Calculate statistics
        with_skill_outcomes = [t['outcome'] for t in with_skill_traces]
        without_skill_outcomes = [t['outcome'] for t in without_skill_traces]

        with_skill_pass_rate = sum(with_skill_outcomes) / len(with_skill_outcomes) \
            if with_skill_outcomes else 0.0
        without_skill_pass_rate = sum(without_skill_outcomes) / len(without_skill_outcomes) \
            if without_skill_outcomes else 0.0

        with_skill_avg_tokens = sum(t['tokens'] for t in with_skill_traces) / len(with_skill_traces) \
            if with_skill_traces else 0
        without_skill_avg_tokens = sum(t['tokens'] for t in without_skill_traces) / len(without_skill_traces) \
            if without_skill_traces else 0

        metadata[task_id] = {
            'skill_id': task_id,
            'with_skill_pass_rate': with_skill_pass_rate,
            'without_skill_pass_rate': without_skill_pass_rate,
            'baseline_pass_rate': without_skill_pass_rate,
            'pass_rate_delta': with_skill_pass_rate - without_skill_pass_rate,
            'with_skill_avg_tokens': with_skill_avg_tokens,
            'without_skill_avg_tokens': without_skill_avg_tokens,
            'token_overhead_ratio': (with_skill_avg_tokens + 1) / (without_skill_avg_tokens + 1),
            'num_traces_with_skill': len(with_skill_traces),
            'num_traces_without_skill': len(without_skill_traces),
        }

    # Save to file
    with open(output_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"✓ Metadata saved to {output_file}")

    # Print summary
    positive_skills = sum(1 for m in metadata.values() if m['pass_rate_delta'] > 0)
    negative_skills = sum(1 for m in metadata.values() if m['pass_rate_delta'] < 0)
    neutral_skills = sum(1 for m in metadata.values() if m['pass_rate_delta'] == 0)

    print(f"\nSkill distribution:")
    print(f"  Positive (ΔP > 0): {positive_skills}")
    print(f"  Neutral (ΔP = 0): {neutral_skills}")
    print(f"  Negative (ΔP < 0): {negative_skills}")

    return metadata


def main():
    parser = argparse.ArgumentParser(
        description='CTA Data Preparation - Validate and analyze execution traces'
    )

    parser.add_argument(
        '--traces-dir', '-t',
        default='./claude_process',
        help='Directory containing trace files (default: ./claude_process)'
    )

    parser.add_argument(
        '--output', '-o',
        default='./config/cta_task_metadata.json',
        help='Output file for task metadata (default: ./config/cta_task_metadata.json)'
    )

    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Skip trace structure validation'
    )

    args = parser.parse_args()

    traces_dir = Path(args.traces_dir)

    if not traces_dir.exists():
        print(f"Error: Traces directory not found: {traces_dir}")
        sys.exit(1)

    # Validate traces
    if not args.skip_validation:
        validation = validate_traces_dir(traces_dir)
        valid_traces = validation['valid']

        if not valid_traces:
            print("Error: No valid traces found")
            sys.exit(1)
    else:
        valid_traces = list(traces_dir.glob('**/*.json'))

    # Analyze coverage
    coverage = analyze_trace_coverage(valid_traces)

    # Generate metadata
    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = generate_task_metadata(coverage, args.output)

    print(f"\n{'='*60}")
    print("Data preparation complete!")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
