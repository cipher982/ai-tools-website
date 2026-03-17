"""Maintenance tasks for the AI tools database."""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from datetime import timezone
from typing import List

from pydantic import BaseModel
from pydantic import Field

from .data_aggregators.umami_aggregator import UmamiDataStaleError
from .data_manager import load_tools
from .data_manager import save_tools_with_retry
from .editorial_batch import DEFAULT_MAX_PER_RUN
from .editorial_batch import DEFAULT_STALE_AFTER_DAYS
from .editorial_batch import run_editorial_review_batch
from .editorial_loop import DEFAULT_CONTENT_MAX_PER_RUN
from .editorial_loop import run_editorial_loop
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import MAINTENANCE_MODEL
from .public_catalog import build_category_metadata
from .public_catalog import project_tools_document
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
                new_category = tool_map[tool["name"]]
                if new_category != current_cat:
                    new_tool["category"] = new_category
                    new_tool["updated_at"] = timestamp
                    moved_count += 1
                    logger.info(f"Moving {tool['name']} to {new_tool['category']}")
            # Check if category should change
            elif current_cat in category_map:
                new_category = category_map[current_cat]
                if new_category != current_cat:
                    new_tool["category"] = new_category
                    new_tool["updated_at"] = timestamp
                    renamed_count += 1
                    logger.info(f"Updating category for {tool['name']}: {current_cat} -> {new_tool['category']}")

            updated_tools.append(new_tool)

        if moved_count == 0 and renamed_count == 0:
            logger.info("Proposed changes did not alter the current database.")
            summary.add_attribute("no_effective_changes", True)
            return

        # Save changes
        current["tools"] = updated_tools
        current["slug_registry_version"] = 1
        save_tools_with_retry(current)
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
        save_tools_with_retry(current)
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
        save_tools_with_retry(current)

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
        except UmamiDataStaleError:
            raise  # Data staleness is a hard failure — don't silently degrade
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
        save_tools_with_retry(current)

        for tier_name, tier_tools in tiered.items():
            summary.add_metric(f"count_{tier_name}", len(tier_tools))
            logger.info(f"Tier {tier_name}: {len(tier_tools)} tools")

        logger.info("Tiering with traffic complete!")


def slim_reset_database(*, dry_run: bool = False, json_output: bool = False, drop_nonpublic: bool = True) -> dict:
    """Rewrite the catalog into the slim public-record shape."""
    with pipeline_summary("maintenance_slim_reset") as summary:
        logger.info("Starting slim directory reset...")
        current = load_tools()
        total = len(current.get("tools", []))
        summary.add_metric("total_tools", total)
        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("drop_nonpublic", drop_nonpublic)

        projected_tools, counts = project_tools_document(current, drop_nonpublic=drop_nonpublic)
        summary.add_metric("projected_tools", len(projected_tools))
        for status_name, count in counts.items():
            summary.add_metric(status_name, count)

        projected_doc = dict(current)
        projected_doc["tools"] = projected_tools
        projected_doc["category_metadata"] = build_category_metadata(projected_tools)
        projected_doc.pop("slug_registry_version", None)

        result = {
            "total_tools": total,
            "projected_tools": len(projected_tools),
            "status_counts": counts,
            "categories": sorted(
                {tool.get("category", "") for tool in projected_tools},
                key=lambda category: category.lower(),
            ),
        }

        if dry_run:
            logger.info("[DRY RUN] Slim reset would rewrite the catalog to %s public tools", len(projected_tools))
        else:
            save_tools_with_retry(projected_doc)
            logger.info("Slim reset saved %s public tools", len(projected_tools))

        if json_output:
            print(json.dumps(result, indent=2))

        return result


def editorial_review_database(
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    slugs: list[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    dry_run: bool = False,
    force: bool = False,
    use_web_search: bool = True,
    json_output: bool = False,
):
    """Run the bounded editorial review flow through the maintenance CLI."""
    with pipeline_summary("maintenance_editorial_review") as summary:
        logger.info("Starting editorial review batch...")
        summary.add_metric("max_per_run", max_per_run)
        summary.add_metric("stale_after_days", stale_after_days)
        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_attribute("use_web_search", use_web_search)
        if slugs:
            summary.add_attribute("requested_slugs", ",".join(slugs))

        result = run_editorial_review_batch(
            max_per_run=max_per_run,
            slugs=slugs,
            stale_after_days=stale_after_days,
            dry_run=dry_run,
            force=force,
            use_web_search=use_web_search,
        )

        summary.add_metric("selected", result.selected)
        summary.add_metric("reviewed", result.reviewed)
        summary.add_metric("updated", result.updated)
        summary.add_metric("failed", result.failed)
        if result.failed:
            summary.mark_failed(error_type="PartialFailure", note=f"{result.failed} editorial reviews failed")
        for action, count in result.action_counts.items():
            summary.add_metric(f"action_{action}", count)
        if result.missing_slugs:
            summary.add_attribute("missing_slugs", ",".join(result.missing_slugs))

        if json_output:
            print(json.dumps(result.to_dict(), indent=2))

        return result


def editorial_loop_database(
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    content_max_per_run: int = DEFAULT_CONTENT_MAX_PER_RUN,
    slugs: list[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    dry_run: bool = False,
    force: bool = False,
    use_web_search: bool = True,
    json_output: bool = False,
):
    """Run the autonomous editorial loop through the maintenance CLI."""
    with pipeline_summary("maintenance_editorial_loop") as summary:
        logger.info("Starting editorial loop...")
        summary.add_metric("max_per_run", max_per_run)
        summary.add_metric("content_max_per_run", content_max_per_run)
        summary.add_metric("stale_after_days", stale_after_days)
        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_attribute("use_web_search", use_web_search)
        if slugs:
            summary.add_attribute("requested_slugs", ",".join(slugs))

        result = run_editorial_loop(
            max_per_run=max_per_run,
            content_max_per_run=content_max_per_run,
            slugs=slugs,
            stale_after_days=stale_after_days,
            dry_run=dry_run,
            force=force,
            use_web_search=use_web_search,
        )

        summary.add_metric("selected", result.selected)
        summary.add_metric("reviewed", result.reviewed)
        summary.add_metric("updated", result.updated)
        summary.add_metric("enriched", result.enriched)
        summary.add_metric("failed", result.failed)
        summary.add_metric("content_failed", result.content_failed)
        if result.failed or result.content_failed:
            notes = []
            if result.failed:
                notes.append(f"{result.failed} editorial reviews failed")
            if result.content_failed:
                notes.append(f"{result.content_failed} content refreshes failed")
            summary.mark_failed(error_type="PartialFailure", note="; ".join(notes))
        for action, count in result.action_counts.items():
            summary.add_metric(f"action_{action}", count)
        for reason, count in result.reason_counts.items():
            summary.add_metric(f"reason_{reason}", count)
        if result.missing_slugs:
            summary.add_attribute("missing_slugs", ",".join(result.missing_slugs))

        if json_output:
            print(json.dumps(result.to_dict(), indent=2))

        return result


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for maintenance tasks."""
    parser = argparse.ArgumentParser(description="AI Tools Website Maintenance Tasks")
    parser.add_argument(
        "task",
        choices=[
            "deduplicate",
            "recategorize",
            "tier",
            "tier-traffic",
            "editorial-review",
            "editorial-loop",
            "slim-reset",
        ],
        help="Maintenance task to perform",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-accept changes without prompting")
    parser.add_argument("--max-per-run", type=int, default=DEFAULT_MAX_PER_RUN, help="Max tools to review")
    parser.add_argument(
        "--content-max-per-run",
        type=int,
        default=DEFAULT_CONTENT_MAX_PER_RUN,
        help="Max kept tools to enrich in one run",
    )
    parser.add_argument("--slug", dest="slugs", action="append", default=[], help="Specific slug to review; repeatable")
    parser.add_argument(
        "--stale-after-days",
        type=int,
        default=DEFAULT_STALE_AFTER_DAYS,
        help="Re-review age threshold in days",
    )
    parser.add_argument("--dry-run", action="store_true", help="Review without persisting changes")
    parser.add_argument("--force", action="store_true", help="Review selected candidates even if fresh")
    parser.add_argument("--no-web-search", dest="use_web_search", action="store_false", default=True)
    parser.add_argument("--json-output", action="store_true", help="Print structured JSON output")
    return parser


def dispatch_task(args: argparse.Namespace) -> None:
    """Dispatch parsed CLI arguments to the right maintenance task."""
    if args.task == "deduplicate":
        asyncio.run(deduplicate_database())
    elif args.task == "recategorize":
        asyncio.run(recategorize_database(auto_accept=args.yes))
    elif args.task == "tier":
        asyncio.run(tier_database())
    elif args.task == "tier-traffic":
        asyncio.run(tier_database_with_traffic())
    elif args.task == "editorial-review":
        editorial_review_database(
            max_per_run=args.max_per_run,
            slugs=args.slugs,
            stale_after_days=args.stale_after_days,
            dry_run=args.dry_run,
            force=args.force,
            use_web_search=args.use_web_search,
            json_output=args.json_output,
        )
    elif args.task == "editorial-loop":
        editorial_loop_database(
            max_per_run=args.max_per_run,
            content_max_per_run=args.content_max_per_run,
            slugs=args.slugs,
            stale_after_days=args.stale_after_days,
            dry_run=args.dry_run,
            force=args.force,
            use_web_search=args.use_web_search,
            json_output=args.json_output,
        )
    elif args.task == "slim-reset":
        slim_reset_database(
            dry_run=args.dry_run,
            json_output=args.json_output,
        )


def main(argv: list[str] | None = None) -> None:
    """Run the maintenance CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging()
    dispatch_task(args)


if __name__ == "__main__":
    main()
