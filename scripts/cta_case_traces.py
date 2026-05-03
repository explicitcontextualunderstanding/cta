#!/usr/bin/env python3
"""Generate the LaTeX appendix that side-by-sides each case-study trace
against its without-skill counterpart, with code-diff coloring.

For every (case, with-skill jsonl, without-skill jsonl, skill_md) tuple we
emit:

    \\subsection{Case N: <task>}
        - a short skill-template excerpt (lstlisting),
        - a two-column tabular of action steps with green = only in
          with-skill, red = only in without-skill, white = shared.

The output is written to ``draft/appendix_cases.tex`` and is consumed by
``draft/neurips_2026.tex`` via ``\\input{appendix_cases.tex}``.

Run from the repo root:

    python scripts/cta_case_traces.py
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = REPO_ROOT / "claude_process" / "claude-sonnet-4-5-20250929" / "batch1" / "claude_thinking"
SKILLS_DIR = REPO_ROOT / "skills"
OUTPUT_TEX = REPO_ROOT / "draft" / "appendix_cases.tex"

# Hard cap on rows in the side-by-side diff so the appendix stays readable.
MAX_ROWS_PER_CASE = 28
# Per-cell text width in characters before we soft-wrap with `\\`.
CELL_CHAR_BUDGET = 52


@dataclass
class Action:
    """A canonical, comparable summary of one tool invocation."""
    key: str           # canonical key used for diffing (e.g. "write:app.py")
    label: str         # human-readable cell content
    raw_index: int     # original 0-based position in the trace's action list


# ---------------------------------------------------------------------------
# Trace parsing
# ---------------------------------------------------------------------------


def _basename(path: str) -> str:
    if not path:
        return "?"
    name = Path(path).name
    return name or path


def _bash_command_summary(cmd: str) -> str:
    # Collapse newlines/tabs/multiple spaces so the cell stays one line.
    cmd = re.sub(r"\s+", " ", cmd).strip()
    if not cmd:
        return "bash"
    first_token = cmd.split()[0]
    # Heuristics to keep the cell short but informative.
    if first_token in {"mkdir", "ls", "cat", "rm", "cp", "mv", "chmod"}:
        # Show "cmd <last-arg-basename>"
        parts = cmd.split()
        target = _basename(parts[-1]) if len(parts) > 1 else ""
        return f"{first_token} {target}".strip()
    if first_token in {"cd", "pwd"}:
        return cmd[:CELL_CHAR_BUDGET]
    # Show first ~ CELL_CHAR_BUDGET chars of the command.
    return cmd[:CELL_CHAR_BUDGET]


def _summarize_tool_call(tool_name: str, tool_input: dict) -> Optional[Action]:
    """Convert a raw Claude Code tool_use block into a comparable Action."""
    if not isinstance(tool_input, dict):
        return None
    name = tool_name or "?"
    if name == "Bash":
        cmd = tool_input.get("command", "")
        first = cmd.strip().split()[0] if cmd.strip() else ""
        # Discriminate by 1st token + length bucket so different `bash` calls
        # don't collapse to a single diff token.
        key = f"bash:{first}:{min(len(cmd) // 40, 4)}"
        label = f"Bash: {_bash_command_summary(cmd)}"
        return Action(key=key, label=label, raw_index=-1)
    if name in {"Write", "Edit", "MultiEdit"}:
        target = tool_input.get("file_path") or tool_input.get("path") or "?"
        bn = _basename(target)
        key = f"{name.lower()}:{bn}"
        label = f"{name}: {bn}"
        return Action(key=key, label=label, raw_index=-1)
    if name == "Read":
        target = tool_input.get("file_path") or tool_input.get("path") or "?"
        bn = _basename(target)
        return Action(key=f"read:{bn}", label=f"Read: {bn}", raw_index=-1)
    if name == "Grep":
        pat = tool_input.get("pattern") or ""
        return Action(
            key=f"grep:{pat[:30]}",
            label=f"Grep: {pat[:CELL_CHAR_BUDGET]}",
            raw_index=-1,
        )
    if name == "Glob":
        pat = tool_input.get("pattern") or tool_input.get("glob_pattern") or ""
        return Action(
            key=f"glob:{pat[:30]}",
            label=f"Glob: {pat[:CELL_CHAR_BUDGET]}",
            raw_index=-1,
        )
    if name == "TodoWrite":
        return Action(key="todo", label="TodoWrite (plan update)", raw_index=-1)
    # Fall-through: unknown tool, keep it but don't try to discriminate.
    return Action(key=f"tool:{name}", label=f"{name}", raw_index=-1)


def extract_actions(trace_path: Path) -> List[Action]:
    """Return the ordered list of Action summaries for a trace jsonl."""
    actions: List[Action] = []
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            content = (rec.get("message") or {}).get("content") or []
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") != "tool_use":
                    continue
                act = _summarize_tool_call(c.get("name", ""), c.get("input") or {})
                if act is None:
                    continue
                act.raw_index = len(actions)
                actions.append(act)
    return actions


# ---------------------------------------------------------------------------
# Side-by-side diff
# ---------------------------------------------------------------------------


@dataclass
class DiffRow:
    """One row in the side-by-side diff: optional left/right cell + tag."""
    left: Optional[Action]
    right: Optional[Action]
    tag: str  # "shared" | "only-with" | "only-without"


def diff_actions(without_actions: List[Action], with_actions: List[Action]) -> List[DiffRow]:
    """Produce a row-aligned diff using SequenceMatcher on canonical keys."""
    a_keys = [a.key for a in without_actions]
    b_keys = [a.key for a in with_actions]
    sm = difflib.SequenceMatcher(a=a_keys, b=b_keys, autojunk=False)
    rows: List[DiffRow] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                rows.append(DiffRow(
                    left=without_actions[i1 + k],
                    right=with_actions[j1 + k],
                    tag="shared",
                ))
        elif op == "delete":
            for k in range(i2 - i1):
                rows.append(DiffRow(
                    left=without_actions[i1 + k],
                    right=None,
                    tag="only-without",
                ))
        elif op == "insert":
            for k in range(j2 - j1):
                rows.append(DiffRow(
                    left=None,
                    right=with_actions[j1 + k],
                    tag="only-with",
                ))
        elif op == "replace":
            # Pair them up positionally; remainder gets one-sided rows.
            n_left = i2 - i1
            n_right = j2 - j1
            n_pair = min(n_left, n_right)
            for k in range(n_pair):
                rows.append(DiffRow(
                    left=without_actions[i1 + k],
                    right=with_actions[j1 + k],
                    tag="replace",
                ))
            for k in range(n_pair, n_left):
                rows.append(DiffRow(
                    left=without_actions[i1 + k],
                    right=None,
                    tag="only-without",
                ))
            for k in range(n_pair, n_right):
                rows.append(DiffRow(
                    left=None,
                    right=with_actions[j1 + k],
                    tag="only-with",
                ))
    return rows


def truncate_rows(rows: List[DiffRow], max_rows: int = MAX_ROWS_PER_CASE) -> List[DiffRow]:
    """Cap row count, preferring to keep all coloured (non-shared) rows.

    We always keep every row whose tag is *not* "shared", and then fill the
    remaining budget with shared rows in order so the overall flow still reads
    chronologically. Truncation is marked with a sentinel ellipsis row.
    """
    if len(rows) <= max_rows:
        return rows
    coloured_ix = [i for i, r in enumerate(rows) if r.tag != "shared"]
    shared_ix = [i for i, r in enumerate(rows) if r.tag == "shared"]
    budget = max(max_rows - 1, 1)  # leave one slot for the ellipsis row
    if len(coloured_ix) >= budget:
        kept_ix = sorted(coloured_ix[:budget])
    else:
        remain = budget - len(coloured_ix)
        # Evenly sample shared rows to preserve chronological flow.
        if remain <= 0:
            kept_shared: List[int] = []
        elif len(shared_ix) <= remain:
            kept_shared = shared_ix
        else:
            stride = len(shared_ix) / remain
            kept_shared = [shared_ix[int(i * stride)] for i in range(remain)]
        kept_ix = sorted(set(coloured_ix) | set(kept_shared))
    out: List[DiffRow] = []
    last_ix = -1
    for ix in kept_ix:
        if last_ix != -1 and ix > last_ix + 1:
            out.append(DiffRow(left=None, right=None, tag="elide"))
        out.append(rows[ix])
        last_ix = ix
    if last_ix < len(rows) - 1:
        out.append(DiffRow(left=None, right=None, tag="elide"))
    return out


# ---------------------------------------------------------------------------
# LaTeX rendering
# ---------------------------------------------------------------------------


_LATEX_ESCAPE = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(s: str) -> str:
    out = []
    for ch in s:
        out.append(_LATEX_ESCAPE.get(ch, ch))
    return "".join(out)


def cell_text(action: Optional[Action]) -> str:
    if action is None:
        return r"\textit{--}"
    label = action.label
    if len(label) > CELL_CHAR_BUDGET:
        label = label[: CELL_CHAR_BUDGET - 1] + "\u2026"
    return r"\texttt{" + latex_escape(label) + "}"


def render_diff_table(rows: List[DiffRow]) -> str:
    """Render the diff as a tabular with green/red row coloring."""
    out: List[str] = []
    out.append(r"\begin{small}")
    out.append(r"\begin{tabularx}{\textwidth}{@{}r >{\raggedright\arraybackslash}X >{\raggedright\arraybackslash}X@{}}")
    out.append(r"\toprule")
    out.append(r"\# & \textbf{Without-skill trace} & \textbf{With-skill trace} \\")
    out.append(r"\midrule")
    step = 0
    for row in rows:
        if row.tag == "elide":
            out.append(r"\multicolumn{3}{c}{\textit{\ldots\ omitted}} \\")
            continue
        step += 1
        if row.tag == "only-without":
            colour = r"\rowcolor{red!18}"
        elif row.tag == "only-with":
            colour = r"\rowcolor{green!22}"
        elif row.tag == "replace":
            colour = r"\rowcolor{yellow!22}"
        else:
            colour = ""
        if colour:
            out.append(colour)
        out.append(f"{step} & {cell_text(row.left)} & {cell_text(row.right)} \\\\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabularx}")
    out.append(r"\end{small}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Skill template excerpting
# ---------------------------------------------------------------------------


def excerpt_skill(md_path: Path, anchor_substrings: List[str], max_lines: int = 22) -> str:
    """Return a short, representative excerpt of a skill markdown.

    We grab the first ``max_lines`` lines of the first section whose heading
    or body matches any of ``anchor_substrings``. If nothing matches we fall
    back to the first non-trivial code block in the file.
    """
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find heading sections; each section is (header_index, body_lines).
    sections: List[List[str]] = []
    cur: List[str] = []
    for ln in lines:
        if ln.startswith("## ") and cur:
            sections.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        sections.append(cur)

    selected: Optional[List[str]] = None
    # Prefer sections whose H2 heading itself matches the anchors; fall back
    # to body-text matches. Anchor matching skips the YAML front-matter.
    body_sections = [
        sec for sec in sections
        if not (sec and sec[0].startswith("---"))
    ]
    for sec in body_sections:
        if not sec:
            continue
        head = sec[0].lower()
        if head.startswith("## ") and any(a.lower() in head for a in anchor_substrings):
            selected = sec
            break
    if selected is None:
        for sec in body_sections:
            joined = "\n".join(sec).lower()
            if any(a.lower() in joined for a in anchor_substrings):
                selected = sec
                break
    if selected is None:
        # Fallback: first ``` block + its surrounding heading.
        for i, ln in enumerate(lines):
            if ln.startswith("```"):
                start = max(0, i - 2)
                end = i + 1
                while end < len(lines) and not lines[end].startswith("```"):
                    end += 1
                selected = lines[start : end + 1]
                break
    if selected is None:
        selected = lines[:max_lines]

    # Trim leading blank lines, cap to max_lines.
    while selected and not selected[0].strip():
        selected = selected[1:]
    if len(selected) > max_lines:
        selected = selected[:max_lines] + ["...(skill excerpt truncated)..."]

    return "\n".join(selected)


def render_skill_block(skill_id: str, excerpt: str) -> str:
    """Wrap a skill excerpt in a framed lstlisting block.

    We deliberately avoid putting ``lstlisting`` inside ``tcolorbox`` since
    that combination needs special verbatim handling (``\\tcblisting`` from
    the listings library). A plain ``lstlisting`` with the ``framed`` style
    is portable across NeurIPS-style templates and renders almost
    identically.
    """
    out = []
    out.append(
        "% Full skill template path (author ref): skills/"
        + skill_id
        + "/SKILL.md"
    )
    out.append(
        r"\noindent\textit{Skill template excerpt: \texttt{"
        + latex_escape(skill_id)
        + r"}.}"
    )
    out.append(r"\begin{lstlisting}[basicstyle=\ttfamily\scriptsize, "
               r"breaklines=true, columns=fullflexible, frame=single, "
               r"framerule=0.4pt, rulecolor=\color{gray!50}, "
               r"backgroundcolor=\color{gray!7}, xleftmargin=2pt, "
               r"xrightmargin=2pt, framexleftmargin=2pt, framextopmargin=2pt, "
               r"framexbottommargin=2pt]")
    out.append(excerpt)
    out.append(r"\end{lstlisting}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


CASES = [
    {
        "case_no": 1,
        "task": "prompt-engineering-patterns",
        "title": "Procedural premature-closure (negative; out-of-taxonomy)",
        "with_glob": "claude_prompt-engineering-patterns_use-agent-true_use-skill-true_*.jsonl",
        "without_glob": "claude_prompt-engineering-patterns_use-agent-true_use-skill-false_*.jsonl",
        "skill_anchors": ["## Quick Start", "## Template", "## Core Capabilities"],
        "delta_p": "-20.0",
        "tok": "1.09",
        "summary": (
            "The skill prescribes a numbered procedure that ends at "
            "\\emph{commit and document}. The with-skill trace halts there, "
            "while the without-skill trace continues into a validation loop "
            "that the unit-test target depends on. Note especially the "
            "\\textit{absence} of late-trace re-validation steps on the "
            "with-skill side."
        ),
    },
    {
        "case_no": 2,
        "task": "gitlab-ci-patterns",
        "title": "Search-space pruning at high token cost (positive)",
        "with_glob": "claude_gitlab-ci-patterns_use-agent-true_use-skill-true_*.jsonl",
        "without_glob": "claude_gitlab-ci-patterns_use-agent-true_use-skill-false_*.jsonl",
        "skill_anchors": ["## Basic Pipeline Structure", "## Multi-stage", "stages:"],
        "delta_p": "+14.3",
        "tok": "22.24",
        "summary": (
            "The with-skill agent reads the skill document at length and "
            "writes a richer \\texttt{.gitlab-ci.yml} with the canonical "
            "stage layout the skill prescribes; the without-skill agent "
            "explores fewer YAML structures but writes a smaller pipeline. "
            "Most green rows correspond to skill-driven scaffolding; the "
            "$22\\times$ token overhead is dominated by repeated skill "
            "consultation in the orientation phase, not by the implementation "
            "phase itself (which has only 4/16 of the bundle's divergences)."
        ),
    },
    {
        "case_no": 3,
        "task": "bash-defensive-patterns",
        "title": "Surface-anchoring as the dominant mechanism even when $\\Delta P > 0$ (mixed)",
        "with_glob": "claude_bash-defensive-patterns_use-agent-true_use-skill-true_*.jsonl",
        "without_glob": "claude_bash-defensive-patterns_use-agent-true_use-skill-false_*.jsonl",
        "skill_anchors": ["## Core Defensive Principles", "Strict Mode", "## Error Trapping"],
        "delta_p": "+18.2",
        "tok": "0.90",
        "summary": (
            "The with-skill agent verbatim copies the skill's defensive-shell "
            "header (\\texttt{set -Eeuo pipefail}, \\texttt{trap}-based "
            "cleanup, quoted variables) into project scripts, and authors two "
            "test files (\\textsc{Unilateral\\_Action}) that the without-skill "
            "trace never touches. The 10 \\textsc{SA} fires are visible as "
            "concentrated green rows in the implementation segment; the "
            "without-skill agent writes shorter, less defensive scripts and "
            "skips the test scaffolding entirely."
        ),
    },
    {
        # Case 4 representative: a different mid-range bundle than Case 3, so
        # the appendix shows a second flavour of unilateral-action writes
        # (here: extra REPL helpers + scratch namespaces). The text frames
        # Case 4 as a corpus-wide pattern (112 unilateral fires across 49
        # tasks); this bundle is one concrete instance of that pattern.
        "case_no": 4,
        "task": "clojure-write",
        "title": "Unilateral artifacts as a corpus-wide phenomenon (mixed; representative bundle)",
        "with_glob": "claude_clojure-write_use-agent-true_use-skill-true_*.jsonl",
        "without_glob": "claude_clojure-write_use-agent-true_use-skill-false_*.jsonl",
        "skill_anchors": ["## REPL-Driven Development Workflow", "## Tool Preference"],
        "delta_p": "+0.0",
        "tok": "0.59",
        "summary": (
            "The without-skill trace already passes the unit tests "
            "($r^{-}=0.82$) and the with-skill trace matches it on "
            "outcome ($\\Delta P = 0$ pp); both sides nonetheless diverge on "
            "$28$ structural events. The diff shows the corpus-wide "
            "\\textsc{Unilateral\\_Action} pattern at the "
            "\\emph{exploration} level: each side runs its own non-overlapping "
            "stack of \\texttt{Grep}/\\texttt{Glob}/\\texttt{Read} probes "
            "(green vs.\\ red blocks) before producing essentially equivalent "
            "writes (which the truncation elides into the \\textit{omitted} "
            "marker). The skill's \\emph{Tool Preference} section, shown "
            "above, biases the with-skill agent towards a different ordering "
            "and choice of search tools than the without-skill baseline; in "
            "the bash-defensive case (\\S\\ref{app:case3}) the same "
            "\\textsc{Unilateral\\_Action} pass surfaces actual extra "
            "\\textsc{Write} targets (\\texttt{test\\_scripts.bats}-like "
            "files), so on the corpus the pattern shows up in both forms."
        ),
    },
    {
        # Case 5 representative: the most extreme ceiling-task token tax in
        # the corpus (creating-financial-models, 6.80x overhead at delta_p=0).
        # The diff makes the "skill inertia" mechanism visually obvious:
        # both sides produce equivalent terminal artifacts but the with-skill
        # trace runs a much longer process tail.
        "case_no": 5,
        "task": "creating-financial-models",
        "title": "Skill inertia at the ceiling (cost-only; representative bundle)",
        "with_glob": "claude_creating-financial-models_use-agent-true_use-skill-true_*.jsonl",
        "without_glob": "claude_creating-financial-models_use-agent-true_use-skill-false_*.jsonl",
        "skill_anchors": ["## Core Capabilities", "## Best Practices Applied", "## Quality Checks"],
        "delta_p": "+0.0",
        "tok": "6.80",
        "summary": (
            "Both traces reach the same passing repository state "
            "($r^{-}=r^{+}=0.90$, $\\Delta P = 0$ pp), but the with-skill "
            "trace pays $6.80\\times$ the baseline tokens. The diff makes "
            "this concrete: after the shared implementation block, the "
            "with-skill trace continues into a long sequence of "
            "\\textsc{Bash} validation and quality-check invocations "
            "(\\colorbox{green!22}{\\strut green tail}) that the "
            "without-skill agent skips because it has already concluded the "
            "task. This is the ``skills prescribe \\emph{process}; agents "
            "optimize \\emph{outcome}'' tension materialised on a single "
            "bundle and is the corpus-wide pattern Case 5 quantifies "
            "across all 12 ceiling tasks with $\\geq 1.5\\times$ overhead at "
            "$\\Delta P \\leq 0$ pp."
        ),
    },
]


def _glob_one(glob: str) -> Path:
    matches = sorted(TRACES_DIR.glob(glob))
    if not matches:
        raise FileNotFoundError(f"No trace matched {glob} under {TRACES_DIR}")
    return matches[-1]  # latest by filename timestamp


def render_case(case: dict) -> str:
    with_path = _glob_one(case["with_glob"])
    without_path = _glob_one(case["without_glob"])
    skill_path = SKILLS_DIR / case["task"] / "SKILL.md"

    with_actions = extract_actions(with_path)
    without_actions = extract_actions(without_path)
    rows = diff_actions(without_actions, with_actions)
    rows = truncate_rows(rows)

    excerpt = excerpt_skill(skill_path, case["skill_anchors"])

    out: List[str] = []
    out.append("")
    out.append(r"\subsection{Case " + str(case["case_no"]) +
               r": \texttt{" + latex_escape(case["task"]) + r"} --- " +
               case["title"] + r"}")
    out.append(r"\label{app:case" + str(case["case_no"]) + r"}")
    out.append("")
    out.append(
        "% Bundle trace files (author ref): with-skill: "
        + with_path.name
        + "; without-skill: "
        + without_path.name
    )
    out.append(
        r"\noindent\textbf{Bundle.} "
        r"Paired with-skill and without-skill traces; "
        r"$\Delta P = "
        + case["delta_p"]
        + r"$~pp, token-overhead $"
        + case["tok"]
        + r"\times$."
    )
    out.append("")
    out.append(r"\noindent\textbf{Skill template.} The section of the "
               r"skill document that the diff below most directly references:")
    out.append("")
    out.append(render_skill_block(case["task"], excerpt))
    out.append("")
    out.append(r"\noindent\textbf{Trace diff.} Each row is one tool "
               r"invocation, aligned by canonical signature. "
               r"\colorbox{green!22}{\strut Green} = action only present in "
               r"the with-skill trace; "
               r"\colorbox{red!18}{\strut red} = action only present in the "
               r"without-skill trace; "
               r"\colorbox{yellow!22}{\strut yellow} = paired but with a "
               r"different target. White rows are shared.")
    out.append("")
    out.append(render_diff_table(rows))
    out.append("")
    out.append(r"\noindent\textbf{Reading.} " + case["summary"])
    out.append("")
    return "\n".join(out)


HEADER = r"""% Auto-generated by scripts/cta_case_traces.py. Do not edit by hand.
% Regenerate with: python scripts/cta_case_traces.py
\section{Case-study trace excerpts}
\label{app:cases}

This appendix accompanies \S\ref{sec:cases} and reproduces, for each of the
five mechanism case studies, (i) the section of the skill template that the
with-skill agent most directly acts on, and (ii) a row-aligned diff of the
two traces' tool-invocation sequences. The diff is computed by collapsing
each tool call to a canonical signature (e.g.\ \texttt{Write:test\_scripts.bats},
\texttt{Bash:python}) and running \texttt{difflib.SequenceMatcher} on the
two resulting sequences. We cap each diff at """ + str(MAX_ROWS_PER_CASE) + r"""
rows, preferring to keep all coloured (non-shared) rows;
\textit{\ldots omitted} marks a contiguous block of shared steps that we
elided to fit on the page. Cases 1--3 are bundles cited directly in
\S\ref{sec:cases}; Cases 4 and 5 are framed in the main text as
corpus-wide patterns ($112$ unilateral fires across $49$ tasks; $12$ ceiling
tasks with $\geq 1.5\times$ token overhead at $\Delta P \leq 0$ pp), and we
reproduce a single representative bundle for each so the reader can see the
mechanism on a concrete pair. The chosen representatives
(\texttt{clojure-write} for Case 4, \texttt{creating-financial-models} for
Case 5) are not the only instances of those patterns in our corpus; they are
selected to be visually unambiguous.

"""


def main() -> None:
    body_parts = [HEADER]
    for case in CASES:
        body_parts.append(render_case(case))
    OUTPUT_TEX.write_text("\n".join(body_parts) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_TEX} ({OUTPUT_TEX.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
