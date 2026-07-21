"""Zero-State-Pollution Validator.

Pre-flight checks that verify a capture environment is clean before recording.
Run BEFORE each capture session to prevent state leakage between runs.

Usage:
    python -m cta.preflight data/m3_captures/P1-interactive-treatment-1/
    python -m cta.preflight data/m3_captures/P1-interactive-treatment-1/ --strict
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PreflightReport:
    run_dir: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "run_dir": self.run_dir,
            "passed": self.all_passed,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
        }


def check_state_db_absent(run_dir: Path) -> CheckResult:
    db = run_dir / "state.db"
    if not db.exists():
        return CheckResult("state_db_absent", True, "No prior state.db")
    try:
        conn = sqlite3.connect(str(db))
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        if count == 0:
            return CheckResult("state_db_absent", True, "state.db exists but is empty (0 messages)")
        return CheckResult("state_db_absent", False, f"state.db has {count} messages from a prior run")
    except Exception as e:
        return CheckResult("state_db_absent", False, f"state.db unreadable: {e}")


def check_wal_absent(run_dir: Path) -> CheckResult:
    wal = run_dir / "state.db-wal"
    if not wal.exists():
        return CheckResult("wal_absent", True, "No WAL file")
    size = wal.stat().st_size
    if size == 0:
        return CheckResult("wal_absent", True, "WAL file is zero-length (checkpoint was performed)")
    return CheckResult("wal_absent", False, f"WAL file is {size} bytes (unclean shutdown)")


def check_workspace_clean(run_dir: Path) -> CheckResult:
    workspace = run_dir / "workspace"
    if not workspace.exists():
        return CheckResult("workspace_clean", True, "No workspace directory (will be created fresh)")
    git_dir = workspace / ".git"
    if not git_dir.exists():
        return CheckResult("workspace_clean", False, "workspace exists but has no .git (corrupt state)")
    import subprocess
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace, capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return CheckResult("workspace_clean", False, f"git status failed: {result.stderr.strip()}")
    dirty = result.stdout.strip()
    if not dirty:
        return CheckResult("workspace_clean", True, "Workspace is clean (no uncommitted changes)")
    lines = dirty.splitlines()
    return CheckResult("workspace_clean", False, f"Workspace has {len(lines)} uncommitted change(s)")


def check_no_result_json(run_dir: Path) -> CheckResult:
    result_file = run_dir / "result.json"
    if not result_file.exists():
        return CheckResult("no_result_json", True, "No prior result.json")
    return CheckResult("no_result_json", False, "result.json exists from a prior run")


def check_no_skill_memory(run_dir: Path) -> CheckResult:
    memory_markers = [
        run_dir / "workspace" / ".hermes_memory",
        run_dir / "workspace" / ".claude",
        run_dir / "workspace" / "AGENT.md",
    ]
    found = [str(m.relative_to(run_dir)) for m in memory_markers if m.exists()]
    if not found:
        return CheckResult("no_skill_memory", True, "No skill memory artifacts")
    return CheckResult("no_skill_memory", False, f"Memory artifacts found: {', '.join(found)}")


def run_preflight(run_dir: Path, strict: bool = False) -> PreflightReport:
    report = PreflightReport(run_dir=str(run_dir))
    report.checks.append(check_state_db_absent(run_dir))
    report.checks.append(check_wal_absent(run_dir))
    report.checks.append(check_workspace_clean(run_dir))
    report.checks.append(check_no_result_json(run_dir))
    report.checks.append(check_no_skill_memory(run_dir))

    if strict:
        stdout_file = run_dir / "hermes_stdout.txt"
        if stdout_file.exists():
            report.checks.append(CheckResult("no_stdout", False, "hermes_stdout.txt exists from prior run"))
        else:
            report.checks.append(CheckResult("no_stdout", True, "No prior stdout capture"))

    return report


def main():
    parser = argparse.ArgumentParser(description="Zero-State-Pollution pre-flight validator")
    parser.add_argument("run_dir", type=str, help="Path to the capture run directory")
    parser.add_argument("--strict", action="store_true", help="Also check for stdout artifacts")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        run_dir.mkdir(parents=True, exist_ok=True)

    report = run_preflight(run_dir, strict=args.strict)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status = "PASS" if report.all_passed else "FAIL"
        print(f"[{status}] {run_dir}")
        for c in report.checks:
            icon = "ok" if c.passed else "FAIL"
            print(f"  [{icon}] {c.name}: {c.detail}")

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
