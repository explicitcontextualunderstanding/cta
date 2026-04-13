"""
Test skill: dotnet-backend-patterns
Verify that the Agent optimizes the eShop Catalog service with async
data access, caching, and projection DTOs.
"""

import os
import re
import pytest


class TestDotnetBackendPatterns:
    REPO_DIR = "/workspace/eshop"

    CATALOG_SERVICE = "src/Catalog.API/Services/CatalogService.cs"
    CATALOG_API = "src/Catalog.API/Apis/CatalogApi.cs"
    CATALOG_CONTEXT = "src/Catalog.API/Infrastructure/CatalogContext.cs"

    def _read_file(self, rel_path):
        filepath = os.path.join(self.REPO_DIR, rel_path)
        with open(filepath) as f:
            return f.read()

    # === File Path Checks ===

    def test_catalog_service_exists(self):
        filepath = os.path.join(self.REPO_DIR, self.CATALOG_SERVICE)
        assert os.path.exists(filepath), "CatalogService.cs not found"

    def test_catalog_api_exists(self):
        filepath = os.path.join(self.REPO_DIR, self.CATALOG_API)
        assert os.path.exists(filepath), "CatalogApi.cs not found"

    def test_catalog_context_exists(self):
        filepath = os.path.join(self.REPO_DIR, self.CATALOG_CONTEXT)
        assert os.path.exists(filepath), "CatalogContext.cs not found"

    # === Semantic Checks ===

    def test_service_uses_async_await(self):
        """Verify CatalogService uses async/await patterns"""
        content = self._read_file(self.CATALOG_SERVICE)
        assert "async" in content, "CatalogService missing async methods"
        assert "await" in content, "CatalogService missing await calls"
        assert "Task" in content, "CatalogService missing Task return types"

    def test_service_uses_caching(self):
        """Verify caching for frequently accessed data"""
        content = self._read_file(self.CATALOG_SERVICE)
        has_cache = bool(re.search(
            r'(IMemoryCache|IDistributedCache|cache|Cache|GetOrCreate)', content, re.I
        ))
        assert has_cache, "CatalogService missing caching implementation"

    def test_api_uses_projection_dtos(self):
        """Verify API endpoints use projection DTOs, not full entities"""
        content = self._read_file(self.CATALOG_API)
        has_dto = bool(re.search(r'(Dto|DTO|ViewModel|Response|Model)', content))
        assert has_dto, "CatalogApi missing projection DTOs"

    def test_api_uses_async_endpoints(self):
        """Verify API endpoints use async patterns"""
        content = self._read_file(self.CATALOG_API)
        assert "async" in content, "CatalogApi missing async endpoints"

    def test_context_uses_eager_loading_or_projections(self):
        """Verify EF Core queries use Include or Select projections"""
        content = self._read_file(self.CATALOG_CONTEXT)
        has_opt = bool(re.search(r'(Include|Select|AsNoTracking|projection)', content, re.I))
        assert has_opt, "CatalogContext missing query optimizations"

    def test_service_async_data_access(self):
        """Verify database calls use ToListAsync/FirstOrDefaultAsync"""
        content = self._read_file(self.CATALOG_SERVICE)
        has_async_ef = bool(re.search(
            r'(ToListAsync|FirstOrDefaultAsync|SingleOrDefaultAsync|CountAsync|AnyAsync)',
            content
        ))
        assert has_async_ef, "CatalogService missing async EF Core calls"

    def test_pagination_is_efficient(self):
        """Verify pagination uses Skip/Take or keyset patterns"""
        content = self._read_file(self.CATALOG_SERVICE) + self._read_file(self.CATALOG_API)
        has_paging = bool(re.search(r'(Skip|Take|pageSize|pageIndex|Offset|Limit)', content))
        assert has_paging, "Missing efficient pagination"

    def test_no_blocking_calls(self):
        """Verify no .Result or .Wait() blocking calls"""
        content = self._read_file(self.CATALOG_SERVICE)
        has_blocking = bool(re.search(r'\.(Result|Wait\(\)|GetAwaiter\(\)\.GetResult\(\))', content))
        assert not has_blocking, \
            "CatalogService has blocking calls (.Result or .Wait)"

    # === Functional Checks ===

    def test_cs_files_have_valid_structure(self):
        """Verify C# files have namespace and class declarations"""
        for path in [self.CATALOG_SERVICE, self.CATALOG_API, self.CATALOG_CONTEXT]:
            content = self._read_file(path)
            assert "namespace" in content, f"{path} missing namespace"
            assert "class" in content or "static" in content, \
                f"{path} missing class declaration"

    def test_service_has_dependency_injection(self):
        """Verify service uses constructor injection"""
        content = self._read_file(self.CATALOG_SERVICE)
        has_di = bool(re.search(
            r'(CatalogService\s*\(|ILogger|IOptions|DbContext)', content
        ))
        assert has_di, "CatalogService missing dependency injection"
