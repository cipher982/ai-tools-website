"""Tests for web routes and middleware."""

import os

# Set BASE_PATH before importing web module (must happen before import)
os.environ["BASE_PATH"] = "/aitools"

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from ai_tools_website.v1.web import app  # noqa: E402
from ai_tools_website.v1.web import get_canonical_url  # noqa: E402


class TestCanonicalUrl:
    """Tests for the get_canonical_url helper function."""

    def test_canonical_url_root(self):
        """Root path returns base URL without trailing slash."""
        result = get_canonical_url()
        assert result == "https://drose.io/aitools"

    def test_canonical_url_root_explicit(self):
        """Explicit root path returns base URL."""
        result = get_canonical_url("/")
        assert result == "https://drose.io/aitools"

    def test_canonical_url_with_path(self):
        """Path is appended correctly."""
        result = get_canonical_url("tools/chatgpt")
        assert result == "https://drose.io/aitools/tools/chatgpt"

    def test_canonical_url_strips_leading_slash(self):
        """Leading slash in path is handled."""
        result = get_canonical_url("/tools/chatgpt")
        assert result == "https://drose.io/aitools/tools/chatgpt"


class TestTrailingSlashMiddleware:
    """Tests for the trailing slash redirect middleware."""

    @pytest.fixture
    def client(self):
        """Create a test client for the app."""
        return TestClient(app, raise_server_exceptions=False)

    def test_trailing_slash_redirects(self, client):
        """Trailing slash URLs should redirect to non-trailing-slash."""
        # Use follow_redirects=False to capture the redirect
        response = client.get("/tools/chatgpt/", follow_redirects=False)
        assert response.status_code == 308
        # Should include BASE_PATH in redirect location
        assert "/aitools/tools/chatgpt" in response.headers["location"]

    def test_non_trailing_slash_passes_through(self, client):
        """Non-trailing-slash URLs should pass through to router."""
        # This will 404 since we don't have real data, but it shouldn't redirect
        response = client.get("/tools/chatgpt", follow_redirects=False)
        # Should be 404 (tool not found) or 200, not 308
        assert response.status_code != 308

    def test_root_path_no_redirect(self, client):
        """Root path should not trigger trailing-slash redirect."""
        response = client.get("/", follow_redirects=False)
        # Should be 200, not redirect
        assert response.status_code == 200


class TestRoutes:
    """Tests for web routes."""

    @pytest.fixture
    def client(self):
        """Create a test client for the app."""
        return TestClient(app, raise_server_exceptions=False)

    def test_homepage_returns_200(self, client):
        """Homepage should return 200."""
        response = client.get("/")
        assert response.status_code == 200
        assert "AI Tools Collection" in response.text

    def test_homepage_has_canonical_link(self, client):
        """Homepage should have canonical link tag."""
        response = client.get("/")
        assert 'rel="canonical"' in response.text
        assert "https://drose.io/aitools" in response.text

    def test_comparisons_hub_returns_200(self, client):
        """Comparisons hub page should return 200."""
        response = client.get("/comparisons")
        assert response.status_code == 200
        assert "AI Tool Comparisons" in response.text

    def test_comparisons_hub_has_canonical_link(self, client):
        """Comparisons hub should have canonical link tag."""
        response = client.get("/comparisons")
        assert 'rel="canonical"' in response.text
        assert "https://drose.io/aitools/comparisons" in response.text

    def test_health_endpoint(self, client):
        """Health endpoint should return ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
