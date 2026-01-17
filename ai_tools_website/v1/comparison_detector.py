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
from typing import Literal
from typing import Optional

import click
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .data_manager import get_minio_client
from .data_manager import load_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import COMPARISON_DETECTOR_MODEL
from .openai_utils import extract_responses_api_text
from .openai_utils import parse_json_response
from .storage import local_comparison_opportunities_path
from .storage import read_local_json
from .storage import use_local_storage
from .storage import write_local_json


# Pydantic models for structured outputs
class ComparisonOpportunity(BaseModel):
    """A single comparison opportunity detected by the model."""

    model_config = ConfigDict(extra="forbid")

    tool1: str = Field(description="Exact name of the first tool")
    tool2: str = Field(description="Exact name of the second tool")
    rationale: str = Field(min_length=50, description="Brief explanation of why this comparison is valuable")
    category: str = Field(description="Primary category these tools serve")
    search_potential: Literal["high", "medium", "low"] = Field(description="Search traffic potential")
    value_score: int = Field(ge=1, le=10, description="Quality score from 1-10")


class DetectionResult(BaseModel):
    """Complete detection result from the model."""

    model_config = ConfigDict(extra="forbid")

    comparisons: List[ComparisonOpportunity] = Field(description="List of comparison opportunities")


load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_MAX_COMPARISONS = int(os.getenv("COMPARISON_DETECTOR_MAX_COMPARISONS", "50"))
DEFAULT_STALE_DAYS = int(os.getenv("COMPARISON_DETECTOR_STALE_DAYS", "30"))
COMPARISON_OPPORTUNITIES_FILE = "comparison_opportunities.json"

# Quality gate thresholds
MIN_VALUE_SCORE = 6  # Minimum value_score for comparison to pass quality gates
MIN_RATIONALE_LENGTH = 50  # Minimum characters for rationale field
VALID_SEARCH_POTENTIALS = ("high", "medium")  # Accepted search_potential values

# Batch processing settings
DEFAULT_BATCH_SIZE = 12  # Tools per batch for LLM analysis
DESCRIPTION_PREVIEW_LENGTH = 200  # Max chars of description in batch summaries
MAX_TAGS_IN_BATCH = 3  # Max tags to include in batch summaries


def _prepare_tool_batch(
    tools: List[Dict[str, Any]], batch_size: int = DEFAULT_BATCH_SIZE
) -> List[List[Dict[str, Any]]]:
    """Prepare tools in batches for analysis."""
    batches = []
    for i in range(0, len(tools), batch_size):
        batch = []
        for tool in tools[i : i + batch_size]:
            # Create concise tool summary for analysis
            summary = {
                "name": tool.get("name"),
                "category": tool.get("category"),
                "description": tool.get("description", "")[:DESCRIPTION_PREVIEW_LENGTH],
                "tags": tool.get("tags", [])[:MAX_TAGS_IN_BATCH],
                "pricing": tool.get("pricing", ""),
                "url": tool.get("url", ""),
            }
            batch.append(summary)
        batches.append(batch)
    return batches


def _detect_comparisons_batch(
    client: OpenAI, tools_batch: List[Dict[str, Any]], max_comparisons: int
) -> Optional[List[Dict[str, Any]]]:
    """Analyze a batch of tools to identify comparison opportunities.

    Uses structured outputs via Responses API for reliable JSON parsing.
    Falls back to manual parsing if structured output fails.
    """
    system_prompt = """You are an AI tool comparison analyst. Your job is to identify the most valuable \
comparison opportunities from a batch of AI tools.

Analyze the provided tools and identify comparison opportunities that would:
- Generate significant search traffic (people actually search "Tool A vs Tool B")
- Help users make real purchasing/adoption decisions
- Cover tools that serve similar purposes but with different approaches
- Focus on popular, well-known tools when possible

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
        # Use structured outputs with JSON schema
        response = client.responses.create(
            model=COMPARISON_DETECTOR_MODEL,
            instructions=system_prompt,
            tools=[{"type": "web_search"}],
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_prompt}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "detection_result",
                    "strict": True,
                    "schema": DetectionResult.model_json_schema(),
                }
            },
        )

        output_text = extract_responses_api_text(response)
        if not output_text:
            logger.warning("No output returned for batch analysis")
            return None

        # Try structured parsing first
        try:
            result = DetectionResult.model_validate_json(output_text)
            comparisons = [c.model_dump() for c in result.comparisons]
        except Exception as parse_exc:
            logger.warning(f"Structured parse failed: {parse_exc}, falling back to manual")
            # Fallback to manual JSON parsing
            parsed = parse_json_response(output_text, context="batch comparison detection")
            if not parsed:
                return None
            comparisons = parsed.get("comparisons", [])

        # Filter by quality gates (Pydantic handles validation, but we still apply score filters)
        valid_comparisons = []
        for comp in comparisons:
            value_score = comp.get("value_score", 0)
            search_potential = comp.get("search_potential", "low")
            rationale = comp.get("rationale", "")

            if (
                value_score >= MIN_VALUE_SCORE
                and search_potential in VALID_SEARCH_POTENTIALS
                and len(rationale) >= MIN_RATIONALE_LENGTH
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
    if use_local_storage():
        path = local_comparison_opportunities_path(COMPARISON_OPPORTUNITIES_FILE)
        if not path.exists():
            logger.info("No existing local opportunities found, starting fresh")
            return {
                "opportunities": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"total_tools_analyzed": 0, "total_comparisons_detected": 0},
            }
        data = read_local_json(
            path,
            {
                "opportunities": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {"total_tools_analyzed": 0, "total_comparisons_detected": 0},
            },
        )
        logger.info(f"Loaded existing opportunities: {len(data.get('opportunities', []))} comparisons (local)")
        return data

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
    if use_local_storage():
        path = local_comparison_opportunities_path(COMPARISON_OPPORTUNITIES_FILE)
        write_local_json(path, opportunities_data)
        logger.info(
            "Saved %d opportunities to local storage",
            len(opportunities_data.get("opportunities", [])),
        )
        return

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
