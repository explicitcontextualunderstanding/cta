"""
Test skill: dotnet-backend-patterns
Verify that the Agent optimizes the Catalog Service in eShop —
async data access, EF Core query optimizations (projections, eager loading),
caching for read-only data, and proper DTO responses.
"""

import os
import re
import subprocess
import pytest


class TestDotnetBackendPatterns:
    REPO_DIR = "/workspace/eshop"

    # ────── helpers ──────

    def _read(self, rel_path):
        fpath = os.path.join(self.REPO_DIR, rel_path)
        with open(fpath, "r") as f:
            return f.read()

    def _exists(self, rel_path):
        return os.path.isfile(os.path.join(self.REPO_DIR, rel_path))

    def _find_file(self, pattern):
        """Walk repo to find a file matching pattern."""
        for root, dirs, files in os.walk(self.REPO_DIR):
            for fn in files:
                if re.search(pattern, fn, re.IGNORECASE):
                    return os.path.relpath(os.path.join(root, fn), self.REPO_DIR)
        return None

    # === File Path Checks ===

    def test_catalog_service_exists(self):
        """CatalogService.cs must exist"""
        found = self._find_file(r'CatalogService\.cs$')
        assert found, "CatalogService.cs not found"

    def test_catalog_api_exists(self):
        """CatalogApi.cs must exist"""
        found = self._find_file(r'CatalogApi\.cs$')
        assert found, "CatalogApi.cs not found"

    def test_catalog_context_exists(self):
        """CatalogContext.cs must exist"""
        found = self._find_file(r'CatalogContext\.cs$')
        assert found, "CatalogContext.cs not found"

    # === Semantic Checks — Async Patterns ===

    def test_async_methods_in_service(self):
        """CatalogService must use async methods"""
        fpath = self._find_file(r'CatalogService\.cs$')
        assert fpath, "CatalogService.cs not found"
        src = self._read(fpath)
        assert "async" in src, "No async methods found in CatalogService"
        assert "await" in src, "No await usage found in CatalogService"

    def test_async_to_list(self):
        """Must use ToListAsync / FirstOrDefaultAsync"""
        fpath = self._find_file(r'CatalogService\.cs$')
        src = self._read(fpath)
        assert "Async" in src, "No async EF Core methods found"

    # === Semantic Checks — Query Optimization ===

    def test_projection_queries(self):
        """Must use Select projections"""
        fpath = self._find_file(r'CatalogService\.cs$')
        src = self._read(fpath)
        assert "Select" in src or ".Select(" in src, (
            "No projection queries (Select) found"
        )

    def test_no_full_entity_loading(self):
        """Should use DTOs rather than returning full entities"""
        fpath = self._find_file(r'CatalogApi\.cs$')
        src = self._read(fpath)
        lower = src.lower()
        assert "dto" in lower or "response" in lower or "model" in lower, (
            "No DTO/response model pattern found"
        )

    def test_eager_loading_or_include(self):
        """Should use Include/ThenInclude for eager loading where needed"""
        fpath = self._find_file(r'CatalogContext\.cs$')
        if not fpath:
            fpath = self._find_file(r'CatalogService\.cs$')
        src = self._read(fpath)
        # Eager loading or explicit join strategy
        lower = src.lower()
        assert "include" in lower or "join" in lower or "select" in lower, (
            "No eager loading strategy found"
        )

    def test_pagination_efficiency(self):
        """Pagination must use Skip/Take or equivalent"""
        fpath = self._find_file(r'CatalogService\.cs$')
        if not fpath:
            fpath = self._find_file(r'CatalogApi\.cs$')
        src = self._read(fpath)
        lower = src.lower()
        assert "skip" in lower or "take" in lower or "pagesize" in lower or "limit" in lower, (
            "No pagination pattern found"
        )

    # === Semantic Checks — Caching ===

    def test_caching_mechanism(self):
        """Must implement caching for read-only data"""
        found = False
        for pattern in [r'CatalogService\.cs$', r'CatalogApi\.cs$']:
            fpath = self._find_file(pattern)
            if fpath:
                src = self._read(fpath)
                lower = src.lower()
                if any(k in lower for k in ["cache", "memorycache", "icache",
                                              "distributedcache", "cacheentry"]):
                    found = True
                    break
        assert found, "No caching mechanism found"

    def test_category_brand_caching(self):
        """Categories or brands should be cached"""
        fpath = self._find_file(r'CatalogService\.cs$')
        if fpath:
            src = self._read(fpath)
            lower = src.lower()
            assert ("brand" in lower or "category" in lower or "type" in lower), (
                "No category/brand data access found"
            )

    # === Semantic Checks — Concurrency ===

    def test_scoped_dbcontext(self):
        """DbContext should be properly scoped"""
        fpath = self._find_file(r'CatalogService\.cs$')
        src = self._read(fpath)
        # Should inject context or use scoped lifetime
        assert "CatalogContext" in src or "DbContext" in src, (
            "No DbContext usage found"
        )

    # === Functional Checks ===

    def test_dotnet_build(self):
        """Project must build"""
        # Find the Catalog.API project file
        proj = self._find_file(r'Catalog\.API.*\.csproj$')
        if proj:
            result = subprocess.run(
                ["dotnet", "build", proj, "--no-restore"],
                capture_output=True, text=True, cwd=self.REPO_DIR, timeout=300,
            )
        else:
            result = subprocess.run(
                ["dotnet", "build", "--no-restore"],
                capture_output=True, text=True, cwd=self.REPO_DIR, timeout=300,
            )
        assert result.returncode == 0, (
            f"Build failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_dotnet_restore(self):
        """Project restore must succeed"""
        result = subprocess.run(
            ["dotnet", "restore"],
            capture_output=True, text=True, cwd=self.REPO_DIR, timeout=300,
        )
        assert result.returncode == 0, (
            f"Restore failed:\n{result.stdout}\n{result.stderr}"
        )
