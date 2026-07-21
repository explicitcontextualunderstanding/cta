#!/bin/bash
# M3 kimi batch runner — survives session shutdown.
# Usage: nohup scripts/run_kimi_batches.sh > data/m3_captures/batch_run.log 2>&1 &
# Monitor: tail -f data/m3_captures/batch_run.log

set -o pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1

LOG="data/m3_captures/batch_run.log"
echo "=== M3 KIMI BATCH RUN ==="
echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "PID: $$"
echo ""

echo "=== PHASE 1: Baseline runs 2-10 (skips valid B1, B3) ==="
echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 scripts/m3_interactive_harness.py \
  --condition baseline \
  --runs 9 \
  --baseline-token \
  --tag kimi \
  --start-run 2 \
  --max-batch 3 \
  --timeout 900
BASELINE_EXIT=$?
echo ""
echo "Phase 1 exit code: $BASELINE_EXIT"
echo "Completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

echo "=== PHASE 2: Treatment runs 6-10 (skips valid T1-T5) ==="
echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 scripts/m3_interactive_harness.py \
  --condition treatment \
  --runs 5 \
  --baseline-token \
  --tag kimi \
  --start-run 6 \
  --max-batch 3 \
  --timeout 900
TREATMENT_EXIT=$?
echo ""
echo "Phase 2 exit code: $TREATMENT_EXIT"
echo "Completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

echo "=== FINAL STATUS ==="
echo "Baseline exit: $BASELINE_EXIT"
echo "Treatment exit: $TREATMENT_EXIT"
echo ""

# Classify all sessions
echo "=== SESSION CLASSIFICATIONS ==="
python3 -c "
import json
from pathlib import Path
from scripts.m3_interactive_harness import classify_session

captures = Path('data/m3_captures')
valid_t, valid_b = 0, 0
for d in sorted(captures.glob('P1-interactive-kimi-*')):
    if not d.is_dir():
        continue
    c = classify_session(d)
    name = d.name.replace('P1-interactive-kimi-', '')
    print(f'  {name:25s} {c[\"validity\"]:20s} {c[\"reason\"]}')
    if c['validity'] == 'valid':
        if 'treatment' in name:
            valid_t += 1
        else:
            valid_b += 1

print()
print(f'Valid treatment: {valid_t}/10')
print(f'Valid baseline:  {valid_b}/10')
print(f'Target: >=5 per condition for statistical comparison')
"

echo ""
echo "=== BATCH RUN COMPLETE ==="
echo "Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
