#!/usr/bin/env python3
"""Synthetic fixture generator for context-capacity eval.

Generates a repo where a cross-file protocol rename requires awareness of all
modules simultaneously. Tests whether an agent's context management (compaction,
selective reads) preserves task state across a repo that exceeds its window.

Target modes:
  orchestrator (default): ~144k tokens. Exceeds 128k orchestrator window.
    Tests whether delegation prevents parent context overflow.
  qodercli: 200k+ tokens. Exceeds qodercli's 131k default window.
    Tests whether the executor tracks rename progress across compaction
    boundaries — state-tracking-under-compaction, not raw capacity.

Usage:
    python scripts/gen_context_fixture.py --output-dir /tmp/fixture_repo
    python scripts/gen_context_fixture.py --target-agent qodercli --output-dir /tmp/fixture_200k
    python scripts/gen_context_fixture.py --files 60 --tokens-per-file 4000 --coupling-density 0.5
    python scripts/gen_context_fixture.py --seed 42 --task rename
"""

import argparse
import hashlib
import os
import random
import string
import textwrap
from pathlib import Path


def make_identifier(rng: random.Random, prefix: str = "") -> str:
    """Generate a non-guessable but valid Python identifier."""
    consonants = "bcdfghjklmnpqrstvwxyz"
    vowels = "aeiou"
    parts = []
    for _ in range(3):
        parts.append(rng.choice(consonants).upper())
        parts.append(rng.choice(vowels))
        parts.append(str(rng.randint(0, 9)))
    name = "".join(parts)
    return f"{prefix}{name}" if prefix else name


class CouplingGraph:
    """Random connected DAG ensuring transitive closure = full graph."""

    def __init__(self, n_files: int, density: float, rng: random.Random):
        self.n = n_files
        self.density = density
        self.rng = rng
        self.edges: dict[int, set[int]] = {i: set() for i in range(n_files)}
        self._build()

    def _build(self):
        # Strict DAG: edges only from higher index to lower index (src > dst).
        # This guarantees no circular imports at runtime.
        # Spanning chain n-1 → n-2 → ... → 0 guarantees full connectivity.
        for i in range(self.n - 1, 0, -1):
            self.edges[i].add(i - 1)

        # Add random downward edges up to density target
        max_edges = int(self.n * (self.n - 1) / 2 * self.density)
        current = sum(len(v) for v in self.edges.values())
        attempts = 0
        while current < max_edges and attempts < max_edges * 10:
            src = self.rng.randint(1, self.n - 1)
            dst = self.rng.randint(0, src - 1)
            if dst not in self.edges[src]:
                self.edges[src].add(dst)
                current += 1
            attempts += 1

    def imports_for(self, file_idx: int) -> list[int]:
        return sorted(self.edges[file_idx])


TARGET_PRESETS = {
    "orchestrator": {"n_files": 40, "tokens_per_file": 3500, "density": 0.4},
    "qodercli": {"n_files": 60, "tokens_per_file": 4000, "density": 0.5},
}


class FixtureGenerator:
    def __init__(
        self,
        n_files: int | None = None,
        tokens_per_file: int | None = None,
        density: float | None = None,
        seed: int | None = None,
        task: str = "rename",
        target_agent: str = "orchestrator",
    ):
        preset = TARGET_PRESETS[target_agent]
        self.n_files = n_files if n_files is not None else preset["n_files"]
        self.tokens_per_file = tokens_per_file if tokens_per_file is not None else preset["tokens_per_file"]
        self.density = density if density is not None else preset["density"]
        self.target_agent = target_agent
        self.seed = seed if seed is not None else 20260722
        self.task = task
        self.rng = random.Random(self.seed)

        self.graph = CouplingGraph(self.n_files, self.density, self.rng)
        self.protocol_name = "RegistryEntry"
        self.new_protocol_name = "CatalogNode"

        # Generate non-guessable type names for each module
        self.type_names: list[str] = []
        seen = set()
        for _ in range(self.n_files):
            while True:
                name = make_identifier(self.rng)
                if name not in seen:
                    seen.add(name)
                    self.type_names.append(name)
                    break

        # Assign modules to layers
        self.n_models = self.n_files // 2
        self.n_services = self.n_files // 4
        self.n_adapters = self.n_files - self.n_models - self.n_services

        self.module_paths: list[str] = []
        for i in range(self.n_files):
            if i < self.n_models:
                self.module_paths.append(f"src/models/mod_{i:03d}.py")
            elif i < self.n_models + self.n_services:
                self.module_paths.append(f"src/services/svc_{i:03d}.py")
            else:
                self.module_paths.append(f"src/adapters/adp_{i:03d}.py")

    def class_name_for(self, idx: int) -> str:
        """Return the actual exported class name for a module."""
        base = self.type_names[idx]
        if idx < self.n_models:
            return base
        elif idx < self.n_models + self.n_services:
            return f"{base}Service"
        else:
            return f"{base}Adapter"

    def _padding_lines(self, target_chars: int, current_chars: int) -> str:
        """Generate realistic filler code to hit token budget."""
        needed = target_chars - current_chars
        if needed <= 0:
            return ""
        lines = []
        accumulated = 0
        j = 0
        while accumulated < needed:
            method_name = make_identifier(self.rng, prefix="compute_")
            block = [
                f"    def {method_name}(self, payload: dict) -> dict:",
                f'        """Process stage {j} for {self.type_names[self.rng.randint(0, self.n_files - 1)]}."""',
                f"        result = {{}}",
                f"        for key, value in payload.items():",
                f"            transformed = self._transform(key, value, stage={j})",
                f"            result[f'{{key}}_s{j}'] = transformed",
                f"        return result",
                "",
                f"    def _transform_{j}(self, key: str, value, stage: int):",
                f"        checksum = hashlib.md5(f'{{key}}{{stage}}'.encode()).hexdigest()[:8]",
                f"        return {{'value': value, 'checksum': checksum, 'stage': stage}}",
                "",
            ]
            block_text = "\n".join(block)
            lines.append(block_text)
            accumulated += len(block_text)
            j += 1
        return "\n".join(lines)

    def _generate_module(self, idx: int) -> str:
        """Generate a single module source file."""
        type_name = self.type_names[idx]
        imports = self.graph.imports_for(idx)

        lines = [
            f'"""Module {idx}: {type_name} implementation."""',
            "",
            "from __future__ import annotations",
            "",
            "import hashlib",
            "from dataclasses import dataclass, field",
            "from typing import Any, Protocol, runtime_checkable",
            "",
        ]

        # Import types from coupled modules
        for dep_idx in imports[:6]:
            dep_path = self.module_paths[dep_idx].replace("/", ".").removesuffix(".py")
            dep_class = self.class_name_for(dep_idx)
            lines.append(f"from {dep_path} import {dep_class}")

        # Import the shared protocol from base
        lines.append("from src.models.base import RegistryEntry")
        lines.append("")
        lines.append("")

        # Protocol implementation or type annotation usage
        uses_isinstance = self.rng.random() < 0.3

        if idx < self.n_models:
            # Models: define dataclass implementing RegistryEntry
            lines.append("@dataclass")
            lines.append(f"class {type_name}(RegistryEntry):")
            lines.append(f'    """Data record for {type_name}."""')
            lines.append("")
            lines.append(f"    record_id: str = field(default_factory=lambda: hashlib.md5(b'{type_name}').hexdigest()[:12])")
            lines.append("    payload: dict[str, Any] = field(default_factory=dict)")
            for dep_idx in imports[:3]:
                dep_class = self.class_name_for(dep_idx)
                lines.append(f"    linked_{dep_class.lower()}: {dep_class} | None = None")
            lines.append("")
            lines.append("    def registry_key(self) -> str:")
            lines.append(f"        return f'{type_name}:{{self.record_id}}'")
            lines.append("")
            lines.append("    def validate(self) -> bool:")
            lines.append("        return bool(self.record_id and self.payload is not None)")
            lines.append("")
        elif idx < self.n_models + self.n_services:
            # Services: business logic using types
            lines.append(f"class {type_name}Service(RegistryEntry):")
            lines.append(f'    """Service layer for {type_name} operations."""')
            lines.append("")
            lines.append("    def __init__(self):")
            lines.append("        self._cache: dict[str, Any] = {}")
            for dep_idx in imports[:4]:
                dep_class = self.class_name_for(dep_idx)
                lines.append(f"        self._{dep_class.lower()}_ref: {dep_class} | None = None")
            lines.append("")
            lines.append("    def registry_key(self) -> str:")
            lines.append(f"        return 'svc:{type_name}'")
            lines.append("")
            if uses_isinstance:
                lines.append(f"    def process(self, item: Any) -> dict:")
                lines.append(f"        if isinstance(item, RegistryEntry):")
                lines.append(f"            return {{'key': item.registry_key(), 'valid': item.validate()}}")
                lines.append(f"        return {{'key': 'unknown', 'valid': False}}")
            else:
                lines.append(f"    def execute(self, entries: list[RegistryEntry]) -> list[str]:")
                lines.append(f"        return [e.registry_key() for e in entries if e.validate()]")
            lines.append("")
        else:
            # Adapters: I/O layer
            lines.append(f"class {type_name}Adapter(RegistryEntry):")
            lines.append(f'    """Adapter for {type_name} I/O."""')
            lines.append("")
            lines.append("    def __init__(self, endpoint: str = 'localhost'):")
            lines.append("        self.endpoint = endpoint")
            lines.append("        self._connected = False")
            lines.append("")
            lines.append("    def registry_key(self) -> str:")
            lines.append(f"        return 'adapter:{type_name}:{{self.endpoint}}'")
            lines.append("")
            if uses_isinstance:
                lines.append("    def serialize(self, obj: Any) -> bytes:")
                lines.append("        if isinstance(obj, RegistryEntry):")
                lines.append("            return obj.registry_key().encode()")
                lines.append("        return b'null'")
            else:
                lines.append("    def connect(self) -> bool:")
                lines.append("        self._connected = True")
                lines.append("        return self._connected")
            lines.append("")

        # Padding to hit token budget (~4 chars per token)
        current = "\n".join(lines)
        target_chars = self.tokens_per_file * 4
        padding = self._padding_lines(target_chars, len(current))
        if padding:
            lines.append(padding)

        return "\n".join(lines)

    def _generate_base(self) -> str:
        """Generate src/models/base.py with the shared protocol."""
        return textwrap.dedent(f'''\
            """Base protocol for all registry entries."""

            from __future__ import annotations

            from typing import Protocol, runtime_checkable


            @runtime_checkable
            class {self.protocol_name}(Protocol):
                """Protocol that all registered modules must implement."""

                def registry_key(self) -> str:
                    """Return unique key for registry dispatch."""
                    ...

                def validate(self) -> bool:
                    """Check internal consistency."""
                    ...
        ''')

    def _generate_registry(self) -> str:
        """Generate src/registry.py that imports ALL modules."""
        lines = [
            '"""Central registry — imports all modules for dispatch."""',
            "",
            "from __future__ import annotations",
            "",
            "from src.models.base import RegistryEntry",
            "",
        ]
        for i, path in enumerate(self.module_paths):
            mod_import = path.replace("/", ".").removesuffix(".py")
            lines.append(f"from {mod_import} import {self.class_name_for(i)}")
        lines.append("")
        lines.append("")
        lines.append("CATALOG: dict[str, type[RegistryEntry]] = {")
        for i in range(self.n_files):
            cls = self.class_name_for(i)
            lines.append(f"    '{cls}': {cls},")
        lines.append("}")
        lines.append("")
        lines.append("")
        lines.append("def lookup(key: str) -> type[RegistryEntry] | None:")
        lines.append("    return CATALOG.get(key)")
        lines.append("")
        lines.append("")
        lines.append("def all_keys() -> list[str]:")
        lines.append("    return list(CATALOG.keys())")
        lines.append("")
        return "\n".join(lines)

    def _generate_test(self) -> str:
        """Generate tests/test_consistency.py — the oracle."""
        return textwrap.dedent(f'''\
            """Oracle: validates the protocol rename was completed correctly."""

            import importlib
            import subprocess
            import sys
            from pathlib import Path

            import pytest

            SRC_ROOT = Path(__file__).parent.parent / "src"
            NEW_NAME = "{self.new_protocol_name}"
            OLD_NAME = "{self.protocol_name}"


            def test_new_protocol_exists():
                """CatalogNode is defined in src/models/base.py."""
                base = importlib.import_module("src.models.base")
                assert hasattr(base, NEW_NAME), f"{{NEW_NAME}} not found in base module"


            def test_old_name_removed():
                """No source file references {self.protocol_name}."""
                violations = []
                for py_file in SRC_ROOT.rglob("*.py"):
                    content = py_file.read_text()
                    if OLD_NAME in content:
                        violations.append(str(py_file))
                assert not violations, f"Old name still in: {{violations}}"


            def test_all_subclasses_register():
                """Every class implementing the protocol appears in registry.CATALOG."""
                registry = importlib.import_module("src.registry")
                catalog = registry.CATALOG
                assert len(catalog) == {self.n_files}, (
                    f"Expected {self.n_files} entries, got {{len(catalog)}}"
                )


            def test_imports_resolve():
                """All modules import without error."""
                errors = []
                for i in range({self.n_files}):
                    try:
                        if i < {self.n_models}:
                            mod = f"src.models.mod_{{i:03d}}"
                        elif i < {self.n_models + self.n_services}:
                            mod = f"src.services.svc_{{i:03d}}"
                        else:
                            mod = f"src.adapters.adp_{{i:03d}}"
                        importlib.import_module(mod)
                    except Exception as e:
                        errors.append(f"{{mod}}: {{e}}")
                assert not errors, f"Import failures: {{errors}}"


            def test_isinstance_checks_updated():
                """isinstance calls use the new protocol name."""
                isinstance_files = []
                for py_file in SRC_ROOT.rglob("*.py"):
                    content = py_file.read_text()
                    if f"isinstance(" in content and OLD_NAME in content:
                        isinstance_files.append(str(py_file))
                assert not isinstance_files, (
                    f"isinstance still references old name in: {{isinstance_files}}"
                )


            def test_progress_report():
                """Diagnostic: report exact completion percentage.

                This test always passes but prints progress for post-hoc analysis.
                If the agent loses track of state after compaction, this shows
                exactly which files were missed.
                """
                total = 0
                remaining = []
                for py_file in sorted(SRC_ROOT.rglob("*.py")):
                    if py_file.name == "__init__.py":
                        continue
                    total += 1
                    content = py_file.read_text()
                    if OLD_NAME in content:
                        remaining.append(str(py_file.relative_to(SRC_ROOT.parent)))
                completed = total - len(remaining)
                pct = (completed / total * 100) if total else 0
                print(f"\\n  PROGRESS: {{completed}}/{{total}} files renamed ({{pct:.1f}}%)")
                if remaining:
                    print(f"  REMAINING: {{remaining[:10]}}")
                    if len(remaining) > 10:
                        print(f"  ... and {{len(remaining) - 10}} more")
        ''')

    def _generate_migration_spec(self) -> str:
        """Generate MIGRATION_SPEC.md — the task prompt."""
        return textwrap.dedent(f"""\
            # Migration Task: Protocol Rename

            ## Objective

            Rename the `{self.protocol_name}` protocol to `{self.new_protocol_name}` across the
            entire codebase.

            ## Requirements

            1. In `src/models/base.py`: rename the protocol class from
               `{self.protocol_name}` to `{self.new_protocol_name}`.

            2. In **every file** that imports or references `{self.protocol_name}`:
               - Update the import statement
               - Update all type annotations
               - Update all `isinstance()` checks
               - Update all class inheritance declarations

            3. In `src/registry.py`: update the `CATALOG` type annotation from
               `dict[str, type[{self.protocol_name}]]` to `dict[str, type[{self.new_protocol_name}]]`.

            4. The `registry_key()` and `validate()` method signatures remain unchanged.

            ## Verification

            Run:
            ```bash
            python -m pytest tests/test_consistency.py -v
            ```

            All 5 tests must pass. A partial rename (some files updated, others not)
            will fail `test_old_name_removed` and `test_isinstance_checks_updated`.

            ## Constraints

            - Do NOT change any logic, only names.
            - Do NOT add or remove files.
            - Every module must still import cleanly after the rename.
        """)

    def _generate_pyproject(self) -> str:
        return textwrap.dedent("""\
            [project]
            name = "context-fixture"
            version = "0.1.0"
            requires-python = ">=3.11"

            [tool.pytest.ini_options]
            testpaths = ["tests"]
        """)

    def generate(self, output_dir: str) -> dict:
        """Write the fixture repo to disk. Returns metadata."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Directory structure
        (out / "src" / "models").mkdir(parents=True, exist_ok=True)
        (out / "src" / "services").mkdir(parents=True, exist_ok=True)
        (out / "src" / "adapters").mkdir(parents=True, exist_ok=True)
        (out / "tests").mkdir(parents=True, exist_ok=True)

        # __init__.py files
        for pkg in ["src", "src/models", "src/services", "src/adapters"]:
            (out / pkg / "__init__.py").write_text("")

        # base.py
        (out / "src" / "models" / "base.py").write_text(self._generate_base())

        # Module files
        total_chars = 0
        for i in range(self.n_files):
            content = self._generate_module(i)
            total_chars += len(content)
            rel_path = self.module_paths[i]
            (out / rel_path).write_text(content)

        # registry.py
        registry_content = self._generate_registry()
        total_chars += len(registry_content)
        (out / "src" / "registry.py").write_text(registry_content)

        # Test oracle
        (out / "tests" / "test_consistency.py").write_text(self._generate_test())
        (out / "tests" / "__init__.py").write_text("")

        # Task spec
        (out / "MIGRATION_SPEC.md").write_text(self._generate_migration_spec())

        # pyproject.toml
        (out / "pyproject.toml").write_text(self._generate_pyproject())

        estimated_tokens = total_chars // 4
        metadata = {
            "target_agent": self.target_agent,
            "n_files": self.n_files,
            "tokens_per_file_target": self.tokens_per_file,
            "estimated_total_tokens": estimated_tokens,
            "coupling_density": self.density,
            "seed": self.seed,
            "task": self.task,
            "protocol_old": self.protocol_name,
            "protocol_new": self.new_protocol_name,
            "n_models": self.n_models,
            "n_services": self.n_services,
            "n_adapters": self.n_adapters,
        }

        import json
        (out / "fixture_metadata.json").write_text(json.dumps(metadata, indent=2))

        return metadata


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic fixture for context-capacity eval."
    )
    parser.add_argument(
        "--target-agent",
        choices=list(TARGET_PRESETS.keys()),
        default="orchestrator",
        help="Target agent preset (sets files/tokens/density defaults)",
    )
    parser.add_argument("--files", type=int, default=None, help="Number of modules (overrides preset)")
    parser.add_argument(
        "--tokens-per-file", type=int, default=None, help="Target tokens per file (overrides preset)"
    )
    parser.add_argument(
        "--coupling-density",
        type=float,
        default=None,
        help="Cross-file coupling density 0.0-1.0 (overrides preset)",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    parser.add_argument(
        "--task",
        choices=["rename"],
        default="rename",
        help="Task type (currently: rename)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/context_fixture",
        help="Output directory",
    )
    args = parser.parse_args()

    gen = FixtureGenerator(
        n_files=args.files,
        tokens_per_file=args.tokens_per_file,
        density=args.coupling_density,
        seed=args.seed,
        task=args.task,
        target_agent=args.target_agent,
    )
    metadata = gen.generate(args.output_dir)

    print(f"Fixture generated: {args.output_dir}")
    print(f"  Target: {metadata['target_agent']}")
    print(f"  Modules: {metadata['n_files']} ({metadata['n_models']}M/{metadata['n_services']}S/{metadata['n_adapters']}A)")
    print(f"  Estimated tokens: {metadata['estimated_total_tokens']:,}")
    print(f"  Coupling density: {metadata['coupling_density']}")
    print(f"  Task: {metadata['task']} ({metadata['protocol_old']} → {metadata['protocol_new']})")
    print(f"  Seed: {metadata['seed']}")


if __name__ == "__main__":
    main()
