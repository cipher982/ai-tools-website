"""Generate comprehensive AI tool comparison articles with web search research."""

import json
import logging
import os
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

import click
from dotenv import load_dotenv
from openai import OpenAI

from .data_manager import get_minio_client
from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import COMPARISON_GENERATOR_MODEL
from .openai_utils import count_all_citations
from .openai_utils import extract_responses_api_citations
from .openai_utils import extract_responses_api_text
from .openai_utils import parse_json_response
from .seo_utils import generate_comparison_slug
from .seo_utils import generate_tool_slug
from .slug_registry import collect_existing_slugs
from .slug_registry import ensure_unique_slug
from .slug_registry import load_slug_registry
from .slug_registry import register_comparison_slug
from .slug_registry import save_slug_registry
from .storage import local_comparison_opportunities_path
from .storage import read_local_json
from .storage import use_local_storage

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_MAX_PER_RUN = int(os.getenv("COMPARISON_GENERATOR_MAX_PER_RUN", "10"))
DEFAULT_STALE_DAYS = int(os.getenv("COMPARISON_GENERATOR_STALE_DAYS", "7"))
COMPARISON_OPPORTUNITIES_FILE = "comparison_opportunities.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_comparison_opportunities() -> List[Dict[str, Any]]:
    """Load comparison opportunities from MinIO."""
    if use_local_storage():
        path = local_comparison_opportunities_path(COMPARISON_OPPORTUNITIES_FILE)
        data = read_local_json(path, {"opportunities": []})
        opportunities = data.get("opportunities", [])
        logger.info(f"Loaded {len(opportunities)} comparison opportunities (local)")
        return opportunities

    client = get_minio_client()
    bucket_name = os.environ["MINIO_BUCKET_NAME"]

    try:
        response = client.get_object(bucket_name, COMPARISON_OPPORTUNITIES_FILE)
        data = json.loads(response.read().decode("utf-8"))
        opportunities = data.get("opportunities", [])
        logger.info(f"Loaded {len(opportunities)} comparison opportunities")
        return opportunities
    except Exception as exc:
        logger.warning(f"Failed to load comparison opportunities: {exc}")
        return []


def _find_tool_details(tool_name: str, tools_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find detailed tool information from tools database."""
    all_tools = tools_data.get("tools", [])

    # Try exact match first
    for tool in all_tools:
        if tool.get("name", "").strip().lower() == tool_name.strip().lower():
            return tool

    # Try partial match
    for tool in all_tools:
        tool_db_name = tool.get("name", "").strip().lower()
        search_name = tool_name.strip().lower()
        if search_name in tool_db_name or tool_db_name in search_name:
            logger.info(f"Partial match: '{tool_name}' -> '{tool.get('name')}'")
            return tool

    logger.warning(f"Tool '{tool_name}' not found in database")
    return None


def _generate_comparison_content(
    client: OpenAI,
    opportunity: Dict[str, Any],
    tool1_details: Optional[Dict[str, Any]],
    tool2_details: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Generate comprehensive comparison content with web search research."""

    tool1_name = opportunity.get("tool1", "")
    tool2_name = opportunity.get("tool2", "")
    category = opportunity.get("category", "AI Tools")

    # Prepare tool context
    tool1_context = "Limited information available"
    tool2_context = "Limited information available"

    if tool1_details:
        tool1_context = (
            f"Description: {tool1_details.get('description', 'N/A')}\n"
            + f"Category: {tool1_details.get('category', 'N/A')}\n"
            + f"Pricing: {tool1_details.get('pricing', 'N/A')}\n"
            + f"URL: {tool1_details.get('url', 'N/A')}"
        )

    if tool2_details:
        tool2_context = (
            f"Description: {tool2_details.get('description', 'N/A')}\n"
            + f"Category: {tool2_details.get('category', 'N/A')}\n"
            + f"Pricing: {tool2_details.get('pricing', 'N/A')}\n"
            + f"URL: {tool2_details.get('url', 'N/A')}"
        )

    system_prompt = f"""You are an expert technical writer specializing in AI tool comparisons. \
Your task is to write a comprehensive, research-backed comparison between {tool1_name} and {tool2_name}.

Use web search extensively to gather current information about:
- Pricing and subscription plans (2024-2025 rates)
- Recent user reviews and experiences
- Feature comparisons and capabilities
- Performance benchmarks and reliability
- Use case examples and best practices
- Community sentiment and adoption

Write for developers and practitioners who need to make informed decisions. \
Embed citations naturally in the text (not as footnotes).

Return valid JSON matching this structure:
{{
  "title": "Tool1 vs Tool2: Complete Comparison Guide (2025)",
  "meta_description": "SEO description under 155 characters",
  "slug": "tool1-vs-tool2",
  "overview": "2-3 paragraph executive summary highlighting key differences",
  "detailed_comparison": {{
    "pricing": "Comprehensive pricing analysis with current rates and value assessment",
    "features": "Key feature differences with specific examples and capabilities",
    "performance": "Speed, reliability, accuracy, and scalability comparison",
    "ease_of_use": "Setup process, learning curve, interface, and documentation quality",
    "use_cases": "When to choose each tool with specific scenarios and recommendations",
    "community": "Ecosystem size, support quality, documentation, and developer resources"
  }},
  "pros_cons": {{
    "tool1_pros": ["Specific advantage 1", "Specific advantage 2", "Specific advantage 3"],
    "tool1_cons": ["Specific limitation 1", "Specific limitation 2"],
    "tool2_pros": ["Specific advantage 1", "Specific advantage 2", "Specific advantage 3"],
    "tool2_cons": ["Specific limitation 1", "Specific limitation 2"]
  }},
  "verdict": "Clear recommendation with scenarios for when to choose each tool",
  "last_updated": "2025-01-01"
}}

Quality requirements:
- Minimum 1500 characters total content
- At least 2 natural citations (e.g., "According to Replicate's pricing page...")
- Current information from 2024-2025
- Specific examples and data points
- Balanced analysis of both tools"""

    user_prompt = f"""Research and write a comprehensive comparison between {tool1_name} and {tool2_name} \
in the {category} category.

{tool1_name} context:
{tool1_context}

{tool2_name} context:
{tool2_context}

Research focus areas:
1. Current pricing models and costs (2024-2025)
2. Recent user reviews and community feedback
3. Feature comparison with specific capabilities
4. Performance benchmarks and reliability data
5. Integration options and API quality
6. Documentation and developer experience
7. Enterprise vs individual use cases

Generate a comparison that helps users choose between these tools based on \
their specific needs and use cases."""

    try:
        logger.info(f"Generating comparison: {tool1_name} vs {tool2_name}")
        response = client.responses.create(
            model=COMPARISON_GENERATOR_MODEL,
            instructions=system_prompt,
            tools=[{"type": "web_search"}],
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_prompt}]}],
        )

        output_text = extract_responses_api_text(response)
        if not output_text:
            logger.warning(f"No output returned for comparison: {tool1_name} vs {tool2_name}")
            return None

        # Extract citations from API annotations before parsing JSON
        api_citations = extract_responses_api_citations(response)

        parsed = parse_json_response(output_text, context=f"comparison {tool1_name} vs {tool2_name}")
        if not parsed:
            logger.warning(f"Failed to parse comparison response: {tool1_name} vs {tool2_name}")
            return None

        # Validate content quality with citation data
        if not _validate_comparison_quality(parsed, tool1_name, tool2_name, api_citations=api_citations):
            return None

        # Count citations for storage - use same logic as validation
        # (API citations preferred, fallback to text-based counting)
        detailed = parsed.get("detailed_comparison", {})
        total_content = (
            parsed.get("overview", "") + " ".join(str(v) for v in detailed.values()) + parsed.get("verdict", "")
        )
        citation_count = count_all_citations(total_content, api_citations=api_citations)

        # Add metadata
        parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
        parsed["opportunity"] = opportunity
        parsed["citation_count"] = citation_count

        return parsed

    except Exception as exc:
        logger.error(f"Comparison generation failed for {tool1_name} vs {tool2_name}: {exc}")
        return None


def _validate_comparison_quality(
    comparison: Dict[str, Any],
    tool1: str,
    tool2: str,
    api_citations: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Apply quality gates to generated comparison content.

    Args:
        comparison: Parsed comparison data
        tool1: Name of first tool
        tool2: Name of second tool
        api_citations: Citations extracted from Responses API annotations (preferred)

    Returns:
        True if quality gates pass
    """
    # Check required fields
    required_fields = ["title", "meta_description", "overview", "detailed_comparison", "verdict"]
    for field in required_fields:
        if not comparison.get(field):
            logger.warning(f"Missing required field '{field}' in comparison: {tool1} vs {tool2}")
            return False

    # Check detailed comparison sections
    detailed = comparison.get("detailed_comparison", {})
    required_sections = ["pricing", "features", "performance", "ease_of_use", "use_cases"]
    for section in required_sections:
        if not detailed.get(section):
            logger.warning(f"Missing detailed section '{section}' in comparison: {tool1} vs {tool2}")
            return False

    # Check minimum content length
    total_content = ""
    total_content += comparison.get("overview", "")
    total_content += " ".join(detailed.values())
    total_content += comparison.get("verdict", "")

    if len(total_content) < 1500:
        logger.warning(f"Content too short ({len(total_content)} chars) for comparison: {tool1} vs {tool2}")
        return False

    # Count citations - prefer API annotations, fallback to text-based counting
    citations_found = count_all_citations(total_content, api_citations=api_citations)

    if citations_found < 2:
        logger.warning(f"Insufficient citations ({citations_found}) in comparison: {tool1} vs {tool2}")
        return False

    logger.info(
        f"Quality validation passed for comparison: {tool1} vs {tool2} "
        + f"({len(total_content)} chars, {citations_found} citations)"
    )
    return True


def _needs_comparison_generation(
    opportunity: Dict[str, Any], tools_data: Dict[str, Any], stale_after: timedelta, force: bool
) -> bool:
    """Check if a comparison needs to be generated or updated."""
    if force:
        return True

    tool1_name = opportunity.get("tool1", "")
    tool2_name = opportunity.get("tool2", "")

    # Check if comparison already exists in tools data
    all_tools = tools_data.get("tools", [])

    for tool in all_tools:
        comparisons = tool.get("comparisons", {})

        # Look for existing comparison (check both directions)
        comparison_key1 = f"{tool1_name.lower()}_vs_{tool2_name.lower()}"
        comparison_key2 = f"{tool2_name.lower()}_vs_{tool1_name.lower()}"

        existing_comparison = comparisons.get(comparison_key1) or comparisons.get(comparison_key2)

        if existing_comparison:
            generated_at = existing_comparison.get("generated_at")
            if generated_at:
                try:
                    generated_time = datetime.fromisoformat(generated_at)
                    if datetime.now(timezone.utc) - generated_time < stale_after:
                        logger.info(f"Fresh comparison exists: {tool1_name} vs {tool2_name}")
                        return False
                except ValueError:
                    pass

    return True


def _store_comparison_in_tools(
    comparison: Dict[str, Any],
    tools_data: Dict[str, Any],
    registry: Dict[str, Any],
    used_slugs: Set[str],
) -> None:
    """Store generated comparison in the tools database structure."""

    opportunity = comparison.get("opportunity", {})
    tool1_name = opportunity.get("tool1", "")
    tool2_name = opportunity.get("tool2", "")

    if not tool1_name or not tool2_name:
        logger.error("Cannot store comparison without tool names")
        return

    def find_tool(name: str) -> Optional[Dict[str, Any]]:
        for tool in tools_data.get("tools", []):
            if tool.get("name", "").strip().lower() == name.lower():
                return tool
        return None

    tool1_entry = find_tool(tool1_name)
    tool2_entry = find_tool(tool2_name)

    tool1_id = tool1_entry.get("id") if tool1_entry else tool1_name.lower()
    tool2_id = tool2_entry.get("id") if tool2_entry else tool2_name.lower()
    tool1_slug = (tool1_entry.get("slug") if tool1_entry else None) or generate_tool_slug(tool1_name)
    tool2_slug = (tool2_entry.get("slug") if tool2_entry else None) or generate_tool_slug(tool2_name)

    comparison_key = f"{tool1_name.lower().replace(' ', '_')}_vs_{tool2_name.lower().replace(' ', '_')}"
    comparison_clean = {k: v for k, v in comparison.items() if k != "opportunity"}

    base_slug = comparison_clean.get("slug") or generate_comparison_slug(
        tool1_name,
        tool2_name,
        tool1_slug=tool1_slug,
        tool2_slug=tool2_slug,
    )

    participants = {"tool1": tool1_id, "tool2": tool2_id}
    registry_key = "__".join(sorted(participants.values()))
    existing_entry = registry.get("comparisons", {}).get(registry_key, {})
    current_slug = existing_entry.get("current")
    if current_slug:
        used_slugs.discard(current_slug)

    canonical_slug = ensure_unique_slug(base_slug, used_slugs)
    comparison_clean["slug"] = canonical_slug

    last_generated = comparison_clean.get("last_generated_at") or comparison_clean.get("generated_at") or _now_iso()
    comparison_clean["last_generated_at"] = last_generated
    comparison_clean.pop("generated_at", None)

    register_comparison_slug(registry, registry_key, canonical_slug, participants=participants)

    all_tools = tools_data.get("tools", [])
    tools_updated = 0
    for tool in all_tools:
        tool_name = tool.get("name", "").strip().lower()
        if (
            tool_name == tool1_name.lower()
            or tool_name == tool2_name.lower()
            or tool1_name.lower() in tool_name
            or tool2_name.lower() in tool_name
        ):
            tool.setdefault("comparisons", {})
            # Use distinct copies to prevent shared mutations
            payload = comparison_clean if tools_updated == 0 else dict(comparison_clean)
            tool["comparisons"][comparison_key] = payload
            tool["last_reviewed_at"] = last_generated
            tool["last_indexed_at"] = last_generated
            tools_updated += 1
            logger.info(f"Added comparison to tool: {tool.get('name')}")

    if tools_updated == 0 and all_tools:
        all_tools[0].setdefault("comparisons", {})
        all_tools[0]["comparisons"][comparison_key] = dict(comparison_clean)
        all_tools[0]["last_reviewed_at"] = last_generated
        all_tools[0]["last_indexed_at"] = last_generated
        logger.info(f"Added comparison as fallback to: {all_tools[0].get('name')}")


def generate_comparisons(*, max_per_run: int, stale_days: int, dry_run: bool, force: bool) -> None:
    """Main function to generate comparison articles."""
    with pipeline_summary("comparison_generation") as summary:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Load data
        opportunities = _load_comparison_opportunities()
        tools_data = load_tools()
        registry = load_slug_registry()
        used_slugs = collect_existing_slugs(registry)
        for existing_tool in tools_data.get("tools", []):
            slug = existing_tool.get("slug")
            if slug:
                used_slugs.add(slug)
        stale_after = timedelta(days=stale_days)

        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_metric("max_per_run", max_per_run)
        summary.add_metric("stale_days", stale_days)
        summary.add_metric("opportunities_available", len(opportunities))

        if not opportunities:
            logger.warning("No comparison opportunities found. Run comparison detector first.")
            summary.add_attribute("skipped_reason", "no_opportunities")
            return

        # Process opportunities
        generated_count = 0
        skipped_count = 0
        failed_count = 0

        for i, opportunity in enumerate(opportunities):
            if generated_count >= max_per_run:
                logger.info(f"Reached max per run limit ({max_per_run}), stopping")
                break

            tool1_name = opportunity.get("tool1", "")
            tool2_name = opportunity.get("tool2", "")

            if not tool1_name or not tool2_name:
                logger.warning(f"Skipping opportunity {i+1}: missing tool names")
                skipped_count += 1
                continue

            # Check if generation is needed
            if not _needs_comparison_generation(opportunity, tools_data, stale_after, force):
                logger.info(f"Skipping fresh comparison: {tool1_name} vs {tool2_name}")
                skipped_count += 1
                continue

            # Find tool details
            tool1_details = _find_tool_details(tool1_name, tools_data)
            tool2_details = _find_tool_details(tool2_name, tools_data)

            # Generate comparison
            logger.info(
                f"Generating comparison {generated_count + 1}/{max_per_run}: " + f"{tool1_name} vs {tool2_name}"
            )

            comparison = _generate_comparison_content(client, opportunity, tool1_details, tool2_details)

            if comparison:
                if not dry_run:
                    _store_comparison_in_tools(comparison, tools_data, registry, used_slugs)
                    logger.info(f"Stored comparison: {tool1_name} vs {tool2_name}")
                else:
                    logger.info(f"Dry run: Would store comparison: {tool1_name} vs {tool2_name}")

                generated_count += 1
            else:
                logger.error(f"Failed to generate comparison: {tool1_name} vs {tool2_name}")
                failed_count += 1

        # Save updated tools data
        if generated_count > 0 and not dry_run:
            tools_data["slug_registry_version"] = 1
            save_tools(tools_data)
            save_slug_registry(registry)
            logger.info(f"Saved tools database with {generated_count} new comparisons")

        # Add metrics
        summary.add_metric("generated_count", generated_count)
        summary.add_metric("skipped_count", skipped_count)
        summary.add_metric("failed_count", failed_count)

        if generated_count > 0:
            logger.info(
                f"Comparison generation complete: {generated_count} generated, "
                + f"{skipped_count} skipped, {failed_count} failed"
            )
        else:
            logger.info("No comparisons generated - all up to date or failed")


@click.command()
@click.option(
    "--max-per-run", default=DEFAULT_MAX_PER_RUN, show_default=True, help="Maximum comparisons to generate per run"
)
@click.option(
    "--stale-days",
    default=DEFAULT_STALE_DAYS,
    show_default=True,
    help="Regenerate comparisons older than this many days",
)
@click.option("--dry-run", is_flag=True, help="Generate comparisons without saving changes")
@click.option("--force", is_flag=True, help="Force regeneration regardless of freshness")
def main(max_per_run: int, stale_days: int, dry_run: bool, force: bool) -> None:
    """Generate comprehensive AI tool comparison articles."""
    logger.info(
        "Starting comparison generation (max_per_run=%d, stale_days=%d, dry_run=%s, force=%s)",
        max_per_run,
        stale_days,
        dry_run,
        force,
    )
    generate_comparisons(max_per_run=max_per_run, stale_days=stale_days, dry_run=dry_run, force=force)


if __name__ == "__main__":
    main()
