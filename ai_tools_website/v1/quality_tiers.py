"""Quality tier system for allocating content generation effort.

Tools are scored based on importance signals and assigned to tiers:
- Tier 1 (top 50): Deep research, frequent updates
- Tier 2 (next 150): Standard research, moderate updates
- Tier 3 (rest): Basic info, infrequent updates
- noindex: Too thin to index, skip LLM calls

This ensures budget is spent on pages most likely to rank.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from typing import Optional

logger = logging.getLogger(__name__)


# Static fallback category scores (used when no traffic data available)
HIGH_VALUE_CATEGORIES = [
    "language models",
    "image generation",
    "code assistants",
    "chatbots",
    "agents",
    "developer tools",
]
MEDIUM_VALUE_CATEGORIES = [
    "audio",
    "video",
    "data analysis",
    "automation",
    "writing",
]

MIN_DESCRIPTION_CHARS_FOR_INDEX = 60


def is_minimally_indexable(tool: dict[str, Any]) -> bool:
    """Heuristic: determine whether a tool page is worth indexing at all.

    We keep this intentionally conservative. If a tool has already been enhanced,
    we treat it as indexable even if the raw description is short.
    """
    if not tool.get("url"):
        return False

    desc = (tool.get("description") or "").strip()
    if len(desc) >= MIN_DESCRIPTION_CHARS_FOR_INDEX:
        return True

    return bool(tool.get("enhanced_content") or tool.get("enhanced_content_v2"))


@dataclass
class TierConfig:
    """Configuration for a quality tier."""

    name: str
    min_score: int
    max_count: Optional[int]  # None = unlimited
    web_searches: int  # Number of Tavily searches
    llm_calls: int  # Number of LLM passes
    refresh_days: int  # How often to refresh content
    noindex: bool = False  # Whether to add noindex meta tag


# Tier definitions
TIERS = {
    "tier1": TierConfig(
        name="tier1",
        min_score=80,
        max_count=50,
        web_searches=5,
        llm_calls=3,  # gather, analyze, write
        refresh_days=7,
    ),
    "tier2": TierConfig(
        name="tier2",
        min_score=50,
        max_count=150,
        web_searches=2,
        llm_calls=2,  # gather+analyze, write
        refresh_days=14,
    ),
    "tier3": TierConfig(
        name="tier3",
        min_score=20,
        max_count=None,
        web_searches=0,
        llm_calls=1,  # single pass
        refresh_days=30,
    ),
    "noindex": TierConfig(
        name="noindex",
        min_score=0,
        max_count=None,
        web_searches=0,
        llm_calls=0,
        refresh_days=0,  # Never refresh
        noindex=True,
    ),
}


def compute_category_scores_from_traffic(
    tools: list[dict[str, Any]],
    traffic_by_slug: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Compute dynamic category scores based on actual traffic data.

    Aggregates pageviews by category and assigns scores based on percentiles:
    - Top 20% of categories: 15 points
    - Next 30% of categories: 10 points
    - Bottom 50% of categories: 5 points

    Args:
        tools: List of tool dictionaries
        traffic_by_slug: Dict mapping tool slugs to traffic stats

    Returns:
        Dict mapping category names (lowercase) to score values (5, 10, or 15)
    """
    if not traffic_by_slug:
        return {}

    # Aggregate traffic by category
    category_traffic: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)

    for tool in tools:
        category = (tool.get("category") or "").lower().strip()
        if not category:
            continue

        slug = (tool.get("slug") or "").lower()
        if slug in traffic_by_slug:
            pageviews = traffic_by_slug[slug].get("pageviews_30d", 0)
            category_traffic[category] += pageviews
            category_counts[category] += 1

    if not category_traffic:
        return {}

    # Sort categories by total traffic (descending)
    sorted_categories = sorted(
        category_traffic.keys(),
        key=lambda c: category_traffic[c],
        reverse=True,
    )

    # Assign scores based on percentile thresholds
    total_categories = len(sorted_categories)
    top_20_cutoff = int(total_categories * 0.2)
    top_50_cutoff = int(total_categories * 0.5)

    category_scores: dict[str, int] = {}
    for i, category in enumerate(sorted_categories):
        if i < top_20_cutoff:
            category_scores[category] = 15  # Top 20%
        elif i < top_50_cutoff:
            category_scores[category] = 10  # Next 30%
        else:
            category_scores[category] = 5  # Bottom 50%

    logger.info(
        f"Computed dynamic category scores: "
        f"{sum(1 for s in category_scores.values() if s == 15)} high, "
        f"{sum(1 for s in category_scores.values() if s == 10)} medium, "
        f"{sum(1 for s in category_scores.values() if s == 5)} low"
    )

    return category_scores


def calculate_importance_score(
    tool: dict[str, Any],
    external_data: Optional[dict[str, Any]] = None,
    category_scores: Optional[dict[str, int]] = None,
) -> int:
    """Calculate importance score for a tool (0-100).

    Scoring factors:
    - GitHub stars (if open source): max 35 points
    - HuggingFace downloads (if ML model): max 35 points
    - Category popularity: max 15 points
    - Content quality signals: max 10 points
    - Existing content quality: max 5 points
    - Umami traffic (percentile-based): max 25 points

    Args:
        tool: Tool dictionary
        external_data: Pre-fetched external data (github_stats, hf_stats, umami_stats, etc.)
        category_scores: Optional dynamic category scores from traffic data (computed by
            compute_category_scores_from_traffic). Falls back to static lists if not provided.

    Returns:
        Score from 0-100 (capped)
    """
    score = 0
    external_data = external_data or {}

    # === GitHub Metrics (max 35 points) ===
    github_stats = external_data.get("github_stats") or tool.get("external_data", {}).get("github_stats")
    if github_stats:
        stars = github_stats.get("stars", 0)
        if stars >= 50000:
            score += 35
        elif stars >= 20000:
            score += 30
        elif stars >= 10000:
            score += 25
        elif stars >= 5000:
            score += 20
        elif stars >= 1000:
            score += 15
        elif stars >= 500:
            score += 10
        elif stars >= 100:
            score += 5

        # Bonus for active development (recent commits)
        last_commit = github_stats.get("last_commit", {})
        if last_commit:
            # If pushed within last 30 days
            pushed_at = github_stats.get("pushed_at")
            if pushed_at:
                # Simple check - if year is current, give bonus
                try:
                    from datetime import datetime

                    pushed_date = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                    days_ago = (datetime.now(pushed_date.tzinfo) - pushed_date).days
                    if days_ago <= 30:
                        score += 5
                    elif days_ago <= 90:
                        score += 3
                except (ValueError, TypeError):
                    pass

    # === HuggingFace Metrics (max 35 points) ===
    hf_stats = external_data.get("huggingface_stats") or tool.get("external_data", {}).get("huggingface_stats")
    if hf_stats:
        downloads = hf_stats.get("downloads", 0) or hf_stats.get("downloads_all_time", 0)
        if downloads >= 10_000_000:
            score += 35
        elif downloads >= 1_000_000:
            score += 30
        elif downloads >= 500_000:
            score += 25
        elif downloads >= 100_000:
            score += 20
        elif downloads >= 50_000:
            score += 15
        elif downloads >= 10_000:
            score += 10
        elif downloads >= 1000:
            score += 5

        # Likes bonus
        likes = hf_stats.get("likes", 0)
        if likes >= 1000:
            score += 5
        elif likes >= 100:
            score += 3

    # === Category Popularity (max 15 points) ===
    category = tool.get("category", "").lower()

    # Use dynamic scores from traffic data if available
    if category_scores and category in category_scores:
        score += category_scores[category]
    else:
        # Fall back to static category lists
        for cat in HIGH_VALUE_CATEGORIES:
            if cat in category:
                score += 15
                break
        else:
            for cat in MEDIUM_VALUE_CATEGORIES:
                if cat in category:
                    score += 10
                    break
            else:
                score += 5  # Base category score

    # === Content Quality Signals (max 10 points) ===
    description = tool.get("description", "")
    if len(description) >= 200:
        score += 5
    elif len(description) >= 100:
        score += 3
    elif len(description) >= 50:
        score += 1

    # Has URL
    if tool.get("url"):
        score += 2

    # Has tags
    tags = tool.get("tags", [])
    if len(tags) >= 3:
        score += 3

    # === Existing Content Quality (max 5 points) ===
    enhanced = tool.get("enhanced_content") or tool.get("enhanced_content_v2")
    if enhanced:
        # Has been enhanced before
        score += 2
        # Has comparisons
        if tool.get("comparisons"):
            score += 3

    # === Umami Traffic Metrics (max 25 points) ===
    # Pre-calculated percentile-based score from fetch_traffic_stats()
    umami_stats = external_data.get("umami_stats", {})
    traffic_score = umami_stats.get("traffic_score", 0)
    score += traffic_score

    # Cap at 100
    return min(score, 100)


def get_tier_config(tier_name: str) -> TierConfig:
    """Get configuration for a tier."""
    return TIERS.get(tier_name, TIERS["noindex"])


def tier_all_tools(
    tools: list[dict[str, Any]],
    external_data_map: Optional[dict[str, dict[str, Any]]] = None,
    category_scores: Optional[dict[str, int]] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Assign tiers to all tools.

    Args:
        tools: List of tool dictionaries
        external_data_map: Map of tool name/id to external data
        category_scores: Optional dynamic category scores from traffic data

    Returns:
        Dictionary with tier names as keys and lists of tools as values
    """
    external_data_map = external_data_map or {}
    tiered: dict[str, list[dict[str, Any]]] = {
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "noindex": [],
    }

    # Score all tools first
    scored_tools: list[tuple[dict[str, Any], int]] = []
    for tool in tools:
        tool_id = tool.get("id") or tool.get("name", "")
        external_data = external_data_map.get(tool_id, {})
        score = calculate_importance_score(tool, external_data, category_scores=category_scores)
        scored_tools.append((tool, score))

    # Sort by score descending
    scored_tools.sort(key=lambda x: x[1], reverse=True)

    # Assign tiers by rank (while still allowing a true noindex bucket).
    # Rationale: without external metrics, score thresholds often lead to empty tier1/tier2.
    tier1_limit = TIERS["tier1"].max_count or 0
    tier2_limit = TIERS["tier2"].max_count or 0

    for tool, score in scored_tools:
        if not is_minimally_indexable(tool):
            tier = "noindex"
        elif len(tiered["tier1"]) < tier1_limit:
            tier = "tier1"
        elif len(tiered["tier2"]) < tier2_limit:
            tier = "tier2"
        else:
            tier = "tier3"

        tiered[tier].append(tool)

        # Store score and tier on tool for reference
        tool["_importance_score"] = score
        tool["_tier"] = tier

    logger.info(
        f"Tiered {len(tools)} tools: "
        f"tier1={len(tiered['tier1'])}, "
        f"tier2={len(tiered['tier2'])}, "
        f"tier3={len(tiered['tier3'])}, "
        f"noindex={len(tiered['noindex'])}"
    )

    return tiered


def should_refresh(tool: dict[str, Any], tier: Optional[str] = None) -> bool:
    """Check if a tool's content should be refreshed.

    Args:
        tool: Tool dictionary
        tier: Tier name (if not provided, uses tool's _tier)

    Returns:
        True if content is stale and should be refreshed
    """
    from datetime import datetime
    from datetime import timedelta
    from datetime import timezone

    tier = tier or tool.get("_tier", "tier3")
    config = get_tier_config(tier)

    if config.refresh_days == 0:
        return False  # Never refresh noindex

    # Priority: Check enhanced_content_v2 timestamp
    enhanced_at = tool.get("enhanced_at_v2")
    if not enhanced_at:
        return True  # No V2 content yet, always refresh

    try:
        enhanced_time = datetime.fromisoformat(enhanced_at.replace("Z", "+00:00"))
        stale_after = timedelta(days=config.refresh_days)
        return datetime.now(timezone.utc) - enhanced_time >= stale_after
    except (ValueError, TypeError):
        return True  # Invalid timestamp, refresh
