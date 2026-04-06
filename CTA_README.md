# Counterfactual Trace Auditing (CTA) Framework

A comprehensive framework for auditing AI agent skills through execution trace analysis. CTA uses counterfactual trace analysis to understand **how**, **why**, and **when** skill documents affect agent behavior.

## Overview

CTA is built on the research plan for analyzing the effectiveness of Agent Skills in SWE-Skills-Bench. Rather than just measuring pass/fail rates, CTA:

1. **Collects** paired execution traces (with skill vs without skill)
2. **Segments** traces into SWE lifecycle phases
3. **Aligns** traces to find behavioral divergences
4. **Detects** Skill Influence Patterns (SIPs) that explain divergences
5. **Predicts** skill quality from static features

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CTA Pipeline                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Module 1: Trace Parser          → Parse Claude Code logs      │
│  Module 2: Phase Segmenter       → Segment into SWE phases     │
│  Module 3: Trace Aligner         → Align & find divergences    │
│  Module 4: SIP Detector          → Classify patterns           │
│  Module 5: Quality Predictor     → Predict skill utility       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

```bash
# Create a dedicated conda environment
conda create -n cta python=3.10 -y
conda activate cta

# Install dependencies
pip install -r requirements.txt

# Install additional CTA requirements
pip install scipy scikit-learn pyyaml numpy
```

### Basic Usage

```bash
# Analyze a single task
python run_cta_analysis.py --task risk-metrics-calculation

# Analyze all tasks
python run_cta_analysis.py --all

# Analyze with multiple output formats
python run_cta_analysis.py --task springboot-tdd --output json --output html --output markdown

# Verbose logging
python run_cta_analysis.py --task some-task -v

# List all available tasks
python run_cta_analysis.py --list-tasks
```

## Configuration

Configure the CTA framework using `cta_config.yaml`:

```yaml
data:
  trace_logs_dir: "./claude_process"     # Where execution logs are stored
  skills_dir: "./skills"                 # Where skill documents are stored
  task_metadata_file: "./config/tasks.json"  # Task metadata
  output_dir: "./cta_output"             # Output directory

modules:
  trace_parser:
    max_content_length: 5000             # Limit event content size

  trace_aligner:
    intent_similarity_threshold: 0.7     # Threshold for intent alignment

  sip_detector:
    min_detection_confidence: 0.5        # Minimum SIP confidence

  skill_predictor:
    cv_strategy: "leave_one_skill_out"   # Cross-validation approach
    model_type: "xgboost"                # Prediction model
```

## Data Models

### Core Data Structures

#### Event
Represents a single action in trace:
```python
Event(
    event_id: int,           # Sequential ID
    type: EventType,         # read, write, execute, reason, error
    target: str,             # File path, command, tool name
    content: str,            # Content/output of event
    reasoning: str,          # Agent's reasoning before event
    outcome: EventOutcome,   # success, failure, partial
    token_count: int,        # Token consumption
    timestamp: float         # Timestamp
)
```

#### Trace
Complete execution sequence:
```python
Trace(
    trace_id: str,
    events: List[Event],
    task_id: str,
    with_skill: bool,        # Whether skill was used
    temperature: float,      # Model temperature
    total_tokens: int,       # Total token consumption
    final_outcome: bool      # Pass/fail result
)
```

#### DivergenceRecord
Records where traces differ:
```python
DivergenceRecord(
    divergence_id: int,
    intent_pair: (Intent, Intent),    # Aligned intents
    phase: PhaseType,                 # Which phase
    actions_plus: List[Event],        # With-skill actions
    actions_minus: List[Event],       # Without-skill actions
    divergence_type: DivergenceType,  # Type of divergence
    skill_region: str,                # Related skill text
    skill_similarity: float           # Similarity score
)
```

#### SIPRecord
Detected Skill Influence Pattern:
```python
SIPRecord(
    sip_id: int,
    sip_type: SIPType,       # Type of pattern
    divergence_id: int,      # Related divergence
    task_id: str,
    confidence: float,       # Detection confidence
    evidence: Dict[str, Any] # Supporting features
)
```

## Module Details

### Module 1: Trace Parser
**Input:** Claude Code JSON logs  
**Output:** Structured Event and Trace objects

Converts Claude Code conversation logs into structured events:
- Maps tool calls (bash, read, write, etc.) to events
- Extracts reasoning text between tool calls
- Determines event outcomes from exit codes/errors
- Estimates token consumption

```python
from src.cta import TraceParser

parser = TraceParser()
trace = parser.parse_trace_file("path/to/log.json")
```

### Module 2: Phase Segmenter
**Input:** Traces  
**Output:** PhasedTrace objects with phase boundaries

Segments traces into SWE lifecycle phases using FSM:
- **Orientation:** Understanding project structure
- **Planning:** Strategy planning
- **Implementation:** Writing code
- **Validation:** Testing/building
- **Debugging:** Error fixing
- **Finalization:** Final adjustments

```python
from src.cta import PhaseSegmenter

segmenter = PhaseSegmenter()
phased_trace = segmenter.segment(trace)

# Get phase statistics
stats = segmenter.get_phase_statistics(phased_trace)
```

### Module 3: Trace Aligner
**Input:** Paired PhasedTraces (with_skill, without_skill)  
**Output:** DivergenceRecord objects

Two-level alignment strategy:
1. **Phase-level:** Dynamic Time Warping (DTW) on phase sequences
2. **Intent-level:** Semantic similarity matching of intents

Detects three types of divergences:
- **TARGET_MISMATCH:** Different files/commands
- **CONTENT_MISMATCH:** Different code changes
- **OUTCOME_MISMATCH:** Different results

```python
from src.cta import TraceAligner

aligner = TraceAligner(intent_similarity_threshold=0.7)
divergences = aligner.align_traces(phased_trace_plus, phased_trace_minus)
```

### Module 4: SIP Detector
**Input:** DivergenceRecord objects  
**Output:** SIPRecord objects with pattern classifications

Detects Skill Influence Patterns:

**Constructive SIPs:**
- **PS (Procedural Scaffolding):** Skill provides missing steps
- **CN (Constraint Narrowing):** Skill reduces search space
- **EP (Edge-case Prompting):** Skill reminds about edge cases

**Neutral SIPs:**
- **RR (Redundant Reiteration):** Skill content is redundant
- **PE (Parallel Exploration):** Skill causes exploration but same solution

**Destructive SIPs:**
- **SA (Surface Anchoring):** Agent copies hardcoded values literally
- **CB (Concept Bleed):** Broad skill causes confusion
- **CD (Context Displacement):** Skill text crowds out task requirements

```python
from src.cta import SIPDetector

detector = SIPDetector()
sips = detector.batch_detect(divergences)

# Get statistics
stats = detector.get_sip_statistics(sips)
```

### Module 5: Quality Predictor
**Input:** Skill document + Project metadata  
**Output:** SkillQualityScore predictions

Predicts skill utility (positive/neutral/negative) using features:

**Skill Features:**
- Template specificity (hardcoded vs abstract)
- Abstraction level (use of placeholders)
- Coverage breadth (number of topics)
- Document length
- Code-to-prose ratio
- Instruction density

**Project Features:**
- Tech stack match
- Version alignment
- Project complexity
- Baseline difficulty

**Interaction Features:**
- Semantic relevance
- API overlap
- Specificity-complexity ratio

```python
from src.cta import SkillQualityPredictor

predictor = SkillQualityPredictor()

# Single task
score = predictor.predict_utility(skill_doc, task_metadata)

# Batch
scores = predictor.predict_batch(skill_docs, task_metadata_list)

# Get risks
risks = predictor.analyze_skill_risks(skill_doc, skill_id)
```

## Execution Flow

### Step 1: Run SWE-Skills-Bench (Data Collection)

```bash
# Generate execution traces with skill
python run_all_skills.py --use-skill

# Generate execution traces without skill
python run_all_skills.py --no-use-skill
```

This generates Claude Code logs in `claude_process/` directory.

### Step 2: Run CTA Analysis (Module 1-2)

Parse traces and segment into phases:

```bash
python run_cta_analysis.py --all
```

This:
1. Parses all execution logs into Event sequences
2. Segments traces into SWE lifecycle phases
3. Saves phased traces for further analysis

### Step 3: Alignment and Divergence Detection (Module 3)

The pipeline automatically aligns paired traces and detects divergences:
- For each task: finds all (with-skill, without-skill) trace pairs
- Aligns phases using DTW
- Extracts intents and aligns semantically
- Records divergences with type and similarity

### Step 4: SIP Detection (Module 4)

Classifies divergences into Skill Influence Patterns:
- Extracts features from each divergence
- Applies rule-based and ML classifiers
- Records SIP type and confidence
- Generates evidence/explanation

### Step 5: Quality Prediction (Module 5)

Predicts skill quality:
- Extracts features from skill document
- Extracts features from project metadata
- Trains leave-one-skill-out predictor
- Predicts utility class (positive/neutral/negative)

## Output

All results are saved to `cta_output/` in multiple formats:

### JSON Format
```json
{
  "task_id": "risk-metrics-calculation",
  "summary": {
    "analysis_complete": true,
    "modules_executed": ["parsing", "segmentation", "alignment", "sip_detection", "quality_prediction"],
    "skill_utility": "positive",
    "dominant_sips": ["procedural_scaffolding", "constraint_narrowing"]
  },
  "modules": {
    "parsing": {
      "traces_with_skill": 3,
      "traces_without_skill": 3
    },
    "alignment": {
      "total_divergences": 12,
      "divergence_statistics": {...}
    },
    "sip_detection": {
      "total_sips": 15,
      "sip_statistics": {...}
    },
    "quality_prediction": {
      "skill_id": "risk-metrics-calculation",
      "utility_class": "positive",
      "probability": {"positive": 0.75, "neutral": 0.15, "negative": 0.1},
      "confidence": 0.75
    }
  }
}
```

### HTML Format
Interactive HTML report with visualizations and tables.

### Markdown Format
Structured report for documentation and sharing.

## Case Studies

The framework includes built-in analysis of key case studies from the research:

### Case 1: Best Positive Skill
**Skill:** `risk-metrics-calculation` (ΔP = +30%)

Demonstrates how Procedural Scaffolding works: skill provides financial formulas the agent's base knowledge doesn't contain.

### Case 2: Worst Negative Skill
**Skill:** `springboot-tdd` (ΔP = -10%)

Shows Surface Anchoring: agent copies incompatible Spring Boot version templates literally from skill.

### Case 3: Maximum Token Overhead
**Skill:** `service-mesh-observability` (ΔP = 0%, token increase: +451%)

Illustrates Parallel Exploration: skill causes agent to explore many alternatives before returning to original solution.

### Case 4: Context Interference
**Skill:** `linkerd-patterns` (ΔP = -9.1%)

Documents how concept bleed and context displacement cascade into failure.

## Advanced Usage

### Run Specific Module Only

```bash
# Only Module 1 (Parsing)
python run_cta_analysis.py --task risk-metrics-calculation --module1-only

# Only Module 4 (SIP Detection)
python run_cta_analysis.py --task springboot-tdd --module4-only
```

### Analyze Specific Task Set

```bash
# Only analyze positive/negative skills
python run_cta_analysis.py --all --only positive_skills.txt
```

### Generate Comparative Report

```bash
python scripts/cta_comparative_analysis.py --output comparison_report.html
```

## Research Questions

The CTA framework is designed to answer:

**RQ1 (Behavior Characterization):** What types of behavior changes do skills cause? How are SIPs distributed across positive/neutral/negative skills?

**RQ2 (Attribution Analysis):** Which SIPs are statistically associated with outcome changes? What are their effect sizes?

**RQ3 (Predictive Ability):** Can we predict skill utility from static features? How well does the predictor generalize?

**RQ4 (Design Guidance):** What skill design principles maximize positive patterns and minimize negative ones?

## Key Insights from Research Plan

- **80% of skills have zero pass rate improvement** but vary dramatically in token efficiency
- **Skill influence is not binary** - we can identify constructive, neutral, and destructive patterns
- **Predictability is achievable** - skill features correlate with outcomes
- **Design matters** - high-abstraction, low-specificity skills are more beneficial

## Troubleshooting

### No traces found
- Ensure traces are saved in `claude_process/` from running `run_all_skills.py`
- Check trace file naming and structure

### Low alignment quality
- Check `intent_similarity_threshold` in config (default 0.7)
- May need to reduce threshold if traces diverge significantly

### SIP detection low confidence
- Ensure `annotated_divergences.json` exists if training custom classifier
- Rule-based detection should work without training

### Prediction model underperforming
- Check feature extraction in Module 5
- May need to adjust feature scaling or model hyperparameters

## Contributing

To extend CTA:

1. **Add new phase types:** Edit `PhaseType` enum in `data_models.py` and update FSM
2. **Add new SIP types:** Define new `SIPType` in `data_models.py` and update detector rules
3. **Improve alignment:** Enhance intent extraction or semantic similarity in Module 3
4. **Enhance prediction:** Add new features in Module 5's feature extraction

## References

- Research Plan: `plan.md`
- Original Benchmark: SWE-Skills-Bench (Han et al., 2026)
- Related Work: SUVA framework for auditing LLM reasoning

## License

MIT - See LICENSE file

---

**Questions?** Check the research plan (`plan.md`) for detailed methodology and theoretical background.
