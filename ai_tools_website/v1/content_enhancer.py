"""Generate enriched tool copy for detail pages."""

import json
import logging
import os
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

import click
from dotenv import load_dotenv
from openai import OpenAI

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .logging_utils import pipeline_summary
from .models import CONTENT_ENHANCER_MODEL

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)
# Optimized for Tier 5 OpenAI account - aggressive but smart processing
DEFAULT_MAX_PER_RUN = int(os.getenv("CONTENT_ENHANCER_MAX_PER_RUN", "200"))
DEFAULT_STALE_DAYS = int(os.getenv("CONTENT_ENHANCER_STALE_DAYS", "3"))


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
        logger.warning("Failed to parse enhanced content JSON: %s", exc)
        return None


def _build_prompt_payload(tool: Dict[str, Any]) -> str:
    summary = {
        "name": tool.get("name"),
        "url": tool.get("url"),
        "category": tool.get("category"),
        "description": tool.get("description"),
        "tags": tool.get("tags"),
        "pricing": tool.get("pricing"),
    }
    return json.dumps(summary, indent=2)


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
            elif content_type == "output_audio" and hasattr(content_item, "transcript"):
                # Fallback for models that return transcripts rather than text.
                collected.append(getattr(content_item, "transcript", ""))
    return "".join(collected)


def _generate_enhanced_content(client: OpenAI, tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call the LLM to generate enriched copy for a single tool."""
    payload = _build_prompt_payload(tool)

    system = (
        "You create succinct marketing copy for software catalog detail pages. "
        "Return only valid JSON. Keep language factual, specific, and grounded in the provided tool data. "
        "If information is unavailable, use null or empty arrays instead of inventing details."
    )
    user = (
        "You are enhancing an AI tool listing. Produce JSON matching this schema:\n"
        "{\n"
        '  "overview": {"heading": string|null, "body": string|null},\n'
        '  "key_features": {"heading": string|null, "items": [string, ...]},\n'
        '  "use_cases": {"heading": string|null, "items": [string, ...]},\n'
        '  "getting_started": {"heading": string|null, "steps": [string, ...]},\n'
        '  "pricing": {"heading": string|null, "details": string|null},\n'
        '  "limitations": {"heading": string|null, "items": [string, ...]}\n'
        "}\n\n"
        "Guidelines:\n"
        "- Default headings: Overview, Key Features, Ideal Use Cases, Getting Started, Pricing, Limitations.\n"
        "- You may adjust a heading if a better phrase improves clarity, but keep it concise.\n"
        "- Overview should be 1-2 short paragraphs.\n"
        "- Feature/use-case bullets must be <=20 words each.\n"
        "- Steps should be action-oriented and <=18 words.\n"
        "- Pricing should reflect available information or note if pricing is not disclosed.\n"
        "- Limitations are optional; include only if confidently supported by the input.\n"
        "- Never fabricate claims, numbers, or endorsements.\n"
        "- Use null or empty lists when you lack evidence.\n\n"
        f"Tool context:\n{payload}"
    )

    try:
        response = client.responses.create(
            model=CONTENT_ENHANCER_MODEL,
            instructions=system,
            tools=[{"type": "web_search"}],
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user},
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("OpenAI request failed for %s: %s", tool.get("name"), exc)
        return None

    content = _extract_output_text(response)
    if not content:
        logger.warning("No content returned for %s", tool.get("name"))
        return None

    parsed = _parse_response(content)
    if parsed is None:
        logger.warning("Skipping %s due to unparsable response", tool.get("name"))
    return parsed


def _needs_refresh(tool: Dict[str, Any], *, stale_after: timedelta, force: bool) -> bool:
    if force:
        return True

    enhanced = tool.get("enhanced_content")
    if not enhanced:
        return True

    timestamp = tool.get("enhanced_at")
    if not timestamp:
        return True

    try:
        enhanced_time = datetime.fromisoformat(timestamp)
    except ValueError:
        return True

    return datetime.now(timezone.utc) - enhanced_time >= stale_after


def _apply_defaults(section: Optional[Dict[str, Any]], default_heading: str) -> Optional[Dict[str, Any]]:
    if not section:
        return None
    heading = section.get("heading") or default_heading
    cleaned = {**section, "heading": heading}
    return cleaned


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure headings exist and strip empty content."""
    normalized: Dict[str, Any] = {}
    defaults = {
        "overview": "Overview",
        "key_features": "Key Features",
        "use_cases": "Ideal Use Cases",
        "getting_started": "Getting Started",
        "pricing": "Pricing",
        "limitations": "Limitations",
    }

    for key, default in defaults.items():
        section = payload.get(key)
        prepared = _apply_defaults(section, default)
        if not prepared:
            continue

        # Drop empty strings/lists to avoid noise
        def is_empty(value: Any) -> bool:
            return (
                value is None
                or (isinstance(value, str) and not value.strip())
                or (isinstance(value, (list, tuple)) and not value)
            )

        cleaned_section = {}
        for section_key, value in prepared.items():
            if is_empty(value):
                continue
            cleaned_section[section_key] = value

        if cleaned_section:
            normalized[key] = cleaned_section

    return normalized


def enhance_tools(*, max_per_run: int, stale_days: int, dry_run: bool, force: bool) -> None:
    with pipeline_summary("enhancement") as summary:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        tools_doc = load_tools()
        tools = tools_doc.get("tools", [])
        stale_after = timedelta(days=stale_days)

        summary.add_attribute("dry_run", dry_run)
        summary.add_attribute("force", force)
        summary.add_metric("max_per_run", max_per_run)
        summary.add_metric("stale_days", stale_days)
        summary.add_metric("total_tools", len(tools))

        updated_count = 0
        attempted = 0
        eligible = 0
        generation_failures = 0
        empty_payloads = 0

        for tool in tools:
            if updated_count >= max_per_run:
                break

            if not _needs_refresh(tool, stale_after=stale_after, force=force):
                continue

            eligible += 1
            attempted += 1
            logger.info("Enhancing tool %s (%d/%d)", tool.get("name"), attempted, max_per_run)
            enhanced = _generate_enhanced_content(client, tool)
            if not enhanced:
                generation_failures += 1
                continue

            normalized = _normalize_payload(enhanced)
            if not normalized:
                empty_payloads += 1
                logger.info("No meaningful content returned for %s", tool.get("name"))
                continue

            tool["enhanced_content"] = normalized
            tool["enhanced_at"] = datetime.now(timezone.utc).isoformat()
            updated_count += 1

        if updated_count and not dry_run:
            save_tools(tools_doc)
            logger.info("Saved enhanced content for %d tools", updated_count)
        elif updated_count:
            logger.info("Dry run: %d tools would have been updated", updated_count)
        else:
            logger.info("No tools needed enhancement")

        summary.add_metric("eligible_tools", eligible)
        summary.add_metric("attempted", attempted)
        summary.add_metric("updated", updated_count)
        summary.add_metric("generation_failures", generation_failures)
        summary.add_metric("empty_payloads", empty_payloads)


@click.command()
@click.option("--max-per-run", default=DEFAULT_MAX_PER_RUN, show_default=True, help="Maximum tools to enhance per run")
@click.option(
    "--stale-days", default=DEFAULT_STALE_DAYS, show_default=True, help="Regenerate content older than this many days"
)
@click.option("--dry-run", is_flag=True, help="Compute enhancements without persisting changes")
@click.option("--force", is_flag=True, help="Force regeneration for all tools regardless of freshness")
def main(max_per_run: int, stale_days: int, dry_run: bool, force: bool) -> None:
    """Enhance tool detail pages with richer copy."""
    logger.info(
        "Starting content enhancement (max_per_run=%d, stale_days=%d, dry_run=%s, force=%s)",
        max_per_run,
        stale_days,
        dry_run,
        force,
    )
    enhance_tools(max_per_run=max_per_run, stale_days=stale_days, dry_run=dry_run, force=force)


if __name__ == "__main__":
    main()
