# Counterfactual Trace Auditing (CTA)

Reproduce the analysis and LaTeX inputs for **`draft/neurips_2026.tex`** (49-task SWE-Skills-Bench study, paired with-skill / without-skill traces).

**Benchmark-only usage** (HuggingFace dataset, Docker runs, pass-rate tables without CTA) lives in [`README_SWE-Skills-Bench.md`](README_SWE-Skills-Bench.md).

---

## Prerequisites

- **Python** 3.10+ (example: `conda create -n cta python=3.10` then `conda activate cta`)
- **Install:** `pip install -r requirements.txt` and `pip install -r requirements_cta.txt`
- **Credentials:** copy `.env.example` to `.env` and set `ANTHROPIC_AUTH_TOKEN` (and `ANTHROPIC_BASE_URL` if using a proxy). Model names in `.env` are used when the agent runs inside Docker.
- **Docker** is required only to **generate new** execution traces with `run_all_skills.py`. If you already have traces under `claude_process/`, you can skip it for CTA.
- **Linux / Docker permissions:** if `docker ps` reports permission denied on the socket, run `sudo usermod -aG docker "$USER"` and start a new shell (or `newgrp docker`).

---

## Reproduce the draft pipeline (end to end)

Approximate wall time for a full 49-task pass: **several hours** for trace generation plus **~15–30 min** for eval, **~1–2 h** for CTA analysis (varies by machine).

### 1. Paired execution traces (skip if you already have them)

Generates Claude Code stream logs under `claude_process/…/claude_thinking/*.jsonl`.

```bash
python run_all_skills.py --use-skill
python run_all_skills.py --no-use-skill
```

Useful flags: `--resume`, `--dry-run`, `--only id1,id2`, `--skip id1,id2`.

### 2. Evaluate terminal repo state (needed for real \(\Delta P\) in metadata)

Runs unit tests and writes `reports/**/eval/eval_report_*.json`. Without this step, `cta_prepare_data.py` cannot attach pass rates and **`pass_rate_delta` stays at zero** in `config/cta_task_metadata.json`.

```bash
python run_all_skills_eval.py --use-skill --use-agent
python run_all_skills_eval.py --no-use-skill --use-agent
```

Skip only if you intentionally want purely structural CTA metrics (divergences, SIP patterns, tokens) and accept placeholder outcome statistics.

### 3. Prepare task metadata

```bash
python scripts/cta_prepare_data.py \
  --traces-dir ./claude_process \
  --output ./config/cta_task_metadata.json
```

### 4. Run CTA analysis (all tasks)

```bash
python run_cta_analysis.py --all -v
```

Configuration: `cta_config.yaml` (trace dir, `task_metadata_file: ./config/cta_task_metadata.json`, alignment thresholds, etc.). Per-module debugging: `python run_cta_analysis.py --task <skill-id> --module3-only` (and `--module1-only` … `--module5-only`).

### 5. Corpus summary JSON

```bash
python scripts/cta_summarize_results.py \
  --results-dir ./cta_output \
  --output ./cta_output/cta_summary.json
```

### 6. Regenerate LaTeX fragments consumed by the draft

Run after a fresh CTA pass when you need updated tables or appendix text:

```bash
python scripts/cta_paper_stats.py      # draft/tab_stratified.tex, tab_sips.tex, tab_topdelta.tex
python scripts/cta_face_validity.py    # draft/face_validity_sample.{md,json} (SIP spot-check worksheet)
python scripts/cta_case_traces.py      # draft/appendix_cases.tex (case-study diffs + skill excerpts)
```

Then compile `draft/neurips_2026.tex` (paths are relative to that file).

---

## Output map (draft ↔ disk)

| Draft artifact | Produced by |
|----------------|-------------|
| Main text numbers/tables (`tab_stratified`, `tab_sips`, `tab_topdelta`) | `scripts/cta_paper_stats.py` → `draft/tab_*.tex` |
| Appendix case studies | `scripts/cta_case_traces.py` → `draft/appendix_cases.tex` |
| Aggregates / per-task JSON | `cta_output/`, `cta_output/cta_summary.json` |
| Pass-rate side metadata | `scripts/cta_prepare_data.py` → `config/cta_task_metadata.json` |

---

## Code layout (quick reference)

| Path | Role |
|------|------|
| `run_cta_analysis.py` | CLI for the five CTA modules |
| `src/cta/` | Parser, phase segmentation, alignment, SIP detection, predictor |
| `scripts/cta_prepare_data.py` | Trace validation + metadata + eval enrichment |
| `scripts/cta_summarize_results.py` | Roll up `cta_output/` into `cta_summary.json` |
| `scripts/cta_paper_stats.py`, `cta_face_validity.py`, `cta_case_traces.py` | Paper-facing generators |

---

## License

MIT. See `LICENSE`.
