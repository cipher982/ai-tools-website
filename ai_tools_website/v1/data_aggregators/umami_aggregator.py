"""Fetch Umami pageview metrics for tool traffic analysis.

Uses direct PostgreSQL access to Umami database on clifford server.
Batch-fetches all tool page views for efficiency.

Set UMAMI_SSH_HOST environment variable to configure the SSH host (default: clifford).
Set UMAMI_AITOOLS_WEBSITE_ID to configure the website ID.
"""

import logging
import os
import subprocess
from datetime import datetime
from datetime import timezone
from typing import Any

logger = logging.getLogger(__name__)

# Umami configuration
UMAMI_AITOOLS_WEBSITE_ID = os.getenv("UMAMI_AITOOLS_WEBSITE_ID", "044a36a5-fdb5-430f-97c5-3903afdda191")
UMAMI_DB_CONTAINER = "postgresql-es84cow0os8kc80wgkg0g408"
UMAMI_DB_USER = "4rfR7GJFefbxMc8j"
UMAMI_DB_NAME = "umami"
SSH_HOST = os.getenv("UMAMI_SSH_HOST", "clifford")

UMAMI_QUERY_TIMEOUT = 30  # seconds
MIN_VIEWS_THRESHOLD = 10  # Filter noise/bot traffic
MIN_TOTAL_VIEWS_SANITY = 100  # Skip if total views too low (indicates Umami issue)


def _run_umami_query(sql: str) -> str | None:
    """Execute SQL query against Umami PostgreSQL via SSH.

    Returns raw output or None on failure.
    """
    # Use psql with -t (tuples only), -A (unaligned), -F (field separator)
    cmd = [
        "ssh",
        SSH_HOST,
        f"docker exec {UMAMI_DB_CONTAINER} psql -U {UMAMI_DB_USER} -d {UMAMI_DB_NAME} -t -A -F ',' -c \"{sql}\"",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=UMAMI_QUERY_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning(f"Umami query failed: {result.stderr}")
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("Umami query timed out")
        return None
    except Exception as exc:
        logger.error(f"Umami query error: {exc}")
        return None


async def fetch_all_tool_pageviews(days: int = 30) -> dict[str, int]:
    """Batch fetch pageview counts for all tool pages.

    Args:
        days: Number of days to look back (default 30)

    Returns:
        Dictionary mapping tool slug to pageview count
        e.g., {"chatgpt": 15234, "whisperx": 892, ...}
    """
    # Query for pageviews on /aitools/tools/* paths
    # Uses split_part instead of regex for better performance
    # Strips query params and lowercases for consistent matching
    sql = f"""
    SELECT
        LOWER(split_part(split_part(url_path, '?', 1), '/', 4)) as slug,
        COUNT(*) as views
    FROM website_event
    WHERE website_id = '{UMAMI_AITOOLS_WEBSITE_ID}'
      AND url_path LIKE '/aitools/tools/%'
      AND url_path NOT LIKE '/aitools/tools/%/%'
      AND created_at > NOW() - INTERVAL '{days} days'
    GROUP BY LOWER(split_part(split_part(url_path, '?', 1), '/', 4))
    HAVING COUNT(*) >= {MIN_VIEWS_THRESHOLD}
    ORDER BY views DESC
    """.strip()

    output = _run_umami_query(sql)
    if not output:
        logger.warning("No Umami data returned, returning empty dict")
        return {}

    pageviews: dict[str, int] = {}
    total_views = 0

    for line in output.split("\n"):
        if "," in line:
            parts = line.split(",")
            if len(parts) == 2:
                slug, count = parts
                if slug and count.isdigit():
                    views = int(count)
                    pageviews[slug] = views
                    total_views += views

    # Sanity check: if total views is suspiciously low, skip
    if total_views < MIN_TOTAL_VIEWS_SANITY and pageviews:
        logger.warning(
            f"Total views ({total_views}) below sanity threshold ({MIN_TOTAL_VIEWS_SANITY}), "
            "skipping traffic scores (possible Umami issue)"
        )
        return {}

    logger.info(f"Fetched pageview data for {len(pageviews)} tool pages ({total_views} total views)")
    return pageviews


def get_traffic_scores(pageviews_by_slug: dict[str, int]) -> dict[str, int]:
    """Assign scores based on percentile rank, not absolute thresholds.

    This auto-adjusts as overall traffic changes.

    Args:
        pageviews_by_slug: Dictionary mapping slug to pageview count

    Returns:
        Dictionary mapping slug to score (0-25)
    """
    if not pageviews_by_slug:
        return {}

    # Sort by views descending
    sorted_tools = sorted(pageviews_by_slug.items(), key=lambda x: x[1], reverse=True)
    total = len(sorted_tools)

    scores: dict[str, int] = {}
    for rank, (slug, views) in enumerate(sorted_tools):
        percentile = (rank / total) * 100  # 0 = top, 100 = bottom

        if percentile <= 5:  # Top 5%
            scores[slug] = 25
        elif percentile <= 15:  # Top 15%
            scores[slug] = 20
        elif percentile <= 30:  # Top 30%
            scores[slug] = 15
        elif percentile <= 50:  # Top 50%
            scores[slug] = 10
        elif percentile <= 75:  # Top 75%
            scores[slug] = 5
        else:  # Bottom 25%
            scores[slug] = 0

    return scores


async def fetch_traffic_stats() -> dict[str, dict[str, Any]]:
    """Fetch all traffic stats and pre-calculate scores.

    This is the main entry point for the maintenance task.

    Returns:
        Dictionary mapping slug to stats dict with:
        - pageviews_30d: raw pageview count
        - traffic_score: percentile-based score (0-25)
        - fetched_at: ISO timestamp
    """
    pageviews = await fetch_all_tool_pageviews(days=30)
    scores = get_traffic_scores(pageviews)

    fetched_at = datetime.now(timezone.utc).isoformat()

    stats: dict[str, dict[str, Any]] = {}
    for slug, views in pageviews.items():
        stats[slug] = {
            "pageviews_30d": views,
            "traffic_score": scores.get(slug, 0),
            "fetched_at": fetched_at,
        }

    return stats
