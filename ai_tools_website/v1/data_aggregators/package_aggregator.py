"""Fetch package manager statistics for PyPI and npm packages.

Both APIs are public and have no authentication requirements.
PyPI JSON API is unlimited. npm registry is also generous with limits.
"""

import logging
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PYPI_API_BASE = "https://pypi.org/pypi"
PYPISTATS_API_BASE = "https://pypistats.org/api/packages"
NPM_REGISTRY_BASE = "https://registry.npmjs.org"
NPM_DOWNLOADS_BASE = "https://api.npmjs.org/downloads"
TIMEOUT = 10.0


def extract_pypi_package(url: str) -> Optional[str]:
    """Extract PyPI package name from a URL.

    Args:
        url: URL that might reference a PyPI package

    Returns:
        Package name or None

    Examples:
        >>> extract_pypi_package("https://pypi.org/project/langchain/")
        "langchain"
        >>> extract_pypi_package("pip install transformers")
        "transformers"
    """
    if not url:
        return None

    # Match PyPI project URLs
    pypi_match = re.search(r"pypi\.org/project/([^/\?#]+)", url)
    if pypi_match:
        return pypi_match.group(1).rstrip("/").lower()

    # Match pip install commands in descriptions
    pip_match = re.search(r"pip\s+install\s+([a-zA-Z0-9_-]+)", url)
    if pip_match:
        return pip_match.group(1).lower()

    return None


def extract_npm_package(url: str) -> Optional[str]:
    """Extract npm package name from a URL.

    Args:
        url: URL that might reference an npm package

    Returns:
        Package name or None

    Examples:
        >>> extract_npm_package("https://www.npmjs.com/package/langchain")
        "langchain"
        >>> extract_npm_package("npm install @huggingface/inference")
        "@huggingface/inference"
    """
    if not url:
        return None

    # Match npm package URLs (including scoped packages)
    npm_match = re.search(r"npmjs\.com/package/(@?[^/\?#]+(?:/[^/\?#]+)?)", url)
    if npm_match:
        return npm_match.group(1).rstrip("/")

    # Match npm install commands
    npm_install_match = re.search(r"npm\s+install\s+(@?[a-zA-Z0-9_/-]+)", url)
    if npm_install_match:
        return npm_install_match.group(1)

    return None


async def fetch_pypi_stats(package_name: str) -> Optional[dict[str, Any]]:
    """Fetch stats for a PyPI package.

    Args:
        package_name: Package name (e.g., "langchain", "transformers")

    Returns:
        Dictionary with package stats, or None if fetch failed
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Fetch package metadata from PyPI
        pypi_url = f"{PYPI_API_BASE}/{package_name}/json"

        try:
            response = await client.get(pypi_url)

            if response.status_code == 404:
                logger.warning(f"PyPI package not found: {package_name}")
                return None

            if response.status_code != 200:
                logger.warning(f"PyPI API error {response.status_code} for {package_name}")
                return None

            data = response.json()

        except httpx.RequestError as exc:
            logger.error(f"PyPI request failed for {package_name}: {exc}")
            return None

        info = data.get("info", {})
        releases = data.get("releases", {})

        # Build stats object
        stats: dict[str, Any] = {
            "name": info.get("name") or package_name,
            "type": "pypi",
            "version": info.get("version"),
            "summary": info.get("summary"),
            "description": info.get("description", "")[:500] if info.get("description") else None,
            "author": info.get("author"),
            "author_email": info.get("author_email"),
            "license": info.get("license"),
            "home_page": info.get("home_page"),
            "project_url": info.get("project_url"),
            "package_url": info.get("package_url"),
            "requires_python": info.get("requires_python"),
            "keywords": info.get("keywords"),
            "classifiers": info.get("classifiers", []),
            "release_count": len(releases),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Project URLs (GitHub, docs, etc.)
        project_urls = info.get("project_urls") or {}
        if project_urls:
            stats["project_urls"] = project_urls
            # Try to find GitHub URL
            for key, url in project_urls.items():
                if "github.com" in str(url).lower():
                    stats["github_url"] = url
                    break

        # Get latest release date
        if releases:
            latest_version = info.get("version")
            if latest_version and latest_version in releases:
                release_files = releases[latest_version]
                if release_files:
                    # Get upload time from first file
                    upload_time = release_files[0].get("upload_time_iso_8601")
                    if upload_time:
                        stats["latest_release_date"] = upload_time

        # Dependencies
        requires_dist = info.get("requires_dist")
        if requires_dist:
            # Extract just package names from requirement strings
            deps = []
            for req in requires_dist[:20]:  # Limit to first 20
                # Parse "package-name (>=1.0)" format
                dep_match = re.match(r"^([a-zA-Z0-9_-]+)", req)
                if dep_match:
                    deps.append(dep_match.group(1))
            stats["dependencies"] = deps
            stats["dependency_count"] = len(requires_dist)

        # Try to fetch download stats from pypistats
        try:
            pypistats_url = f"{PYPISTATS_API_BASE}/{package_name}/recent"
            stats_response = await client.get(pypistats_url)
            if stats_response.status_code == 200:
                stats_data = stats_response.json()
                downloads = stats_data.get("data", {})
                stats["downloads"] = {
                    "last_day": downloads.get("last_day"),
                    "last_week": downloads.get("last_week"),
                    "last_month": downloads.get("last_month"),
                }
        except Exception as exc:
            logger.debug(f"Failed to fetch pypistats for {package_name}: {exc}")

        return stats


async def fetch_npm_stats(package_name: str) -> Optional[dict[str, Any]]:
    """Fetch stats for an npm package.

    Args:
        package_name: Package name (e.g., "langchain", "@huggingface/inference")

    Returns:
        Dictionary with package stats, or None if fetch failed
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Fetch package metadata from npm registry
        # Scoped packages need URL encoding
        encoded_name = package_name.replace("/", "%2F")
        npm_url = f"{NPM_REGISTRY_BASE}/{encoded_name}"

        try:
            response = await client.get(npm_url)

            if response.status_code == 404:
                logger.warning(f"npm package not found: {package_name}")
                return None

            if response.status_code != 200:
                logger.warning(f"npm API error {response.status_code} for {package_name}")
                return None

            data = response.json()

        except httpx.RequestError as exc:
            logger.error(f"npm request failed for {package_name}: {exc}")
            return None

        # Get latest version info
        dist_tags = data.get("dist-tags", {})
        latest_version = dist_tags.get("latest")
        versions = data.get("versions", {})
        latest_data = versions.get(latest_version, {}) if latest_version else {}

        # Build stats object
        stats: dict[str, Any] = {
            "name": data.get("name") or package_name,
            "type": "npm",
            "version": latest_version,
            "description": data.get("description"),
            "license": data.get("license") or latest_data.get("license"),
            "homepage": data.get("homepage") or latest_data.get("homepage"),
            "repository": None,
            "keywords": data.get("keywords", []),
            "version_count": len(versions),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Author info
        author = data.get("author")
        if isinstance(author, dict):
            stats["author"] = author.get("name")
        elif isinstance(author, str):
            stats["author"] = author

        # Repository info
        repo = data.get("repository") or latest_data.get("repository")
        if isinstance(repo, dict):
            stats["repository"] = repo.get("url")
        elif isinstance(repo, str):
            stats["repository"] = repo

        # Time info (created, modified)
        time_info = data.get("time", {})
        if time_info:
            stats["created"] = time_info.get("created")
            stats["modified"] = time_info.get("modified")
            if latest_version:
                stats["latest_release_date"] = time_info.get(latest_version)

        # Dependencies
        deps = latest_data.get("dependencies", {})
        if deps:
            stats["dependencies"] = list(deps.keys())[:20]
            stats["dependency_count"] = len(deps)

        # Fetch download stats
        try:
            downloads_url = f"{NPM_DOWNLOADS_BASE}/point/last-week/{encoded_name}"
            downloads_response = await client.get(downloads_url)
            if downloads_response.status_code == 200:
                downloads_data = downloads_response.json()
                stats["downloads"] = {
                    "last_week": downloads_data.get("downloads"),
                }

            # Also get last month
            downloads_month_url = f"{NPM_DOWNLOADS_BASE}/point/last-month/{encoded_name}"
            downloads_month_response = await client.get(downloads_month_url)
            if downloads_month_response.status_code == 200:
                downloads_month_data = downloads_month_response.json()
                if "downloads" not in stats:
                    stats["downloads"] = {}
                stats["downloads"]["last_month"] = downloads_month_data.get("downloads")

        except Exception as exc:
            logger.debug(f"Failed to fetch npm downloads for {package_name}: {exc}")

        return stats
