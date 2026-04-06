# CTA Quick Reference Card

Fast lookup for common CTA commands and workflows.

## Installation

```bash
# Create a dedicated conda environment
conda create -n cta python=3.10 -y
conda activate cta

# Install dependencies (one-time)
pip install -r requirements.txt
pip install -r requirements_cta.txt
```

## Main Commands

### Data Collection (Phase 1)

```bash
# Generate traces WITH skill
python run_all_skills.py --use-skill

# Generate traces WITHOUT skill
python run_all_skills.py --no-use-skill

# Resume incomplete runs
python run_all_skills.py --use-skill --resume
python run_all_skills.py --no-use-skill --resume
```

### Data Preparation (Phase 2.1)

```bash
# Validate and prepare traces
python scripts/cta_prepare_data.py \
    --traces-dir ./claude_process \
    --output ./config/cta_task_metadata.json
```

### CTA Analysis (Phase 2.2)

```bash
# Analyze all tasks
python run_cta_analysis.py --all

# Analyze single task
python run_cta_analysis.py --task risk-metrics-calculation

# Analyze multiple tasks
python run_cta_analysis.py --task task1 --task task2 --task task3

# With verbose output
python run_cta_analysis.py --all -v

# Save in multiple formats
python run_cta_analysis.py --all --output json --output html --output markdown

# List available tasks
python run_cta_analysis.py --list-tasks
```

### Result Analysis (Phase 3)

```bash
# Summarize results
python scripts/cta_summarize_results.py \
    --results-dir ./cta_output \
    --output ./cta_output/cta_summary.json

# View summary
cat cta_output/cta_summary.json | python -m json.tool
```

## Single Module Analysis

```bash
# Module 1: Trace Parser
python run_cta_analysis.py --task <task> --module1-only

# Module 2: Phase Segmentation
python run_cta_analysis.py --task <task> --module2-only

# Module 3: Trace Alignment
python run_cta_analysis.py --task <task> --module3-only

# Module 4: SIP Detection
python run_cta_analysis.py --task <task> --module4-only

# Module 5: Quality Prediction
python run_cta_analysis.py --task <task> --module5-only
```

## Data Inspection

```bash
# List execution traces
find claude_process -name "*.json" | head -20

# Count total traces
find claude_process -name "*.json" | wc -l

# Inspect single trace
cat claude_process/claude_output/<trace>.json | python -m json.tool

# Check task metadata
cat config/cta_task_metadata.json | python -m json.tool | head -100

# View analysis result
cat cta_output/cta_analysis_<task>_*.json | python -m json.tool

# View summary
cat cta_output/cta_summary.json | python -m json.tool
```

## Troubleshooting

```bash
# Run with debug logging
python run_cta_analysis.py --task <task> -v

# Validate traces before analysis
python scripts/cta_prepare_data.py --traces-dir ./claude_process

# Check trace coverage
python -c "
import json
meta = json.load(open('config/cta_task_metadata.json'))
complete = [t for t, m in meta.items() if m['num_traces_with_skill'] > 0 and m['num_traces_without_skill'] > 0]
print(f'Complete pairs: {len(complete)}/{len(meta)}')"

# List failed analyses
find cta_output -name "*.json" -exec grep -l '"error"' {} \;
```

## Output File Locations

```bash
# Analysis results
cta_output/cta_analysis_<task>_<timestamp>.json      # Per-task detailed
cta_output/cta_analysis_<task>_<timestamp>.html      # Per-task HTML
cta_output/cta_analysis_<task>_<timestamp>.md        # Per-task Markdown

# Combined/Summary
cta_output/cta_combined_results.json                  # All results combined
cta_output/cta_summary.json                           # Summary statistics

# Configuration
config/cta_task_metadata.json                         # Task metadata
cta_config.yaml                                       # Framework config

# Raw traces
claude_process/claude_output/<model>/<batch>/*.json   # Execution logs
reports/eval/*.json                                   # Test results
```

## Configuration

Edit `cta_config.yaml` to change:

```yaml
# Data paths
data:
  trace_logs_dir: "./claude_process"
  skills_dir: "./skills"
  task_metadata_file: "./config/cta_task_metadata.json"
  output_dir: "./cta_output"

# Module parameters
modules:
  trace_aligner:
    intent_similarity_threshold: 0.7
  sip_detector:
    min_detection_confidence: 0.5
  skill_predictor:
    cv_strategy: "leave_one_skill_out"
```

## Common Workflows

### Quick Start (First Time)

```bash
# Step 1: Collect traces
python run_all_skills.py --use-skill
python run_all_skills.py --no-use-skill

# Step 2: Prepare data
python scripts/cta_prepare_data.py

# Step 3: Analyze
python run_cta_analysis.py --all

# Step 4: Summarize
python scripts/cta_summarize_results.py
```

### Analyze Specific Failing Skills

```bash
# Run only problematic tasks
python run_cta_analysis.py \
    --task springboot-tdd \
    --task service-mesh-observability \
    --task linkerd-patterns \
    --output json --output html
```

### Deep Dive into Single Task

```bash
# Analyze one task with all detail
python run_cta_analysis.py --task risk-metrics-calculation -v

# View results
cat cta_output/cta_analysis_risk-metrics-calculation_*.json | python -m json.tool

# Extract specific module results
python -c "
import json
result = json.load(open('cta_output/cta_analysis_risk-metrics-calculation_*.json'))
print('Divergences:', result['modules']['alignment']['total_divergences'])
print('SIPs:', result['modules']['sip_detection']['total_sips'])
print('Utility:', result['summary']['skill_utility'])"
```

### Batch Processing

```bash
# Process in groups of 10
for i in {1..5}; do
    start=$((($i-1)*10))
    end=$(($i*10))
    echo "Processing tasks $start-$end..."
    python run_cta_analysis.py --only task_${start},task_${end} --output json
    sleep 5
done
```

## Key Metrics to Track

| Metric | Meaning | Target |
|--------|---------|--------|
| ΔP (pass_rate_delta) | Improvement from skill | > 0 |
| Token overhead | Token ratio (with/without) | < 1.5 |
| Divergence count | Behavioral differences | > 0 |
| SIP confidence | Pattern detection confidence | > 0.5 |
| Utility class | Predicted skill quality | positive |

## Understanding Results

### Skill Utility Classes

- **Positive:** Skill likely helps (ΔP > 0)
- **Neutral:** No clear impact (ΔP = 0)
- **Negative:** Skill likely harms (ΔP < 0)

### SIP Types

**Constructive:** Want these ✓
- PS (Procedural Scaffolding)
- CN (Constraint Narrowing)
- EP (Edge-case Prompting)

**Neutral:** Acceptable ≈
- RR (Redundant Reiteration)
- PE (Parallel Exploration)

**Destructive:** Avoid these ✗
- SA (Surface Anchoring)
- CB (Concept Bleed)
- CD (Context Displacement)

## Documentation Links

- **Full guide:** `CTA_EXECUTION_GUIDE.md`
- **Framework docs:** `CTA_README.md`
- **Project structure:** `CTA_PROJECT_STRUCTURE.md`
- **Research plan:** `plan.md`
- **Module source:** `src/cta/`

## Performance Tips

```bash
# Analyze in parallel (bash)
for task in $(python run_cta_analysis.py --list-tasks | grep -v Total); do
    python run_cta_analysis.py --task "$task" &
    if [ $(jobs -r -p | wc -l) -ge 4 ]; then wait -n; fi
done

# Reduce memory usage
python run_cta_analysis.py --all --module1-only  # One module at a time

# Speed up with caching
touch .cta_cache  # Creates cache file (framework will use if exists)
```

## Environment Variables

```bash
# Set custom log level
export CTA_LOG_LEVEL=DEBUG
python run_cta_analysis.py --all

# Set output directory
export CTA_OUTPUT_DIR=/custom/path
python run_cta_analysis.py --all
```

## Help and Examples

```bash
# Show command help
python run_cta_analysis.py --help
python scripts/cta_prepare_data.py --help
python scripts/cta_summarize_results.py --help

# Show available tasks
python run_cta_analysis.py --list-tasks

# Run example analysis
python run_cta_analysis.py --task risk-metrics-calculation --output json
```

---

**Need more?** See `CTA_EXECUTION_GUIDE.md` for detailed instructions.
