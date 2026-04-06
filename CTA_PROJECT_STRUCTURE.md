# CTA Project Structure

Complete overview of the Counterfactual Trace Auditing framework implementation.

## Directory Layout

```
SWE-Skills-Bench/
├── src/cta/                          # CTA Framework Core
│   ├── __init__.py                   # Module exports
│   ├── data_models.py                # Core data structures
│   ├── module1_parser.py             # Trace parsing
│   ├── module2_segmenter.py          # Phase segmentation
│   ├── module3_aligner.py            # Trace alignment & divergence
│   ├── module4_detector.py           # SIP detection
│   ├── module5_predictor.py          # Skill quality prediction
│   └── pipeline.py                   # Orchestration pipeline
│
├── scripts/                          # Analysis & utility scripts
│   ├── cta_prepare_data.py           # Trace preparation & validation
│   └── cta_summarize_results.py      # Result aggregation & summary
│
├── cta_output/                       # Analysis results (generated)
│   ├── cta_analysis_*.json           # Per-task analysis results
│   ├── cta_analysis_*.html           # HTML reports
│   ├── cta_analysis_*.md             # Markdown reports
│   ├── cta_combined_results.json     # Combined results
│   └── cta_summary.json              # Summary statistics
│
├── config/                           # Configuration files
│   └── cta_task_metadata.json        # Generated task metadata
│
├── CTA_README.md                     # Framework documentation
├── CTA_EXECUTION_GUIDE.md            # Step-by-step execution guide
├── CTA_PROJECT_STRUCTURE.md          # This file
├── cta_config.yaml                   # Framework configuration
├── requirements_cta.txt              # Additional Python dependencies
└── run_cta_analysis.py               # Main CTA runner script
```

## File Descriptions

### Core Framework (`src/cta/`)

#### `__init__.py`
Exports all CTA classes for easy importing:
```python
from src.cta import TraceParser, PhaseSegmenter, TraceAligner, SIPDetector, SkillQualityPredictor
```

#### `data_models.py`
Core data structures used throughout the framework:
- **EventType**: Types of execution events (read, write, execute, etc.)
- **Event**: Single action in trace
- **Trace**: Complete execution sequence
- **Phase**: Segment of trace (Orientation, Planning, Implementation, etc.)
- **PhasedTrace**: Trace split into phases
- **Intent**: Extracted agent intent from reasoning
- **DivergenceRecord**: Where with-skill and without-skill traces differ
- **SIPRecord**: Detected Skill Influence Pattern
- **SIPType**: Pattern types (PS, CN, SA, etc.)
- **SkillQualityScore**: Skill utility prediction

#### `module1_parser.py` (Trace Collection & Parsing)
**Input:** Claude Code JSON logs  
**Output:** Event sequences and Trace objects

Converts Claude Code conversation logs to structured traces:
- Parses JSON conversation format
- Maps tool calls to events
- Extracts and aggregates reasoning text
- Determines event outcomes and token counts

**Key Classes:**
- `TraceParser`: Main parser class
  - `parse_claude_log()`: Parse from log data
  - `parse_trace_file()`: Load from JSON file
  - `batch_parse()`: Parse directory of traces

#### `module2_segmenter.py` (Phase Segmentation)
**Input:** Trace objects  
**Output:** PhasedTrace objects

Segments traces into SWE lifecycle phases using finite state machine:
- **FSMState**: States (INIT, ORIENTATION, PLANNING, IMPLEMENTATION, VALIDATION, DEBUGGING, FINALIZATION)
- **Phase transition rules:** Detects phase boundaries based on event types and keywords

**Key Classes:**
- `PhaseSegmenter`: FSM-based segmentation
  - `segment()`: Segment single trace
  - `segment_batch()`: Segment multiple traces
  - `get_phase_statistics()`: Phase distribution
  - `validate_phases()`: Quality validation

#### `module3_aligner.py` (Trace Alignment & Divergence Detection)
**Input:** Paired PhasedTrace objects (with-skill, without-skill)  
**Output:** DivergenceRecord objects

Two-level trace alignment:
1. **Phase-level:** Dynamic Time Warping (DTW) on phase sequences
2. **Intent-level:** Semantic similarity matching

**Key Classes:**
- `TraceAligner`: Alignment engine
  - `align_traces()`: Main alignment function
  - `_align_phases()`: Phase-level DTW alignment
  - `_align_intents()`: Intent-level semantic alignment
  - `_determine_divergence_type()`: Classify divergence types
  - `get_divergence_statistics()`: Aggregate stats

#### `module4_detector.py` (SIP Detection)
**Input:** DivergenceRecord objects  
**Output:** SIPRecord objects

Classifies divergences into Skill Influence Patterns:
- **Constructive:** PS, CN, EP
- **Neutral:** RR, PE
- **Destructive:** SA, CB, CD

**Key Classes:**
- `SIPDetector`: Pattern detector
  - `detect()`: Classify single divergence
  - `batch_detect()`: Classify multiple divergences
  - `_extract_features()`: Feature extraction
  - `_rule_based_detection()`: Pattern matching rules
  - `train_classifier()`: Optional ML-based training
  - `analyze_outcome_relationship()`: Divergence-outcome analysis
  - `get_sip_statistics()`: Aggregate SIP stats

#### `module5_predictor.py` (Skill Quality Prediction)
**Input:** Skill document + Project metadata  
**Output:** SkillQualityScore predictions

Predicts skill utility from static features:
- **Skill features:** Specificity, abstraction, coverage, length, code ratio, instruction density
- **Project features:** Tech match, version alignment, complexity, baseline difficulty
- **Interaction features:** Semantic relevance, API overlap, ratios

**Key Classes:**
- `SkillQualityPredictor`: Quality predictor
  - `predict_utility()`: Single skill prediction
  - `predict_batch()`: Batch predictions
  - `extract_skill_features()`: Skill feature extraction
  - `extract_project_features()`: Project feature extraction
  - `rank_by_utility()`: Rank skills by predicted quality
  - `analyze_skill_risks()`: Risk analysis

#### `pipeline.py` (Orchestration)
**Input:** Task ID  
**Output:** Comprehensive analysis results

Orchestrates all five modules:
- Loads configuration
- Runs modules in sequence
- Aggregates results
- Generates reports

**Key Classes:**
- `CTAPipeline`: Main orchestrator
  - `run_full_analysis()`: Complete analysis for task
  - `save_results()`: Export in JSON/HTML/Markdown
  - Module execution methods: `_run_module1()` through `_run_module5()`

### Scripts (`scripts/`)

#### `cta_prepare_data.py`
Data preparation and validation:
- Validates trace file structure
- Analyzes coverage across tasks/conditions
- Generates task metadata file for Module 5
- Creates statistics about pass rates and token usage

```bash
python scripts/cta_prepare_data.py --traces-dir ./claude_process
```

#### `cta_summarize_results.py`
Results aggregation and reporting:
- Loads all CTA analysis results
- Aggregates statistics across tasks
- Identifies case studies
- Generates comprehensive summary report
- Exports JSON summary

```bash
python scripts/cta_summarize_results.py --results-dir ./cta_output
```

### Configuration Files

#### `cta_config.yaml`
Main CTA configuration:
- Data paths (traces, skills, task metadata, output)
- Module-specific parameters
- Feature thresholds
- Output formats
- Case study definitions

Can be overridden via command-line arguments.

#### `requirements_cta.txt`
Additional Python dependencies:
- numpy, scipy: Numerical computing
- scikit-learn, xgboost: Machine learning
- pyyaml: Configuration files
- matplotlib, seaborn: Optional visualization
- pandas: Optional data analysis

### Main Entry Point

#### `run_cta_analysis.py`
Command-line interface for CTA analysis:

```bash
python run_cta_analysis.py --task <task_id>      # Single task
python run_cta_analysis.py --all                  # All tasks
python run_cta_analysis.py --list-tasks           # Show available tasks
python run_cta_analysis.py --task X --module1-only  # Single module
```

### Documentation

#### `CTA_README.md`
- Framework overview
- Architecture explanation
- Detailed module documentation
- Data models reference
- Advanced usage examples
- Troubleshooting guide

#### `CTA_EXECUTION_GUIDE.md`
- Step-by-step execution guide
- Phase-by-phase breakdown
- Checkpoints and verification steps
- Timeline and duration estimates
- Troubleshooting specific issues
- Output file reference

#### `CTA_PROJECT_STRUCTURE.md`
This file - project structure and file descriptions.

## Data Flow

```
Phase 1: Execution Traces (from SWE-Skills-Bench)
    ↓
    run_all_skills.py --use-skill
    run_all_skills.py --no-use-skill
    ↓
    claude_process/claude_output/*.json
    
Phase 2: CTA Preparation
    ↓
    cta_prepare_data.py
    ↓
    config/cta_task_metadata.json
    
Phase 3: CTA Analysis
    ↓
    run_cta_analysis.py --all
    ↓
    [Module 1] → Trace objects
    [Module 2] → PhasedTrace objects
    [Module 3] → DivergenceRecord objects
    [Module 4] → SIPRecord objects
    [Module 5] → SkillQualityScore objects
    ↓
    cta_output/cta_analysis_*.json
    cta_output/cta_combined_results.json
    
Phase 4: Result Summary
    ↓
    cta_summarize_results.py
    ↓
    cta_output/cta_summary.json
    ↓
    Insights and Findings
```

## Module Dependencies

```
Module 1 (Parser)
    ├── Reads: claude_process/claude_output/*.json
    └── Produces: Trace objects
         ↓
Module 2 (Segmenter)
    ├── Reads: Trace objects
    └── Produces: PhasedTrace objects
         ↓
Module 3 (Aligner)
    ├── Reads: PhasedTrace pairs (with-skill, without-skill)
    └── Produces: DivergenceRecord objects
         ↓
Module 4 (SIP Detector)
    ├── Reads: DivergenceRecord objects
    └── Produces: SIPRecord objects
         ↓
Module 5 (Quality Predictor)
    ├── Reads: config/cta_task_metadata.json
    │           skill documents
    │           SIPRecord objects
    └── Produces: SkillQualityScore objects
         ↓
Pipeline Aggregation
    ├── Produces: JSON/HTML/Markdown reports
    └── Produces: cta_summary.json
```

## Key Constants and Thresholds

**From `cta_config.yaml`:**
- `intent_similarity_threshold`: 0.7 (for intent alignment)
- `min_detection_confidence`: 0.5 (for SIP detection)
- `max_content_length`: 5000 chars (event content limit)

**From Module implementations:**
- `embedding_dim`: 100 (simple hash-based embeddings)
- DTW distance: 0 for same phase, 1 for different
- Phase transition detection: Keyword matching

## Testing and Validation

To test the framework:

```bash
# Test single module
python -c "from src.cta import TraceParser; print('Module 1 OK')"
python -c "from src.cta import PhaseSegmenter; print('Module 2 OK')"
python -c "from src.cta import TraceAligner; print('Module 3 OK')"
python -c "from src.cta import SIPDetector; print('Module 4 OK')"
python -c "from src.cta import SkillQualityPredictor; print('Module 5 OK')"

# Test pipeline
python -c "from src.cta import CTAPipeline; print('Pipeline OK')"
```

## Integration with SWE-Skills-Bench

CTA integrates with existing SWE-Skills-Bench infrastructure:

```
Existing SWE-Skills-Bench
├── run_all_skills.py          → Generates execution traces
├── run_all_skills_eval.py     → Evaluates task completion
└── config/benchmark_config.yaml → Task definitions
                                    ↓ (used by CTA)
CTA Framework
├── Reads trace logs
├── Reads task configs
└── Produces analysis results
```

No modifications needed to existing SWE-Skills-Bench code.

## Extension Points

1. **Custom Phase Types:** Modify `PhaseType` enum in `data_models.py`
2. **Custom SIP Types:** Add to `SIPType` enum and update detection rules
3. **Custom Features:** Extend feature extraction in Module 5
4. **Custom Models:** Replace rule-based detectors with trained models
5. **Custom Reports:** Add export formats in `pipeline.py`

## Performance Characteristics

| Component | Complexity | Time per Task |
|-----------|-----------|---------------|
| Module 1 (Parser) | O(n) events | ~5 seconds |
| Module 2 (Segmenter) | O(n) events | ~2 seconds |
| Module 3 (Aligner) | O(p² × i²) phases/intents | ~10 seconds |
| Module 4 (SIP Detector) | O(d × f) divergences/features | ~3 seconds |
| Module 5 (Predictor) | O(1) feature extraction | ~1 second |
| **Total per task** | | ~21 seconds |
| **All 49 tasks** | | ~17 minutes |

*Actual times depend on system and trace sizes.*

---

For questions or extending the framework, see `CTA_README.md` for methodology and `CTA_EXECUTION_GUIDE.md` for practical instructions.
