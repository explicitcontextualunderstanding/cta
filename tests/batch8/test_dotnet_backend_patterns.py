"""
Tests for the dotnet-backend-patterns skill.
Validates Catalog API concurrency and data access optimizations in eShop
with async patterns, caching, projection DTOs, and efficient pagination.
"""

import os
import re

REPO_DIR = "/workspace/eshop"
CATALOG_DIR = os.path.join(REPO_DIR, "src", "Catalog.API")


class TestDotnetBackendPatterns:
    """Tests for the eShop Catalog API optimization."""

    # ── file_path_check ──────────────────────────────────────────────

    def test_catalog_service_exists(self):
        """CatalogService.cs must exist."""
        path = os.path.join(CATALOG_DIR, "Services", "CatalogService.cs")
        assert os.path.isfile(path), f"Missing {path}"

    def test_catalog_api_exists(self):
        """CatalogApi.cs must exist."""
        path = os.path.join(CATALOG_DIR, "Apis", "CatalogApi.cs")
        assert os.path.isfile(path), f"Missing {path}"

    def test_catalog_context_exists(self):
        """CatalogContext.cs must exist."""
        path = os.path.join(CATALOG_DIR, "Infrastructure", "CatalogContext.cs")
        assert os.path.isfile(path), f"Missing {path}"

    # ── semantic_check ───────────────────────────────────────────────

    def _read(self, rel_path):
        path = os.path.join(CATALOG_DIR, rel_path)
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_async_await_usage(self):
        """CatalogService must use async/await for data access."""
        content = self._read("Services/CatalogService.cs")
        assert re.search(r"async\s+Task|await\b", content), (
            "async/await pattern not found in CatalogService"
        )

    def test_no_sync_db_calls(self):
        """CatalogService should not use synchronous .Result or .Wait()."""
        content = self._read("Services/CatalogService.cs")
        has_sync = re.search(r"\.Result\b|\.Wait\(\)|\.GetAwaiter\(\)\.GetResult\(\)", content)
        assert not has_sync, "Synchronous blocking call found (use await instead)"

    def test_projection_dto(self):
        """CatalogApi must use projection DTOs, not full entities."""
        content = self._read("Apis/CatalogApi.cs")
        assert re.search(r"Dto|DTO|ViewModel|Select\(|\.Select\b", content, re.IGNORECASE), (
            "Projection DTO or Select projection not found"
        )

    def test_caching_implementation(self):
        """Service must cache frequently accessed read-only data."""
        content = self._read("Services/CatalogService.cs")
        assert re.search(r"[Cc]ache|IMemoryCache|IDistributedCache|GetOrCreate", content), (
            "Caching implementation not found"
        )

    def test_pagination_optimization(self):
        """Queries must use efficient pagination (Skip/Take or keyset)."""
        all_content = self._read("Apis/CatalogApi.cs") + self._read("Services/CatalogService.cs")
        assert re.search(r"Skip|Take|pageSize|PageSize|OFFSET|FETCH", all_content), (
            "Pagination optimization not found"
        )

    def test_eager_loading_or_include(self):
        """Context queries should use Include or projection to avoid N+1."""
        content = self._read("Infrastructure/CatalogContext.cs") + self._read("Services/CatalogService.cs")
        assert re.search(r"Include\(|ThenInclude|AsNoTracking|Select\(", content), (
            "Eager loading or projection not found"
        )

    # ── functional_check ─────────────────────────────────────────────

    def test_cs_files_no_syntax_markers(self):
        """C# files should have proper class/namespace structure."""
        for rel in ["Services/CatalogService.cs", "Apis/CatalogApi.cs",
                     "Infrastructure/CatalogContext.cs"]:
            content = self._read(rel)
            if not content:
                continue
            assert re.search(r"namespace\s+|using\s+", content), (
                f"{rel} missing namespace or using declarations"
            )
            assert re.search(r"class\s+|static\s+class\s+|public\s+", content), (
                f"{rel} missing class definition"
            )

    def test_cancellation_token_support(self):
        """Async methods should accept CancellationToken."""
        content = self._read("Services/CatalogService.cs")
        assert re.search(r"CancellationToken", content), (
            "CancellationToken not found in async methods"
        )

    def test_as_no_tracking(self):
        """Read-only queries should use AsNoTracking."""
        content = self._read("Services/CatalogService.cs")
        assert re.search(r"AsNoTracking", content), (
            "AsNoTracking not used for read queries"
        )

    def test_tolistasync_usage(self):
        """Queries should use ToListAsync, not ToList."""
        content = self._read("Services/CatalogService.cs")
        assert re.search(r"ToListAsync|FirstOrDefaultAsync|CountAsync", content), (
            "Async query execution not found"
        )
