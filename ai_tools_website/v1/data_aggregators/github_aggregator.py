"""Fetch GitHub repository metrics for open-source tools.

Uses GitHub REST API v3. With a token, rate limit is 5,000 requests/hour.
Without a token, rate limit is 60 requests/hour (insufficient for batch processing).

Set GITHUB_TOKEN environment variable for authenticated requests.
"""

import logging
import os
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TIMEOUT = 10.0  # seconds


def _get_headers() -> dict[str, str]:
    """Build headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ai-tools-website/1.0",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_github_repo(url: str) -> Optional[tuple[str, str]]:
    """Extract owner/repo from a GitHub URL.

    Args:
        url: Any URL that might contain a GitHub repository reference

    Returns:
        Tuple of (owner, repo) if found, None otherwise

    Examples:
        >>> extract_github_repo("https://github.com/langchain-ai/langchain")
        ("langchain-ai", "langchain")
        >>> extract_github_repo("https://github.com/openai/whisper/tree/main")
        ("openai", "whisper")
    """
    if not url:
        return None

    # Match various GitHub URL patterns
    patterns = [
        r"github\.com/([^/]+)/([^/\?#]+)",  # Standard: github.com/owner/repo
        r"raw\.githubusercontent\.com/([^/]+)/([^/]+)",  # Raw content URLs
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner = match.group(1)
            repo = match.group(2)
            # Clean up repo name (remove .git suffix, etc.)
            repo = repo.rstrip("/").removesuffix(".git")
            return (owner, repo)

    return None


async def fetch_github_stats(
    owner: str,
    repo: str,
    *,
    include_commits: bool = True,
    include_contributors: bool = True,
) -> Optional[dict[str, Any]]:
    """Fetch comprehensive stats for a GitHub repository.

    Args:
        owner: Repository owner (user or organization)
        repo: Repository name
        include_commits: Whether to fetch recent commit activity
        include_contributors: Whether to fetch contributor count

    Returns:
        Dictionary with repository stats, or None if fetch failed
    """
    async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT) as client:
        headers = _get_headers()

        # Fetch main repository data
        repo_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        try:
            response = await client.get(repo_url, headers=headers)

            if response.status_code == 404:
                logger.warning(f"GitHub repo not found: {owner}/{repo}")
                return None

            if response.status_code == 403:
                logger.warning(f"GitHub rate limit exceeded or access denied: {owner}/{repo}")
                return None

            if response.status_code != 200:
                logger.warning(f"GitHub API error {response.status_code} for {owner}/{repo}")
                return None

            repo_data = response.json()

        except httpx.RequestError as exc:
            logger.error(f"GitHub request failed for {owner}/{repo}: {exc}")
            return None

        # Build stats object
        stats: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "full_name": repo_data.get("full_name"),
            "description": repo_data.get("description"),
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "watchers": repo_data.get("subscribers_count", 0),
            "license": None,
            "language": repo_data.get("language"),
            "topics": repo_data.get("topics", []),
            "created_at": repo_data.get("created_at"),
            "updated_at": repo_data.get("updated_at"),
            "pushed_at": repo_data.get("pushed_at"),
            "default_branch": repo_data.get("default_branch"),
            "homepage": repo_data.get("homepage"),
            "archived": repo_data.get("archived", False),
            "disabled": repo_data.get("disabled", False),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Extract license info
        license_info = repo_data.get("license")
        if license_info:
            stats["license"] = license_info.get("spdx_id") or license_info.get("name")

        # Fetch contributor count (separate API call)
        if include_contributors:
            try:
                # Use per_page=1 and check Link header for total count
                contrib_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contributors"
                contrib_response = await client.get(
                    contrib_url,
                    headers=headers,
                    params={"per_page": 1, "anon": "false"},
                )
                if contrib_response.status_code == 200:
                    # Parse Link header to get total count
                    link_header = contrib_response.headers.get("Link", "")
                    if 'rel="last"' in link_header:
                        # Extract page number from last link
                        match = re.search(r"page=(\d+)>; rel=\"last\"", link_header)
                        if match:
                            stats["contributors"] = int(match.group(1))
                    else:
                        # Small number of contributors, count directly
                        stats["contributors"] = len(contrib_response.json())
            except Exception as exc:
                logger.debug(f"Failed to fetch contributors for {owner}/{repo}: {exc}")

        # Fetch recent commit info
        if include_commits:
            try:
                commits_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits"
                commits_response = await client.get(
                    commits_url,
                    headers=headers,
                    params={"per_page": 5},
                )
                if commits_response.status_code == 200:
                    commits = commits_response.json()
                    if commits:
                        latest = commits[0]
                        commit_info = latest.get("commit", {})
                        stats["last_commit"] = {
                            "sha": latest.get("sha", "")[:7],
                            "message": commit_info.get("message", "").split("\n")[0][:100],
                            "date": commit_info.get("committer", {}).get("date"),
                            "author": commit_info.get("author", {}).get("name"),
                        }
            except Exception as exc:
                logger.debug(f"Failed to fetch commits for {owner}/{repo}: {exc}")

        # Fetch releases info (latest release)
        try:
            releases_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases/latest"
            release_response = await client.get(releases_url, headers=headers)
            if release_response.status_code == 200:
                release = release_response.json()
                stats["latest_release"] = {
                    "tag": release.get("tag_name"),
                    "name": release.get("name"),
                    "published_at": release.get("published_at"),
                    "prerelease": release.get("prerelease", False),
                }
        except Exception as exc:
            logger.debug(f"Failed to fetch releases for {owner}/{repo}: {exc}")

        return stats


async def fetch_github_stats_from_url(url: str) -> Optional[dict[str, Any]]:
    """Convenience function to fetch stats directly from a GitHub URL.

    Args:
        url: GitHub repository URL

    Returns:
        Repository stats or None if URL is not a valid GitHub repo
    """
    extracted = extract_github_repo(url)
    if not extracted:
        return None

    owner, repo = extracted
    return await fetch_github_stats(owner, repo)
