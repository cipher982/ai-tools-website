"""Content Enhancer V2: Multi-source, variable-structure content generation.

This replaces the original content_enhancer.py with a more sophisticated pipeline:
1. Classify tool type (open_source, ml_model, saas, etc.)
2. Gather external data from APIs (GitHub, HuggingFace, PyPI/npm)
3. Research with web search (for tier 1-2 tools)
4. Generate variable content based on type and available data

Key differences from v1:
- Variable page structures based on tool type
- Real metrics from external APIs
- Quality tiers for budget allocation
- Sections only rendered when data is available (no "N/A")
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import click
from dotenv import load_dotenv
from openai import OpenAI

from .data_aggregators import extract_github_repo
from .data_aggregators import extract_huggingface_id
from .data_aggregators import fetch_github_stats
from .data_aggregators import fetch_huggingface_stats
from .data_aggregators import fetch_npm_stats
from .data_aggregators import fetch_pypi_stats
from .data_aggregators.package_aggregator import extract_npm_package
from .data_aggregators.package_aggregator import extract_pypi_package
from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import CONTENT_ENHANCER_MODEL
from .quality_tiers import get_tier_config
from .quality_tiers import should_refresh
from .quality_tiers import tier_all_tools
from .tool_classifier import ToolType
from .tool_classifier import classify_tool
from .tool_classifier import get_sections_for_type

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_MAX_PER_RUN = int(os.getenv("CONTENT_ENHANCER_MAX_PER_RUN", "50"))
DEFAULT_TIER = os.getenv("CONTENT_ENHANCER_TIER", "all")  # tier1, tier2, tier3, or all


def _strip_json_content(value: str) -> str:
    """Remove Markdown code fences if present."""
    value = value.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline != -1:
            value = value[first_newline + 1 :]
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def _parse_response(raw: str) -> Optional[dict[str, Any]]:
    """Safely parse JSON content from the model."""
    try:
        cleaned = _strip_json_content(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse enhanced content JSON: %s", exc)
        return None


def _extract_output_text(response: Any) -> str:
    """Best-effort extraction of text from OpenAI Responses API."""
    text = getattr(response, "output_text", "") or ""
    if text:
        return text

    output_items = getattr(response, "output", None) or []
    collected: list[str] = []
    for item in output_items:
        if getattr(item, "type", None) != "message":
            continue
        for content_item in getattr(item, "content", []) or []:
            content_type = getattr(content_item, "type", None)
            if content_type == "output_text":
                piece = getattr(content_item, "text", "")
                if piece:
                    collected.append(piece)
    return "".join(collected)


async def gather_external_data(tool: dict[str, Any]) -> dict[str, Any]:
    """Gather data from external APIs based on tool URL and type.

    Runs API calls in parallel for efficiency.
    """
    url = tool.get("url", "")
    description = tool.get("description", "")
    name = tool.get("name", "")
    tags = tool.get("tags") or []

    tasks: dict[str, Any] = {}

    # GitHub
    github_repo = extract_github_repo(url) or extract_github_repo(description)
    if not github_repo:
        for tag in tags:
            github_repo = extract_github_repo(str(tag))
            if github_repo:
                break
    if github_repo:
        owner, repo = github_repo
        tasks["github_stats"] = fetch_github_stats(owner, repo)

    # HuggingFace
    hf_ref: Optional[str] = None
    if extract_huggingface_id(url):
        hf_ref = url
    elif extract_huggingface_id(description):
        hf_ref = description
    else:
        for tag in tags:
            if extract_huggingface_id(str(tag)):
                hf_ref = str(tag)
                break
    if hf_ref:
        tasks["huggingface_stats"] = fetch_huggingface_stats(hf_ref)

    # PyPI - check URL and description for pip references
    pypi_package = extract_pypi_package(url) or extract_pypi_package(description)
    if pypi_package:
        tasks["pypi_stats"] = fetch_pypi_stats(pypi_package)

    # npm - check URL and description
    npm_package = extract_npm_package(url) or extract_npm_package(description)
    if npm_package:
        tasks["npm_stats"] = fetch_npm_stats(npm_package)

    if not tasks:
        return {}

    # Run all tasks in parallel
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    external_data = {}
    for name_key, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.debug(f"Failed to fetch {name_key} for {name}: {result}")
        elif result:
            external_data[name_key] = result

    # Derive additional signals from package metadata (common for OSS tools whose "url" is the marketing site).
    derived_tasks: dict[str, Any] = {}
    if "github_stats" not in external_data:
        pypi_stats = external_data.get("pypi_stats") or {}
        gh_url = pypi_stats.get("github_url")
        if gh_url:
            extracted = extract_github_repo(str(gh_url))
            if extracted:
                owner, repo = extracted
                derived_tasks["github_stats"] = fetch_github_stats(owner, repo)

    if "github_stats" not in external_data:
        npm_stats = external_data.get("npm_stats") or {}
        repo_url = npm_stats.get("repository")
        if repo_url:
            extracted = extract_github_repo(str(repo_url))
            if extracted:
                owner, repo = extracted
                derived_tasks["github_stats"] = fetch_github_stats(owner, repo)

    if derived_tasks:
        derived_results = await asyncio.gather(*derived_tasks.values(), return_exceptions=True)
        for name_key, result in zip(derived_tasks.keys(), derived_results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to fetch {name_key} for {name}: {result}")
            elif result:
                external_data[name_key] = result

    return external_data


def _build_section_prompts(tool_type: str, external_data: dict[str, Any]) -> dict[str, str]:
    """Build section-specific prompts based on tool type and available data."""
    prompts = {}

    if tool_type == ToolType.OPEN_SOURCE:
        github = external_data.get("github_stats")
        if github:
            prompts["github_context"] = (
                f"GitHub Stats: {github.get('stars', 0):,} stars, "
                f"{github.get('forks', 0):,} forks, "
                f"{github.get('contributors', 'unknown')} contributors, "
                f"License: {github.get('license', 'unknown')}, "
                f"Last commit: {github.get('last_commit', {}).get('date', 'unknown')}"
            )
            prompts["installation_hint"] = "Include actual installation commands if known"

    elif tool_type == ToolType.ML_MODEL:
        hf = external_data.get("huggingface_stats")
        if hf:
            prompts["model_context"] = (
                f"HuggingFace Stats: {hf.get('downloads', 0):,} downloads, "
                f"{hf.get('likes', 0)} likes, "
                f"Pipeline: {hf.get('pipeline_tag', 'unknown')}, "
                f"Parameters: {hf.get('parameters_human', 'unknown')}"
            )
            model_card = hf.get("model_card", {})
            if model_card:
                prompts["model_card_hint"] = (
                    f"License: {model_card.get('license', 'unknown')}, "
                    f"Base model: {model_card.get('base_model', 'unknown')}"
                )

    elif tool_type == ToolType.SAAS_COMMERCIAL:
        prompts["pricing_hint"] = (
            "Research current pricing tiers. If pricing info is found, include specific amounts. "
            "If not found after research, omit the pricing section entirely rather than saying 'not disclosed'."
        )

    return prompts


def _build_variable_schema(tool_type: str, external_data: dict[str, Any]) -> str:
    """Build a JSON schema string that varies by tool type and available data."""
    sections = get_sections_for_type(tool_type)

    schema_parts = []

    for section in sections:
        if section == "overview":
            schema_parts.append('"overview": {"body": "2-3 paragraph overview of the tool"}')

        elif section == "github_stats" and external_data.get("github_stats"):
            # We'll inject real data, just need interpretation
            schema_parts.append('"github_analysis": {"body": "Brief analysis of GitHub activity and community health"}')

        elif section == "model_card" and external_data.get("huggingface_stats"):
            schema_parts.append(
                '"model_details": {"body": "Technical overview of the model architecture and capabilities"}'
            )

        elif section == "installation":
            schema_parts.append(
                '"installation": {"package_manager": "pip|npm|brew|docker", "commands": ["command1", "command2"]}'
            )

        elif section == "key_features":
            schema_parts.append('"key_features": {"items": ["feature1", "feature2", "feature3"]}')

        elif section == "use_cases":
            schema_parts.append('"use_cases": {"items": ["use case 1", "use case 2", "use case 3"]}')

        elif section == "benchmarks":
            schema_parts.append('"benchmarks": {"metrics": [{"name": "metric", "value": "score", "source": "url"}]}')

        elif section == "usage_examples":
            schema_parts.append('"code_example": {"language": "python", "code": "example code"}')

        elif section == "pricing_tiers":
            schema_parts.append(
                '"pricing": {"tiers": [{"name": "Free", "price": "$0", "features": ["..."]}], '
                '"notes": "any pricing notes"}'
            )

        elif section == "pricing":
            schema_parts.append('"pricing": {"summary": "pricing summary if known, null if unknown"}')

        elif section == "alternatives":
            schema_parts.append('"alternatives": {"tools": ["alt1", "alt2"], "comparison_notes": "brief notes"}')

        elif section == "api_overview":
            schema_parts.append(
                '"api_overview": {"auth_method": "API key|OAuth|None", '
                '"base_url": "if known", "rate_limits": "if known"}'
            )

        elif section == "code_examples":
            schema_parts.append(
                '"code_examples": {"python": "example", "curl": "example", "javascript": "example or null"}'
            )

        elif section == "community":
            schema_parts.append('"community": {"summary": "community engagement summary"}')

        elif section == "recent_news":
            # We don't generate news - it comes from Tavily search
            pass

    return "{\n  " + ",\n  ".join(schema_parts) + "\n}"


def _generate_enhanced_content_v2(
    client: OpenAI,
    tool: dict[str, Any],
    classification: dict[str, Any],
    external_data: dict[str, Any],
    tier_config: Any,
) -> Optional[dict[str, Any]]:
    """Generate enhanced content using the research agent pattern."""
    tool_type = classification["type"]
    tool_name = tool.get("name", "Unknown")

    # Build context from external data
    section_prompts = _build_section_prompts(tool_type, external_data)
    schema = _build_variable_schema(tool_type, external_data)

    # Build tool context
    tool_context = {
        "name": tool.get("name"),
        "url": tool.get("url"),
        "category": tool.get("category"),
        "description": tool.get("description"),
        "tags": tool.get("tags"),
        "pricing": tool.get("pricing"),
    }

    # Add external data context
    extra_context = "\n".join(f"- {k}: {v}" for k, v in section_prompts.items())

    system_prompt = f"""You are an expert technical writer creating content for an AI tools directory.
Your task is to write comprehensive, accurate content for {tool_name}.

Tool Type: {tool_type}
This determines which sections to include and how to frame the content.

External Data Available:
{extra_context if extra_context else "No external data fetched"}

Guidelines:
- Write factual, specific content based on research
- Include real metrics and data points when available
- Cite sources naturally in the text (e.g., "According to the GitHub repository...")
- IMPORTANT: If you cannot find specific information (like pricing), return null for that field
- Do NOT invent features, metrics, or pricing
- Keep language professional but accessible
- Each feature/use case bullet should be <=25 words

Return valid JSON matching this schema:
{schema}

Quality requirements:
- Overview should be 150-300 words
- Include at least 3-5 key features
- Use specific examples, not generic descriptions"""

    user_prompt = f"""Research and write content for this AI tool:

{json.dumps(tool_context, indent=2)}

Use web search to find:
1. Current features and capabilities
2. Recent updates or news
3. Pricing information (if commercial)
4. User reviews or community feedback
5. Technical specifications

Generate comprehensive content following the schema provided."""

    # Determine if we should use web search based on tier
    use_web_search = tier_config.web_searches > 0

    try:
        if use_web_search:
            response = client.responses.create(
                model=CONTENT_ENHANCER_MODEL,
                instructions=system_prompt,
                tools=[{"type": "web_search"}],
                input=[{"role": "user", "content": [{"type": "input_text", "text": user_prompt}]}],
            )
        else:
            # No web search for tier 3 - use basic completion
            response = client.responses.create(
                model=CONTENT_ENHANCER_MODEL,
                instructions=system_prompt,
                input=[{"role": "user", "content": [{"type": "input_text", "text": user_prompt}]}],
            )
    except Exception as exc:
        logger.error(f"OpenAI request failed for {tool_name}: {exc}")
        return None

    content = _extract_output_text(response)
    if not content:
        logger.warning(f"No content returned for {tool_name}")
        return None

    parsed = _parse_response(content)
    if not parsed:
        logger.warning(f"Failed to parse response for {tool_name}")
        return None

    # Inject external data directly (not generated)
    if external_data.get("github_stats"):
        gh = external_data["github_stats"]
        full_name = gh.get("full_name")
        if full_name:
            github_url = f"https://github.com/{full_name}"
        else:
            owner = gh.get("owner")
            repo = gh.get("repo")
            github_url = f"https://github.com/{owner}/{repo}" if owner and repo else None
        parsed["github_stats"] = {
            "url": github_url,
            "stars": gh.get("stars"),
            "forks": gh.get("forks"),
            "open_issues": gh.get("open_issues"),
            "contributors": gh.get("contributors"),
            "license": gh.get("license"),
            "last_commit": gh.get("last_commit", {}).get("date"),
            "language": gh.get("language"),
            "latest_release": gh.get("latest_release", {}).get("tag"),
        }

    if external_data.get("huggingface_stats"):
        hf = external_data["huggingface_stats"]
        hf_id = hf.get("id")
        hf_type = hf.get("type")
        hf_url = None
        if hf_id and hf_type == "space":
            hf_url = f"https://huggingface.co/spaces/{hf_id}"
        elif hf_id and hf_type == "dataset":
            hf_url = f"https://huggingface.co/datasets/{hf_id}"
        elif hf_id:
            hf_url = f"https://huggingface.co/{hf_id}"
        parsed["huggingface_stats"] = {
            "url": hf_url,
            "downloads": hf.get("downloads"),
            "likes": hf.get("likes"),
            "pipeline_tag": hf.get("pipeline_tag"),
            "parameters": hf.get("parameters_human"),
            "model_card": hf.get("model_card"),
        }

    if external_data.get("pypi_stats"):
        pypi = external_data["pypi_stats"]
        package_name = pypi.get("name")
        package_url = pypi.get("package_url") or (f"https://pypi.org/project/{package_name}/" if package_name else None)
        parsed["pypi_stats"] = {
            "package_url": package_url,
            "version": pypi.get("version"),
            "downloads": pypi.get("downloads"),
            "requires_python": pypi.get("requires_python"),
        }

    if external_data.get("npm_stats"):
        npm = external_data["npm_stats"]
        package_name = npm.get("name")
        package_url = npm.get("package_url") or (
            f"https://www.npmjs.com/package/{package_name}" if package_name else None
        )
        parsed["npm_stats"] = {
            "package_url": package_url,
            "version": npm.get("version"),
            "downloads": npm.get("downloads"),
        }

    return parsed


async def enhance_tool_v2(
    client: OpenAI,
    tool: dict[str, Any],
    tier_config: Any,
) -> Optional[dict[str, Any]]:
    """Full enhancement pipeline for a single tool."""
    tool_name = tool.get("name", "Unknown")

    # Step 1: Classify the tool
    classification = classify_tool(tool)
    logger.info(f"Classified {tool_name} as {classification['type']} (confidence: {classification['confidence']})")

    # Step 2: Gather external data
    external_data = await gather_external_data(tool)
    if external_data:
        logger.info(f"Gathered external data for {tool_name}: {list(external_data.keys())}")

    # Step 3: Generate content
    enhanced = _generate_enhanced_content_v2(client, tool, classification, external_data, tier_config)

    if not enhanced:
        return None

    # Add metadata
    enhanced["tool_type"] = classification["type"]
    enhanced["classification_confidence"] = classification["confidence"]
    enhanced["tier"] = tier_config.name
    enhanced["generated_at"] = datetime.now(timezone.utc).isoformat()
    enhanced["data_sources"] = list(external_data.keys())

    return enhanced


def enhance_tools_v2(
    *,
    max_per_run: int,
    target_tier: str,
    dry_run: bool,
    force: bool,
) -> None:
    """Main function to run the v2 enhancement pipeline."""
    with pipeline_summary("enhancement_v2") as summary:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        tools_doc = load_tools()
        tools = tools_doc.get("tools", [])

        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_attribute("target_tier", target_tier)
        summary.add_metric("max_per_run", max_per_run)
        summary.add_metric("total_tools", len(tools))

        # Tier all tools
        tiered = tier_all_tools(tools)

        # Determine which tools to process
        if target_tier == "all":
            target_tools = tiered["tier1"] + tiered["tier2"] + tiered["tier3"]
        else:
            target_tools = tiered.get(target_tier, [])

        logger.info(f"Processing {len(target_tools)} tools in {target_tier}")

        updated_count = 0
        skipped_count = 0
        failed_count = 0

        for tool in target_tools:
            if updated_count >= max_per_run:
                break

            tool_name = tool.get("name", "Unknown")
            tier = tool.get("_tier", "tier3")

            # Check if refresh needed (unless forcing)
            if not force and not should_refresh(tool, tier):
                skipped_count += 1
                continue

            tier_config = get_tier_config(tier)

            # Skip noindex tools
            if tier_config.noindex:
                skipped_count += 1
                continue

            logger.info(f"Enhancing {tool_name} (tier: {tier})")

            # Run async enhancement
            try:
                enhanced = asyncio.run(enhance_tool_v2(client, tool, tier_config))
            except Exception as exc:
                logger.error(f"Enhancement failed for {tool_name}: {exc}")
                failed_count += 1
                continue

            if not enhanced:
                failed_count += 1
                continue

            # Store enhanced content
            tool["enhanced_content_v2"] = enhanced
            tool["enhanced_at_v2"] = datetime.now(timezone.utc).isoformat()
            updated_count += 1

        if updated_count and not dry_run:
            save_tools(tools_doc)
            logger.info(f"Saved enhanced content for {updated_count} tools")
        elif updated_count:
            logger.info(f"Dry run: {updated_count} tools would have been updated")
        else:
            logger.info("No tools needed enhancement")

        summary.add_metric("updated", updated_count)
        summary.add_metric("skipped", skipped_count)
        summary.add_metric("failed", failed_count)


@click.command()
@click.option("--max-per-run", default=DEFAULT_MAX_PER_RUN, show_default=True, help="Max tools to enhance per run")
@click.option("--tier", default=DEFAULT_TIER, show_default=True, help="Target tier: tier1, tier2, tier3, or all")
@click.option("--dry-run", is_flag=True, help="Compute without persisting changes")
@click.option("--force", is_flag=True, help="Force regeneration regardless of freshness")
def main(max_per_run: int, tier: str, dry_run: bool, force: bool) -> None:
    """Enhance tool pages with V2 pipeline (multi-source, variable structure)."""
    logger.info(
        f"Starting content enhancement V2 (max_per_run={max_per_run}, tier={tier}, dry_run={dry_run}, force={force})"
    )
    enhance_tools_v2(max_per_run=max_per_run, target_tier=tier, dry_run=dry_run, force=force)


if __name__ == "__main__":
    main()
