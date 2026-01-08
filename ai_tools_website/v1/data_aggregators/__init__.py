"""Data aggregators for fetching external metrics about AI tools."""

from .github_aggregator import extract_github_repo
from .github_aggregator import fetch_github_stats
from .huggingface_aggregator import extract_huggingface_id
from .huggingface_aggregator import fetch_huggingface_stats
from .package_aggregator import fetch_npm_stats
from .package_aggregator import fetch_pypi_stats

__all__ = [
    "fetch_github_stats",
    "extract_github_repo",
    "fetch_huggingface_stats",
    "extract_huggingface_id",
    "fetch_pypi_stats",
    "fetch_npm_stats",
]
