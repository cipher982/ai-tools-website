"""Backfill canonical slugs and freshness metadata for the tools dataset."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple

import click

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.data_manager import save_tools
from ai_tools_website.v1.seo_utils import generate_category_slug
from ai_tools_website.v1.seo_utils import generate_comparison_slug
from ai_tools_website.v1.seo_utils import generate_tool_slug
from ai_tools_website.v1.slug_registry import collect_existing_slugs
from ai_tools_website.v1.slug_registry import ensure_unique_slug
from ai_tools_website.v1.slug_registry import load_slug_registry
from ai_tools_website.v1.slug_registry import register_comparison_slug
from ai_tools_website.v1.slug_registry import register_tool_slug
from ai_tools_website.v1.slug_registry import save_slug_registry

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _normalize_timestamp(value: Optional[str], default: str) -> str:
    parsed = _parse_iso_timestamp(value)
    return parsed.isoformat() if parsed else default


def _max_timestamp(values: Iterable[Optional[str]]) -> Optional[str]:
    best: Optional[datetime] = None
    for value in values:
        candidate = _parse_iso_timestamp(value)
        if not candidate:
            continue
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    return best.isoformat()


def _extract_comparison_participants(
    comparison_key: str,
    comparison_payload: Dict,
    tool_slug_lookup: Dict[str, List[Tuple[str, str]]],
    default_tool_id: str,
    default_tool_slug: str,
) -> Tuple[str, str, str, str]:
    """Determine participant tool identifiers and slugs for a comparison entry."""
    opportunity = comparison_payload.get("opportunity", {})
    tool1_name = opportunity.get("tool1") or comparison_payload.get("tool1") or ""
    tool2_name = opportunity.get("tool2") or comparison_payload.get("tool2") or ""

    if not tool1_name or not tool2_name:
        parts = comparison_key.split("_vs_")
        if len(parts) == 2:
            tool1_name = tool1_name or parts[0].replace("_", " ")
            tool2_name = tool2_name or parts[1].replace("_", " ")

    def resolve(name: str) -> Tuple[str, str]:
        candidates = tool_slug_lookup.get(name.lower())
        if candidates:
            return candidates[0]
        generated_slug = generate_tool_slug(name)
        return (name.lower() or default_tool_id, generated_slug or default_tool_slug)

    tool1_id, tool1_slug = resolve(tool1_name or default_tool_slug)
    tool2_id, tool2_slug = resolve(tool2_name or default_tool_slug)

    return tool1_id, tool1_slug, tool2_id, tool2_slug


def migrate_dataset(*, dry_run: bool) -> None:
    tools_doc = load_tools()
    tools = tools_doc.get("tools", [])

    registry = load_slug_registry()
    existing_slugs = collect_existing_slugs(registry)

    tool_slug_lookup: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    tool_slug_usage = set(existing_slugs)

    updated_tools: List[Dict] = []
    now_iso = _now_iso()

    tool_slug_by_id: Dict[str, str] = {}

    for tool in tools:
        tool_copy = dict(tool)
        tool_id = tool_copy.get("id") or str(uuid.uuid4())
        tool_copy["id"] = tool_id

        current_registry_entry = registry.get("tools", {}).get(tool_id, {})
        current_slug = current_registry_entry.get("current")
        desired_slug = tool_copy.get("slug") or current_slug or generate_tool_slug(tool_copy.get("name", ""))
        desired_slug = desired_slug or generate_tool_slug(tool_copy.get("name", ""), disambiguator=tool_id[:6])

        if current_slug:
            tool_slug_usage.discard(current_slug)
        canonical_slug = ensure_unique_slug(desired_slug, tool_slug_usage)
        tool_copy["slug"] = canonical_slug
        register_tool_slug(registry, tool_id, canonical_slug)
        tool_slug_by_id[tool_id] = canonical_slug

        name_lower = tool_copy.get("name", "").lower()
        if name_lower:
            tool_slug_lookup[name_lower].append((tool_id, canonical_slug))

        discovered_at = _normalize_timestamp(tool_copy.get("discovered_at"), now_iso)
        tool_copy["discovered_at"] = discovered_at

        last_reviewed = _normalize_timestamp(tool_copy.get("last_reviewed_at"), discovered_at)
        tool_copy["last_reviewed_at"] = last_reviewed

        enhanced_at = tool_copy.get("enhanced_at") or tool_copy.get("last_enhanced_at")
        last_enhanced = _normalize_timestamp(enhanced_at, last_reviewed)
        tool_copy["last_enhanced_at"] = last_enhanced

        tool_copy["last_indexed_at"] = _normalize_timestamp(tool_copy.get("last_indexed_at"), last_reviewed)

        comparisons = tool_copy.get("comparisons", {})
        for comp_key, comparison in list(comparisons.items()):
            comparison_copy = dict(comparison)
            tool1_id, tool1_slug, tool2_id, tool2_slug = _extract_comparison_participants(
                comp_key, comparison_copy, tool_slug_lookup, tool_id, canonical_slug
            )
            participants = {"tool1": tool1_id, "tool2": tool2_id}
            comparison_key = "__".join(sorted(participants.values()))
            registry_entry = registry.get("comparisons", {}).get(comparison_key, {})
            current_comparison_slug = registry_entry.get("current")
            if current_comparison_slug:
                tool_slug_usage.discard(current_comparison_slug)

            comparison_slug = comparison_copy.get("slug")
            if not comparison_slug:
                comparison_slug = generate_comparison_slug(
                    tool_copy.get("name", tool1_slug),
                    comparison_copy.get("title", tool2_slug),
                    tool1_slug=tool1_slug,
                    tool2_slug=tool2_slug,
                )
            comparison_slug = ensure_unique_slug(comparison_slug, tool_slug_usage)
            comparison_copy["slug"] = comparison_slug

            generated_at = comparison_copy.get("generated_at")
            comparison_copy["last_generated_at"] = _normalize_timestamp(generated_at, now_iso)

            comparisons[comp_key] = comparison_copy

            register_comparison_slug(registry, comparison_key, comparison_slug, participants=participants)

        tool_copy["comparisons"] = comparisons
        updated_tools.append(tool_copy)

    tools_doc["tools"] = updated_tools

    category_metadata: Dict[str, Dict] = {}
    for tool in updated_tools:
        category = tool.get("category", "Other")
        category_slug = generate_category_slug(category)
        category_entry = category_metadata.setdefault(
            category_slug,
            {"name": category, "slug": category_slug, "last_rebuilt_at": None},
        )

        timestamps = [
            tool.get("last_reviewed_at"),
            tool.get("last_enhanced_at"),
        ]
        for comparison in tool.get("comparisons", {}).values():
            timestamps.append(comparison.get("last_generated_at"))
        latest = _max_timestamp(timestamps)
        existing = category_entry.get("last_rebuilt_at")
        category_entry["last_rebuilt_at"] = _max_timestamp([existing, latest])

    tools_doc["category_metadata"] = category_metadata
    tools_doc["slug_registry_version"] = 1

    if dry_run:
        logger.info("Dry run completed. No changes persisted.")
        logger.info("Preview (first tool): %s", updated_tools[0] if updated_tools else {})
        return

    save_tools(tools_doc)
    save_slug_registry(registry)
    logger.info("Migration completed. Processed %d tools.", len(updated_tools))


@click.command()
@click.option("--dry-run", is_flag=True, help="Compute updates without writing to storage.")
def main(dry_run: bool) -> None:
    """CLI entrypoint for metadata backfill."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    migrate_dataset(dry_run=dry_run)


if __name__ == "__main__":
    main()
