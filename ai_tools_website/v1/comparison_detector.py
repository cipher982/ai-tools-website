"""Detect high-value AI tool comparison opportunities."""

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

import click
from dotenv import load_dotenv
from openai import OpenAI

from .data_manager import get_minio_client
from .data_manager import load_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import COMPARISON_DETECTOR_MODEL

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_MAX_COMPARISONS = int(os.getenv("COMPARISON_DETECTOR_MAX_COMPARISONS", "50"))
DEFAULT_STALE_DAYS = int(os.getenv("COMPARISON_DETECTOR_STALE_DAYS", "30"))
COMPARISON_OPPORTUNITIES_FILE = "comparison_opportunities.json"


def _strip_json_content(value: str) -> str:
    """Remove Markdown code fences if present before json loading."""
    value = value.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline != -1:
            value = value[first_newline + 1 :]
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
    """Safely parse JSON content from the model."""
    try:
        cleaned = _strip_json_content(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse comparison detection JSON: %s", exc)
        return None


def _extract_output_text(response: Any) -> str:
    """Best-effort extraction of text from a Responses API payload."""
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


def _prepare_tool_batch(tools: List[Dict[str, Any]], batch_size: int = 12) -> List[List[Dict[str, Any]]]:
    """Prepare tools in batches for analysis."""
    batches = []
    for i in range(0, len(tools), batch_size):
        batch = []
        for tool in tools[i : i + batch_size]:
            # Create concise tool summary for analysis
            summary = {
                "name": tool.get("name"),
                "category": tool.get("category"),
                "description": tool.get("description", "")[:200],  # Limit description length
                "tags": tool.get("tags", [])[:3],  # First 3 tags only
                "pricing": tool.get("pricing", ""),
                "url": tool.get("url", ""),
            }
            batch.append(summary)
        batches.append(batch)
    return batches


def _detect_comparisons_batch(
    client: OpenAI, tools_batch: List[Dict[str, Any]], max_comparisons: int
) -> Optional[List[Dict[str, Any]]]:
    """Analyze a batch of tools to identify comparison opportunities."""

    system_prompt = """You are an AI tool comparison analyst. Your job is to identify the most valuable \
comparison opportunities from a batch of AI tools.

Analyze the provided tools and identify comparison opportunities that would:
- Generate significant search traffic (people actually search "Tool A vs Tool B")
- Help users make real purchasing/adoption decisions
- Cover tools that serve similar purposes but with different approaches
- Focus on popular, well-known tools when possible

Return ONLY valid JSON in this exact format:
{
  "comparisons": [
    {
      "tool1": "Exact Tool Name 1",
      "tool2": "Exact Tool Name 2",
      "rationale": "Brief explanation of why this comparison is valuable",
      "category": "primary category these tools serve",
      "search_potential": "high|medium|low",
      "value_score": 1-10
    }
  ]
}

Quality requirements:
- Only suggest comparisons with value_score >= 6
- Focus on "high" or "medium" search_potential only
- Rationale must be at least 50 characters
- Be very selective - quality over quantity"""

    user_prompt = f"""Analyze this batch of AI tools and identify high-value comparison opportunities:

{json.dumps(tools_batch, indent=2)}

Target the TOP comparison opportunities from this batch. Focus on tools that users would \
realistically compare when making decisions."""

    try:
        response = client.responses.create(
            model=COMPARISON_DETECTOR_MODEL,
            instructions=system_prompt,
            tools=[{"type": "web_search"}],
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_prompt}]}],
        )

        output_text = _extract_output_text(response)
        if not output_text:
            logger.warning("No output returned for batch analysis")
            return None

        parsed = _parse_response(output_text)
        if not parsed:
            logger.warning("Failed to parse batch analysis response")
            return None

        # Validate and filter comparisons
        comparisons = parsed.get("comparisons", [])
        valid_comparisons = []

        for comp in comparisons:
            # Apply quality gates
            value_score = comp.get("value_score", 0)
            search_potential = comp.get("search_potential", "low")
            rationale = comp.get("rationale", "")

            if (
                value_score >= 6
                and search_potential in ["high", "medium"]
                and len(rationale) >= 50
                and comp.get("tool1")
                and comp.get("tool2")
            ):
                valid_comparisons.append(comp)

        logger.info(f"Batch analysis: {len(comparisons)} detected, {len(valid_comparisons)} passed quality gates")
        return valid_comparisons

    except Exception as exc:
        logger.error("Batch comparison detection failed: %s", exc)
        return None


def _load_existing_opportunities() -> Dict[str, Any]:
    """Load existing comparison opportunities from MinIO."""
    client = get_minio_client()
    bucket_name = os.environ["MINIO_BUCKET_NAME"]

    try:
        response = client.get_object(bucket_name, COMPARISON_OPPORTUNITIES_FILE)
        data = json.loads(response.read().decode("utf-8"))
        logger.info(f"Loaded existing opportunities: {len(data.get('opportunities', []))} comparisons")
        return data
    except Exception:
        logger.info("No existing opportunities found, starting fresh")
        return {
            "opportunities": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"total_tools_analyzed": 0, "total_comparisons_detected": 0},
        }


def _save_opportunities(opportunities_data: Dict[str, Any]) -> None:
    """Save comparison opportunities to MinIO."""
    client = get_minio_client()
    bucket_name = os.environ["MINIO_BUCKET_NAME"]

    try:
        from io import BytesIO

        json_data = json.dumps(opportunities_data, indent=2).encode("utf-8")
        client.put_object(
            bucket_name,
            COMPARISON_OPPORTUNITIES_FILE,
            BytesIO(json_data),
            len(json_data),
            content_type="application/json",
        )
        logger.info(f"Saved {len(opportunities_data.get('opportunities', []))} opportunities to MinIO")
    except Exception as exc:
        logger.error(f"Failed to save opportunities: {exc}")
        raise


def _needs_refresh(opportunities_data: Dict[str, Any], *, stale_after: timedelta, force: bool) -> bool:
    """Check if opportunities need refresh based on age."""
    if force:
        return True

    generated_at = opportunities_data.get("generated_at")
    if not generated_at:
        return True

    try:
        generated_time = datetime.fromisoformat(generated_at)
        return datetime.now(timezone.utc) - generated_time >= stale_after
    except ValueError:
        return True


def detect_comparison_opportunities(*, max_comparisons: int, stale_days: int, dry_run: bool, force: bool) -> None:
    """Main function to detect comparison opportunities."""
    with pipeline_summary("comparison_detection") as summary:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Load existing opportunities
        opportunities_data = _load_existing_opportunities()
        stale_after = timedelta(days=stale_days)

        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_metric("max_comparisons", max_comparisons)
        summary.add_metric("stale_days", stale_days)

        # Check if refresh is needed
        if not _needs_refresh(opportunities_data, stale_after=stale_after, force=force):
            existing_count = len(opportunities_data.get("opportunities", []))
            logger.info(f"Opportunities are fresh ({existing_count} comparisons), skipping detection")
            summary.add_metric("existing_opportunities", existing_count)
            summary.add_attribute("skipped_reason", "not_stale")
            return

        # Load and prepare tools for analysis
        tools_doc = load_tools()
        all_tools = tools_doc.get("tools", [])

        # Filter tools with good descriptions for better analysis
        quality_tools = []
        for tool in all_tools:
            description = tool.get("description", "")
            name = tool.get("name", "")
            if len(description) > 50 and len(name) > 0:
                quality_tools.append(tool)

        summary.add_metric("total_tools", len(all_tools))
        summary.add_metric("quality_tools", len(quality_tools))

        # Prepare batches
        tool_batches = _prepare_tool_batch(quality_tools)
        summary.add_metric("tool_batches", len(tool_batches))

        # Analyze batches to detect opportunities
        all_opportunities = []
        batches_processed = 0
        api_failures = 0

        for i, batch in enumerate(tool_batches):
            logger.info(f"Analyzing batch {i+1}/{len(tool_batches)} ({len(batch)} tools)")

            batch_opportunities = _detect_comparisons_batch(client, batch, max_comparisons)
            if batch_opportunities:
                all_opportunities.extend(batch_opportunities)
                logger.info(f"Batch {i+1} found {len(batch_opportunities)} opportunities")
            else:
                api_failures += 1
                logger.warning(f"Batch {i+1} analysis failed")

            batches_processed += 1

            # Stop if we have enough high-quality opportunities
            if len(all_opportunities) >= max_comparisons:
                logger.info(f"Reached target of {max_comparisons} opportunities, stopping")
                break

        # Deduplicate and rank opportunities
        unique_opportunities = []
        seen_pairs = set()

        # Sort by value_score descending
        all_opportunities.sort(key=lambda x: x.get("value_score", 0), reverse=True)

        for opp in all_opportunities:
            tool1 = opp.get("tool1", "").strip()
            tool2 = opp.get("tool2", "").strip()

            # Create normalized pair key (alphabetical order)
            pair_key = tuple(sorted([tool1.lower(), tool2.lower()]))

            if pair_key not in seen_pairs and len(unique_opportunities) < max_comparisons:
                seen_pairs.add(pair_key)
                unique_opportunities.append(opp)

        # Update opportunities data
        opportunities_data.update(
            {
                "opportunities": unique_opportunities,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "total_tools_analyzed": len(quality_tools),
                    "total_comparisons_detected": len(all_opportunities),
                    "unique_comparisons": len(unique_opportunities),
                    "batches_processed": batches_processed,
                    "api_failures": api_failures,
                },
            }
        )

        # Save results
        if not dry_run:
            _save_opportunities(opportunities_data)
            logger.info(f"Detection complete: {len(unique_opportunities)} unique opportunities saved")
        else:
            logger.info(f"Dry run: {len(unique_opportunities)} opportunities would be saved")

        # Add metrics to summary
        summary.add_metric("opportunities_detected", len(all_opportunities))
        summary.add_metric("unique_opportunities", len(unique_opportunities))
        summary.add_metric("batches_processed", batches_processed)
        summary.add_metric("api_failures", api_failures)


@click.command()
@click.option(
    "--max-comparisons",
    default=DEFAULT_MAX_COMPARISONS,
    show_default=True,
    help="Maximum comparison opportunities to detect",
)
@click.option(
    "--stale-days",
    default=DEFAULT_STALE_DAYS,
    show_default=True,
    help="Regenerate opportunities older than this many days",
)
@click.option("--dry-run", is_flag=True, help="Analyze opportunities without saving changes")
@click.option("--force", is_flag=True, help="Force regeneration regardless of freshness")
def main(max_comparisons: int, stale_days: int, dry_run: bool, force: bool) -> None:
    """Detect high-value AI tool comparison opportunities."""
    logger.info(
        "Starting comparison detection (max_comparisons=%d, stale_days=%d, dry_run=%s, force=%s)",
        max_comparisons,
        stale_days,
        dry_run,
        force,
    )
    detect_comparison_opportunities(
        max_comparisons=max_comparisons, stale_days=stale_days, dry_run=dry_run, force=force
    )


if __name__ == "__main__":
    main()
