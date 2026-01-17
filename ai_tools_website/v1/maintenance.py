"""Maintenance tasks for the AI tools database."""

import asyncio
import logging
from datetime import datetime
from datetime import timezone
from typing import List

from pydantic import BaseModel
from pydantic import Field

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import MAINTENANCE_MODEL
from .quality_tiers import compute_category_scores_from_traffic
from .quality_tiers import tier_all_tools
from .search import build_category_context
from .search import client
from .search import smart_deduplicate_tools


class CategoryChange(BaseModel):
    """Represents a category name change."""

    from_category: str = Field(alias="from", description="Original category name")
    to_category: str = Field(alias="to", description="New category name")
    reason: str = Field(description="Explanation for the change")


class ToolMove(BaseModel):
    """Represents moving a tool to a different category."""

    tool: str = Field(description="Name of the tool to move")
    from_category: str = Field(alias="from", description="Original category")
    to_category: str = Field(alias="to", description="New category")
    reason: str = Field(description="Explanation for the move")


class RecategorizationChanges(BaseModel):
    """Complete set of categorization changes."""

    category_changes: List[CategoryChange] = Field(default_factory=list)
    tool_moves: List[ToolMove] = Field(default_factory=list)


logger = logging.getLogger(__name__)


async def recategorize_database(auto_accept: bool = False) -> None:
    """Do a complete review and reorganization of tool categories."""
    with pipeline_summary("maintenance") as summary:
        logger.info("Starting tool recategorization...")
        current = load_tools()
        total = len(current["tools"])
        logger.info(f"Processing {total} tools")
        summary.add_metric("total_tools", total)
        summary.add_attribute("auto_accept", auto_accept)

        # Get AI to analyze current categorization and suggest improvements
        categories_text = build_category_context(current)

        completion = client.beta.chat.completions.parse(
            model=MAINTENANCE_MODEL,
            reasoning_effort="low",
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert at organizing AI tools into meaningful categories.
Your task is to analyze the current categorization and suggest improvements.
Consider:
1. Categories that could be merged (e.g., 'LLMs' and 'Language Models')
2. Categories that should be split (e.g., if 'Other' contains distinct groups)
3. Tools that might fit better in different categories
4. Category names that could be more clear or consistent

Since this task will run often, be careful to not keep creating more specific categories.
Focus on broad categories that a user will be seeing on a webpage and can quickly scroll through.
Also we can differentiate and mix 'models' and 'tools'. So they can have their own categories.

IMPORTANT RULES FOR CATEGORY NAMES:
1. Must be a simple, concise noun or noun phrase (e.g. "Language Models", "Developer Tools")
2. Never use explanatory phrases or parentheticals as category names
3. Never include words like "redistributed" or "moved to" in category names
4. Keep names short and clear - ideally 1-3 words
5. Use title case consistently


""",
                },
                {
                    "role": "user",
                    "content": f"""Here is our current database of tools organized by category:

{categories_text}

Analyze this categorization and suggest a revised category structure.""",
                },
            ],
            response_format=RecategorizationChanges,
        )

        changes = completion.choices[0].message.parsed
        logger.info("\nProposed reorganization changes:")

        summary.add_metric("proposed_category_changes", len(changes.category_changes))
        summary.add_metric("proposed_tool_moves", len(changes.tool_moves))

        if not changes.category_changes and not changes.tool_moves:
            logger.info("No changes suggested, categories look good!")
            summary.add_attribute("no_changes", True)
            return

        if changes.category_changes:
            logger.info("\nCategory renames:")
            for change in changes.category_changes:
                logger.info(f"  • {change.from_category} -> {change.to_category}")
                logger.info(f"    Reason: {change.reason}")

        if changes.tool_moves:
            logger.info("\nTool moves:")
            for move in changes.tool_moves:
                logger.info(f"  • {move.tool}: {move.from_category} -> {move.to_category}")
                logger.info(f"    Reason: {move.reason}")

        # Get user confirmation if not auto-accepting
        if not auto_accept:
            response = input("\nApply these changes? (y/n): ").lower().strip()
            if response != "y":
                logger.info("Changes cancelled.")
                summary.add_attribute("cancelled", True)
                return
        else:
            logger.info("Auto-accepting changes...")

        logger.info("Applying changes...")
        timestamp = datetime.now(timezone.utc).isoformat()
        updated_tools = []

        # Create mapping of old -> new categories
        category_map = {c.from_category: c.to_category for c in changes.category_changes}

        # Create mapping of tool -> new category
        tool_map = {m.tool: m.to_category for m in changes.tool_moves}

        moved_count = 0
        renamed_count = 0

        for tool in current["tools"]:
            new_tool = tool.copy()
            current_cat = tool.get("category", "Other")

            # Check if tool should move
            if tool["name"] in tool_map:
                new_tool["category"] = tool_map[tool["name"]]
                moved_count += 1
                logger.info(f"Moving {tool['name']} to {new_tool['category']}")
            # Check if category should change
            elif current_cat in category_map:
                new_tool["category"] = category_map[current_cat]
                renamed_count += 1
                logger.info(f"Updating category for {tool['name']}: {current_cat} -> {new_tool['category']}")

            new_tool["last_reviewed_at"] = timestamp
            new_tool["last_indexed_at"] = timestamp

            updated_tools.append(new_tool)

        # Save changes
        current["tools"] = updated_tools
        current["slug_registry_version"] = 1
        save_tools(current)
        summary.add_metric("tools_reassigned", moved_count)
        summary.add_metric("tools_renamed", renamed_count)
        logger.info("Reorganization complete!")


async def deduplicate_database() -> None:
    """One-time cleanup to deduplicate the tools database."""
    with pipeline_summary("maintenance_deduplicate") as summary:
        logger.info("Starting database deduplication...")
        current = load_tools()
        total = len(current["tools"])
        logger.info(f"Processing {total} tools")
        summary.add_metric("total_tools", total)

        cleaned_tools = await smart_deduplicate_tools(current["tools"])

        # Save cleaned database
        removed = total - len(cleaned_tools)
        logger.info(f"Removed {removed} duplicates")
        current["tools"] = cleaned_tools
        save_tools(current)
        summary.add_metric("duplicates_removed", removed)
        summary.add_metric("final_total", len(cleaned_tools))
        logger.info("Deduplication complete!")


async def tier_database() -> None:
    """Re-calculate quality tiers for all tools."""
    with pipeline_summary("maintenance_tiering") as summary:
        logger.info("Starting tool tiering...")
        current = load_tools()
        tools = current["tools"]
        logger.info(f"Tiering {len(tools)} tools")

        # In a full run, we'd pre-gather external data here.
        # For this maintenance task, we use what's already in the tool records.
        tiered = tier_all_tools(tools)

        # tier_all_tools modifies the tool dicts in place (sets _tier and _importance_score)
        save_tools(current)

        for tier_name, tier_tools in tiered.items():
            summary.add_metric(f"count_{tier_name}", len(tier_tools))
            logger.info(f"Tier {tier_name}: {len(tier_tools)} tools")

        logger.info("Tiering complete!")


async def tier_database_with_traffic() -> None:
    """Re-calculate quality tiers for all tools, including Umami traffic data.

    This fetches pageview data from Umami and uses percentile-based scoring
    to boost high-traffic tools in the tier rankings.
    """
    from .data_aggregators import fetch_traffic_stats
    from .seo_utils import generate_tool_slug

    with pipeline_summary("maintenance_tiering_traffic") as summary:
        logger.info("Starting tool tiering with traffic data...")
        current = load_tools()
        tools = current["tools"]
        logger.info(f"Tiering {len(tools)} tools")

        # Fetch all Umami traffic data in one batch
        logger.info("Fetching Umami traffic data...")
        try:
            traffic_stats = await fetch_traffic_stats()
            summary.add_metric("tools_with_traffic", len(traffic_stats))
            logger.info(f"Got traffic data for {len(traffic_stats)} tools")

            # Log top 10 by traffic for visibility
            if traffic_stats:
                sorted_traffic = sorted(
                    traffic_stats.items(),
                    key=lambda x: x[1].get("pageviews_30d", 0),
                    reverse=True,
                )[:10]
                logger.info("Top 10 tools by traffic:")
                for slug, stats in sorted_traffic:
                    logger.info(
                        f"  {slug}: {stats.get('pageviews_30d', 0)} views, " f"score +{stats.get('traffic_score', 0)}"
                    )
        except Exception as exc:
            logger.warning(f"Failed to fetch Umami data, continuing without: {exc}")
            traffic_stats = {}
            summary.add_attribute("umami_fetch_failed", True)

        # Build external_data_map with traffic data
        external_data_map: dict[str, dict] = {}
        for tool in tools:
            tool_id = tool.get("id") or tool.get("name", "")
            slug = (tool.get("slug") or generate_tool_slug(tool.get("name", ""))).lower()

            # Start with existing external_data from tool record
            ext_data = dict(tool.get("external_data", {}))

            # Add Umami stats if available
            if slug in traffic_stats:
                ext_data["umami_stats"] = traffic_stats[slug]

            external_data_map[tool_id] = ext_data

        # Compute dynamic category scores from traffic data
        category_scores = compute_category_scores_from_traffic(tools, traffic_stats)
        if category_scores:
            summary.add_metric("categories_with_traffic", len(category_scores))

        # Tier with external data and dynamic category scores
        tiered = tier_all_tools(tools, external_data_map, category_scores=category_scores)

        # Save tiered results
        save_tools(current)

        for tier_name, tier_tools in tiered.items():
            summary.add_metric(f"count_{tier_name}", len(tier_tools))
            logger.info(f"Tier {tier_name}: {len(tier_tools)} tools")

        logger.info("Tiering with traffic complete!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Tools Website Maintenance Tasks")
    parser.add_argument(
        "task",
        choices=["deduplicate", "recategorize", "tier", "tier-traffic"],
        help="Maintenance task to perform",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-accept changes without prompting")

    args = parser.parse_args()
    setup_logging()

    if args.task == "deduplicate":
        asyncio.run(deduplicate_database())
    elif args.task == "recategorize":
        asyncio.run(recategorize_database(auto_accept=args.yes))
    elif args.task == "tier":
        asyncio.run(tier_database())
    elif args.task == "tier-traffic":
        asyncio.run(tier_database_with_traffic())
