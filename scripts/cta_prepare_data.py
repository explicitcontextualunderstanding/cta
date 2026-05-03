#!/usr/bin/env python
"""
CTA Data Preparation
Prepares and validates data for CTA analysis
"""

import json
import re
import sys
from pathlib import Path
import argparse
from typing import Dict, List, Any, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cta import TraceParser


# Eval report filename pattern, shared with scripts/compare_pass_rate.py:
#   eval_report_<task>_use-agent-<bool>_use-skill-<bool>_<YYYYMMDD>_<HHMMSS>.json
EVAL_REPORT_PATTERN = re.compile(
    r"^eval_report_(?P<skill>.+)_use-agent-(?P<ua>true|false)"
    r"_use-skill-(?P<us>true|false)_(?P<ts>\d{8}_\d{6})\.json$"
)


def validate_trace_structure(trace_file: Path) -> bool:
    """Validate a Claude Code stream-json trace file.

    Checks that:
    - the filename encodes task_id and with_skill
    - the file contains at least one parseable JSON line with an
      ``assistant`` or ``user`` event
    """
    try:
        TraceParser.parse_filename_metadata(trace_file.name)
    except ValueError as e:
        print(f"  ✗ {e}")
        return False

    try:
        seen_event = False
        with open(trace_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get('type') in ('assistant', 'user'):
                    seen_event = True
                    break
        if not seen_event:
            print(f"  ✗ No assistant/user events found")
            return False

        print(f"  ✓ Valid structure")
        return True

    except Exception as e:
        print(f"  ✗ Parse error: {e}")
        return False


def validate_traces_dir(traces_dir: Path) -> Dict[str, List[Path]]:
    """
    Validate all Claude Code stream-json traces under ``traces_dir``.

    Looks for ``claude_thinking/*.jsonl`` files produced by
    ``src/proxy/claude_code_proxy.py`` during benchmark runs.
    """
    print(f"\nValidating traces in: {traces_dir}")
    print("-" * 60)

    valid_traces = []
    invalid_traces = []

    trace_files = sorted(traces_dir.glob('**/claude_thinking/*.jsonl'))
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


def find_eval_reports(
    eval_reports_dir: Optional[Path] = None,
    search_root: Path = Path('reports'),
) -> Dict[Tuple[str, bool, bool], Path]:
    """Discover the latest ``eval_report_*.json`` for each (task, use_agent, use_skill).

    If ``eval_reports_dir`` is provided, only that directory is scanned.
    Otherwise we glob ``{search_root}/**/eval/eval_report_*.json``, which picks
    up reports produced by ``run_all_skills_eval.py`` regardless of model or
    batch sub-directory.

    Reuses the same filename regex as ``scripts/compare_pass_rate.py`` and
    keeps only the report with the latest timestamp per key.
    """
    if eval_reports_dir is not None:
        candidates = list(eval_reports_dir.glob('eval_report_*.json'))
    else:
        candidates = list(search_root.glob('**/eval/eval_report_*.json'))

    latest: Dict[Tuple[str, bool, bool], Tuple[str, Path]] = {}
    for path in candidates:
        match = EVAL_REPORT_PATTERN.match(path.name)
        if not match:
            continue
        key = (
            match.group('skill'),
            match.group('ua') == 'true',
            match.group('us') == 'true',
        )
        ts = match.group('ts')
        existing = latest.get(key)
        if existing is None or ts > existing[0]:
            latest[key] = (ts, path)

    return {k: v[1] for k, v in latest.items()}


def extract_l2_pass_rate(report_path: Path) -> Optional[Tuple[int, int, float]]:
    """Read L2/unit_test pass rate from an ``eval_report_*.json``.

    Returns ``(passed, total, pass_rate)`` or ``None`` if the report has no
    L2/unit_test entry or ``total == 0``.

    Mirrors the lookup in ``scripts/compare_pass_rate.py._extract_pass_rate``.
    """
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ! Could not read {report_path.name}: {e}")
        return None

    details = (data.get('evaluation_scores') or {}).get('details') or []
    for item in details:
        if item.get('level') == 'L2' and item.get('method') == 'unit_test':
            d = item.get('details') or {}
            total = int(d.get('total', 0) or 0)
            passed = int(d.get('passed', 0) or 0)
            if total <= 0:
                return None
            return passed, total, passed / total
    return None


def enrich_coverage_with_eval(
    coverage: Dict[str, Any],
    eval_reports: Dict[Tuple[str, bool, bool], Path],
    use_agent: bool = True,
) -> int:
    """Overwrite each trace entry's ``outcome`` with the real L2/unit_test
    pass rate looked up from its matching ``eval_report_*.json``.

    ``outcome`` starts as a bool (always ``False`` for stream-json traces)
    and becomes a float in ``[0.0, 1.0]`` after enrichment. Downstream
    averaging in ``generate_task_metadata`` then yields real fractional
    ``with/without_skill_pass_rate`` and ``pass_rate_delta`` values.

    Returns the number of trace entries that were updated.
    """
    if not eval_reports:
        print("\nNo eval_report_*.json files found — skipping pass-rate enrichment.")
        print("Run `python run_all_skills_eval.py --use-skill --use-agent` and")
        print("     `python run_all_skills_eval.py --no-use-skill --use-agent` first")
        print("to populate real pass/fail data; otherwise pass_rate_delta stays 0.")
        return 0

    print(f"\nEnriching traces with L2/unit_test pass rates from eval reports...")
    print("-" * 60)

    enriched = 0
    missing: List[Tuple[str, bool]] = []

    for task_id in sorted(coverage):
        for condition, entries in coverage[task_id].items():
            use_skill = condition == 'with_skill'
            key = (task_id, use_agent, use_skill)
            report_path = eval_reports.get(key)
            if report_path is None:
                if entries:
                    missing.append((task_id, use_skill))
                continue

            rate = extract_l2_pass_rate(report_path)
            if rate is None:
                if entries:
                    missing.append((task_id, use_skill))
                continue

            passed, total, pass_rate = rate
            for entry in entries:
                entry['outcome'] = pass_rate
                entry['l2_passed'] = passed
                entry['l2_total'] = total
                entry['eval_report'] = str(report_path)
                enriched += 1

    print(f"✓ Enriched {enriched} trace(s) from {len(eval_reports)} eval report(s)")
    if missing:
        preview = ", ".join(
            f"{t}({'with' if u else 'without'})" for t, u in missing[:5]
        )
        more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        print(f"  ! {len(missing)} (task, condition) pairs had no usable eval report: {preview}{more}")

    return enriched


def analyze_trace_coverage(
    valid_traces: List[Path],
    eval_reports: Optional[Dict[Tuple[str, bool, bool], Path]] = None,
    use_agent: bool = True,
) -> Dict[str, Any]:
    """
    Analyze coverage of traces across tasks and conditions.

    If ``eval_reports`` is provided, each trace's ``outcome`` is enriched with
    the real L2/unit_test pass rate from the matching report so that the
    downstream ``pass_rate_delta`` reflects ground truth.

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
                'outcome': trace.final_outcome,
            })

        except Exception as e:
            print(f"Error processing {trace_file}: {e}")

    if eval_reports is not None:
        enrich_coverage_with_eval(coverage, eval_reports, use_agent=use_agent)

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

        # ``enriched`` is True iff both conditions had at least one trace whose
        # outcome was overwritten from an ``eval_report_*.json``. When False,
        # ``pass_rate_delta`` is meaningless (both sides default to 0.0).
        enriched = bool(with_skill_traces) and bool(without_skill_traces) and all(
            'l2_total' in t for t in with_skill_traces + without_skill_traces
        )

        metadata[task_id] = {
            'skill_id': task_id,
            'with_skill_pass_rate': with_skill_pass_rate,
            'without_skill_pass_rate': without_skill_pass_rate,
            'baseline_pass_rate': without_skill_pass_rate,
            'pass_rate_delta': with_skill_pass_rate - without_skill_pass_rate,
            'pass_rate_source': 'eval_report' if enriched else 'unevaluated',
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

    # Print summary, distinguishing truly neutral tasks from those that simply
    # have no eval data yet.
    evaluated = [m for m in metadata.values() if m['pass_rate_source'] == 'eval_report']
    unevaluated = [m for m in metadata.values() if m['pass_rate_source'] != 'eval_report']

    positive_skills = sum(1 for m in evaluated if m['pass_rate_delta'] > 0)
    negative_skills = sum(1 for m in evaluated if m['pass_rate_delta'] < 0)
    neutral_skills = sum(1 for m in evaluated if m['pass_rate_delta'] == 0)

    print(f"\nSkill distribution (from {len(evaluated)} evaluated task(s)):")
    print(f"  Positive (ΔP > 0): {positive_skills}")
    print(f"  Neutral  (ΔP = 0): {neutral_skills}")
    print(f"  Negative (ΔP < 0): {negative_skills}")
    if unevaluated:
        print(f"  Unevaluated:        {len(unevaluated)}  (run run_all_skills_eval.py to populate)")

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

    parser.add_argument(
        '--eval-reports-dir',
        default=None,
        help=(
            'Directory containing eval_report_*.json files produced by '
            'run_all_skills_eval.py. If omitted, all reports under '
            'reports/**/eval/ are auto-discovered. Pass an empty string to '
            'disable enrichment entirely.'
        ),
    )

    parser.add_argument(
        '--use-agent',
        choices=('true', 'false'),
        default='true',
        help='Which use-agent condition to match when looking up eval reports '
             '(default: true, matching how run_all_skills.py produces traces)'
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
        valid_traces = sorted(traces_dir.glob('**/claude_thinking/*.jsonl'))

    # Locate eval reports (skip entirely if user passes --eval-reports-dir '').
    eval_reports: Optional[Dict[Tuple[str, bool, bool], Path]]
    if args.eval_reports_dir == '':
        eval_reports = None
    else:
        eval_dir = Path(args.eval_reports_dir) if args.eval_reports_dir else None
        if eval_dir is not None and not eval_dir.exists():
            print(f"Warning: --eval-reports-dir not found: {eval_dir} (continuing without enrichment)")
            eval_reports = {}
        else:
            eval_reports = find_eval_reports(eval_dir)

    use_agent = args.use_agent == 'true'

    # Analyze coverage (enriches outcomes from eval reports when available)
    coverage = analyze_trace_coverage(valid_traces, eval_reports=eval_reports, use_agent=use_agent)

    # Generate metadata
    output_dir = Path(args.output).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = generate_task_metadata(coverage, args.output)

    print(f"\n{'='*60}")
    print("Data preparation complete!")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
