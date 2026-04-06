# CTA Execution Guide

Complete step-by-step guide for running the Counterfactual Trace Auditing (CTA) framework.

## Overview

The CTA framework analyzes Agent Skills through execution trace analysis. It requires:
1. **Execution traces** from running SWE-Skills-Bench with and without skills
2. **CTA analysis** to extract patterns and predict skill quality
3. **Result summarization** to generate insights

**Total execution time:** ~2-4 hours (depending on number of tasks and system specs)

## Prerequisites

```bash
# Create a dedicated conda environment
conda create -n cta python=3.10 -y
conda activate cta

# Ensure Python 3.8+
python --version

# Install dependencies (if not already done)
pip install -r requirements.txt
pip install scipy scikit-learn pyyaml numpy

# Verify Docker is running
docker info
```

## PHASE 1: Data Collection (Execution Traces)

### Step 1.1: Prepare Environment

```bash
# Navigate to SWE-Skills-Bench directory
cd /Users/huxiyang/SWE-Skills-Bench

# Create necessary directories
mkdir -p cta_output config skills

# Copy Claude API key to .env if not done
cp .env.example .env
# Edit .env and add your ANTHROPIC_AUTH_TOKEN
```

### Step 1.2: Generate Traces WITH Skill

This generates execution traces where the agent has access to skill documents.

```bash
# Full run (all 49 tasks)
python run_all_skills.py --use-skill

# Or with specific options:
# - Resume incomplete runs:
python run_all_skills.py --use-skill --resume

# - Dry run (preview without executing):
python run_all_skills.py --use-skill --dry-run

# - Only specific tasks:
python run_all_skills.py --use-skill --only add-uint-support,springboot-tdd

# - Skip specific tasks:
python run_all_skills.py --use-skill --skip test-task-1,test-task-2
```

**Expected output:** `claude_process/` directory with execution logs
**Time:** ~1.5-2 hours for all 49 tasks

### Step 1.3: Generate Traces WITHOUT Skill (Control)

This generates execution traces without skill documents for comparison.

```bash
# Full run
python run_all_skills.py --no-use-skill

# Resume after potential failures
python run_all_skills.py --no-use-skill --resume
```

**Expected output:** Additional logs in `claude_process/`
**Time:** ~1.5-2 hours for all 49 tasks

### Step 1.4: Evaluate Execution Results

Evaluate which tasks passed/failed:

```bash
# Evaluate with-skill runs
python run_all_skills_eval.py --use-skill --use-agent

# Evaluate without-skill runs
python run_all_skills_eval.py --no-use-skill --use-agent
```

This populates `reports/eval/` with test results.

### Step 1.5: Verify Data Collection

Check that traces were collected properly:

```bash
# List generated trace files
find claude_process -name "*.json" | wc -l

# Should show at least ~90 files (3 runs × 49 tasks × 2 conditions)
```

## PHASE 2: CTA Analysis

### Step 2.1: Prepare Trace Data

Validate and prepare traces for CTA analysis:

```bash
# Validate trace structure and generate metadata
python scripts/cta_prepare_data.py \
    --traces-dir ./claude_process \
    --output ./config/cta_task_metadata.json

# This will:
# - Check trace file validity
# - Analyze coverage (which tasks have both conditions)
# - Generate task metadata for Module 5
```

**Expected output:** `config/cta_task_metadata.json`

### Step 2.2: Run Full CTA Analysis

Run the complete pipeline on all tasks:

```bash
# Analyze all tasks (will take 30-60 minutes)
python run_cta_analysis.py --all --verbose

# Or analyze specific task:
python run_cta_analysis.py --task risk-metrics-calculation

# Or analyze multiple specific tasks:
python run_cta_analysis.py --task springboot-tdd --task service-mesh-observability

# Save in multiple formats:
python run_cta_analysis.py --all \
    --output json \
    --output html \
    --output markdown
```

**What happens:**
1. **Module 1 (Trace Parser):** Parses Claude Code logs into Events
2. **Module 2 (Phase Segmenter):** Segments traces into SWE lifecycle phases
3. **Module 3 (Trace Aligner):** Aligns paired traces and detects divergences
4. **Module 4 (SIP Detector):** Classifies divergences into Skill Influence Patterns
5. **Module 5 (Quality Predictor):** Predicts skill utility from features

**Expected output:** 
- JSON files in `cta_output/` with detailed analysis per task
- `cta_output/cta_combined_results.json` with all results

**Time:** ~1-2 minutes per task × 49 tasks = ~45-100 minutes

### Step 2.3: Run Individual Modules (Optional)

If you want to run specific modules only:

```bash
# Only Module 1 (Parsing)
python run_cta_analysis.py --task risk-metrics-calculation --module1-only

# Only Module 2 (Segmentation)
python run_cta_analysis.py --all --module2-only

# Only Module 4 (SIP Detection)
python run_cta_analysis.py --task springboot-tdd --module4-only

# Only Module 5 (Prediction)
python run_cta_analysis.py --all --module5-only
```

## PHASE 3: Result Analysis and Reporting

### Step 3.1: Summarize Results

Aggregate analysis results across all tasks:

```bash
# Generate summary report
python scripts/cta_summarize_results.py \
    --results-dir ./cta_output \
    --output ./cta_output/cta_summary.json
```

This prints a comprehensive summary report showing:
- Distribution of skill utilities (positive/neutral/negative)
- Skill Influence Patterns detected
- Divergence statistics
- Case study findings

**Expected output:**
- Console output with formatted report
- `cta_output/cta_summary.json` with structured summary

### Step 3.2: Analyze Individual Cases

Examine specific task analyses:

```bash
# View best positive skill analysis
cat cta_output/cta_analysis_risk-metrics-calculation_*.json | python -m json.tool | less

# View worst negative skill analysis
cat cta_output/cta_analysis_springboot-tdd_*.json | python -m json.tool | less

# View max token overhead skill
cat cta_output/cta_analysis_service-mesh-observability_*.json | python -m json.tool | less
```

### Step 3.3: Generate Research Report

Create a comprehensive research report:

```bash
# (This script is a template - you can create it based on results)
# For now, manually review:
cat cta_output/cta_summary.json

# View the combined results file
cat cta_output/cta_combined_results.json | python -m json.tool | less
```

## Timeline and Checkpoints

### Checkpoint 1: After Phase 1 (Data Collection)
**Expected:** ~4 hours
```bash
# Verify traces exist
ls -lah claude_process/claude_output/ | head -20
wc -l claude_process/claude_output/*.json

# Check evaluation reports
ls reports/eval/
```

### Checkpoint 2: After Step 2.1 (Data Preparation)
**Expected:** ~5 minutes
```bash
# Check metadata file
cat config/cta_task_metadata.json | python -m json.tool | head -50

# Verify coverage
python -c "import json; m=json.load(open('config/cta_task_metadata.json')); print(f'Tasks: {len(m)}, Positive: {sum(1 for v in m.values() if v[\"pass_rate_delta\"]>0)}')"
```

### Checkpoint 3: After Step 2.2 (CTA Analysis)
**Expected:** ~2 hours
```bash
# Check analysis results
ls cta_output/ | grep cta_analysis | wc -l

# View sample result
cat cta_output/cta_analysis_*_*.json | head -100

# Check combined results
cat cta_output/cta_combined_results.json | python -m json.tool | head -100
```

### Checkpoint 4: After Step 3.1 (Result Summary)
**Expected:** ~5 minutes
```bash
# View summary statistics
cat cta_output/cta_summary.json | python -m json.tool
```

## Troubleshooting

### No traces found during CTA analysis

**Problem:** "No traces found for task X"

**Solution:**
```bash
# Check if trace files exist
find claude_process -name "*.json" | grep -i "task_id"

# Verify format
cat claude_process/claude_output/*.json | python -c "import sys, json; data=json.load(sys.stdin); print(list(data.keys()))"
```

### Low coverage of tasks

**Problem:** Some tasks missing traces

**Solution:**
```bash
# Resume incomplete runs
python run_all_skills.py --use-skill --resume
python run_all_skills.py --no-use-skill --resume

# Check what's missing
python scripts/cta_prepare_data.py --traces-dir ./claude_process
```

### CTA analysis fails on specific task

**Problem:** Error analyzing task X

**Solution:**
```bash
# Run with verbose logging
python run_cta_analysis.py --task <problematic-task> -v

# Run only until the failing module
python run_cta_analysis.py --task <problematic-task> --module1-only
python run_cta_analysis.py --task <problematic-task> --module2-only
# etc.
```

### Out of memory during analysis

**Problem:** Python crashes with memory error

**Solution:**
```bash
# Process fewer tasks at a time
python run_cta_analysis.py --only a,b,c,d,e

# Or increase available memory (system-dependent)
# On macOS/Linux:
export MALLOC_TRIM_THRESHOLD_=100000
python run_cta_analysis.py --all
```

## Advanced: Custom Analysis

### Custom task selection

```bash
# Save task IDs to file
echo "risk-metrics-calculation
springboot-tdd
service-mesh-observability" > tasks.txt

# Analyze only those tasks
while read task; do
    python run_cta_analysis.py --task "$task"
done < tasks.txt
```

### Generate comparison report

```bash
# Compare positive vs negative skills
python -c "
import json

with open('cta_output/cta_summary.json') as f:
    summary = json.load(f)

print('POSITIVE SKILLS:')
for task in summary['skill_utility']['by_class']['positive'][:10]:
    print(f'  - {task}')

print('\nNEGATIVE SKILLS:')
for task in summary['skill_utility']['by_class']['negative'][:10]:
    print(f'  - {task}')
"
```

## Output Files Reference

### Main Outputs

| File | Contains | Size | Purpose |
|------|----------|------|---------|
| `cta_output/cta_analysis_*.json` | Per-task analysis results | ~50-500 KB | Detailed module outputs |
| `cta_output/cta_combined_results.json` | All results combined | ~5-20 MB | Complete dataset |
| `cta_output/cta_summary.json` | Aggregated statistics | ~100-500 KB | Quick summary |
| `cta_output/cta_analysis_*.html` | HTML reports | ~100-300 KB | Visual reports |
| `cta_output/cta_analysis_*.md` | Markdown reports | ~50-200 KB | Documentation |

### Supporting Files

| File | Contains |
|------|----------|
| `config/cta_task_metadata.json` | Task-level statistics from Phase 1 |
| `claude_process/claude_output/*.json` | Raw execution logs |
| `reports/eval/*.json` | Test execution results |

## Key Metrics to Understand

### From Phase 1
- **pass_rate**: Percentage of tests passing (with/without skill)
- **pass_rate_delta (ΔP)**: Improvement or decline from skill
- **token_overhead**: Ratio of tokens with/without skill

### From CTA Analysis
- **divergence_count**: Number of behavioral divergences
- **skill_similarity**: How related divergence is to skill content
- **sip_confidence**: Confidence in SIP classification

### Final Results
- **utility_class**: Predicted skill impact (positive/neutral/negative)
- **confidence**: Confidence in prediction
- **dominant_sips**: Most common patterns detected

## Next Steps After Analysis

1. **Review case studies** in `CTA_README.md`
2. **Analyze risk factors** using Module 5 risk analysis
3. **Generate insights** for skill design guidelines
4. **Validate findings** against research plan predictions
5. **Document lessons** learned

## Questions?

- Review `CTA_README.md` for detailed module documentation
- Check `plan.md` for research methodology
- See individual module source code in `src/cta/`

---

**Ready to start?** Begin with **Step 1.1** above!
