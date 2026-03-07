"""Batch editorial review runner for v2 triage and refresh flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Callable
from typing import Iterable

import click

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.data_manager import save_tools_with_retry
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_DELETE
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_NEEDS_REVIEW
from ai_tools_website.v1.editorial import get_editorial_action
from ai_tools_website.v1.editorial_agent import EditorialReview
from ai_tools_website.v1.editorial_agent import apply_editorial_review
from ai_tools_website.v1.editorial_agent import resolve_editorial_review_model
from ai_tools_website.v1.editorial_agent import review_tool
from ai_tools_website.v1.logging_config import setup_logging

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = 25
DEFAULT_STALE_AFTER_DAYS = 30

Reviewer = Callable[..., EditorialReview]
ToolsLoader = Callable[[], dict[str, Any]]
ToolsSaver = Callable[[dict[str, Any]], None]


@dataclass
class SelectedTool:
    index: int
    slug: str
    tool: dict[str, Any]


@dataclass
class EditorialBatchResult:
    selected: int = 0
    reviewed: int = 0
    updated: int = 0
    failed: int = 0
    dry_run: bool = False
    reviewed_slugs: list[str] = field(default_factory=list)
    failed_slugs: list[str] = field(default_factory=list)
    missing_slugs: list[str] = field(default_factory=list)
    action_counts: dict[str, int] = field(default_factory=dict)


def normalize_requested_slugs(slugs: Iterable[str] | None) -> list[str]:
    """Normalize and deduplicate requested slugs while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for slug in slugs or []:
        candidate = slug.strip().lower()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def parse_reviewed_at(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp into UTC."""
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_tool_reviewed_at(tool: dict[str, Any]) -> datetime | None:
    """Get the best available editorial review timestamp for a tool."""
    editorial = tool.get("editorial")
    if isinstance(editorial, dict):
        reviewed_at = parse_reviewed_at(editorial.get("reviewed_at"))
        if reviewed_at is not None:
            return reviewed_at
    return parse_reviewed_at(tool.get("last_reviewed_at"))


def needs_editorial_review(
    tool: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    force: bool = False,
) -> bool:
    """Return whether a tool should be included in the next batch review."""
    action = get_editorial_action(tool)
    if action == EDITORIAL_ACTION_DELETE and not force:
        return False

    if force:
        return True

    if action == EDITORIAL_ACTION_NEEDS_REVIEW:
        return True

    reviewed_at = get_tool_reviewed_at(tool)
    if reviewed_at is None:
        return True

    now = now or datetime.now(timezone.utc)
    return reviewed_at <= now - timedelta(days=stale_after_days)


def _selection_priority(
    tool: dict[str, Any],
    *,
    now: datetime,
    stale_after_days: int,
) -> tuple[int, datetime, str, str]:
    action = get_editorial_action(tool)
    reviewed_at = get_tool_reviewed_at(tool)

    if action == EDITORIAL_ACTION_NEEDS_REVIEW:
        bucket = 0
    elif reviewed_at is None:
        bucket = 1
    elif reviewed_at <= now - timedelta(days=stale_after_days):
        bucket = 2
    else:
        bucket = 3

    sort_time = reviewed_at or datetime.min.replace(tzinfo=timezone.utc)
    return (
        bucket,
        sort_time,
        str(tool.get("name") or "").lower(),
        str(tool.get("slug") or "").lower(),
    )


def select_tools_for_editorial_review(
    tools: list[dict[str, Any]],
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    slugs: Iterable[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    force: bool = False,
    now: datetime | None = None,
) -> list[SelectedTool]:
    """Pick the next tools to review, with explicit slugs first."""
    if max_per_run <= 0:
        return []

    now = now or datetime.now(timezone.utc)
    requested_slugs = normalize_requested_slugs(slugs)
    slug_map: dict[str, SelectedTool] = {}
    for index, tool in enumerate(tools):
        slug = str(tool.get("slug") or "").strip().lower()
        if not slug or slug in slug_map:
            continue
        slug_map[slug] = SelectedTool(index=index, slug=slug, tool=tool)

    selected: list[SelectedTool] = []
    seen_slugs: set[str] = set()

    for slug in requested_slugs:
        candidate = slug_map.get(slug)
        if candidate is None or slug in seen_slugs:
            continue
        selected.append(candidate)
        seen_slugs.add(slug)
        if len(selected) >= max_per_run:
            return selected

    remaining: list[SelectedTool] = []
    for slug, candidate in slug_map.items():
        if slug in seen_slugs:
            continue
        if not needs_editorial_review(
            candidate.tool,
            now=now,
            stale_after_days=stale_after_days,
            force=force,
        ):
            continue
        remaining.append(candidate)

    remaining.sort(
        key=lambda candidate: _selection_priority(
            candidate.tool,
            now=now,
            stale_after_days=stale_after_days,
        )
    )
    for candidate in remaining:
        selected.append(candidate)
        if len(selected) >= max_per_run:
            break

    return selected


def run_editorial_review_batch(
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    slugs: Iterable[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    dry_run: bool = False,
    force: bool = False,
    use_web_search: bool = True,
    model: str | None = None,
    reviewer: Reviewer | None = None,
    loader: ToolsLoader | None = None,
    saver: ToolsSaver | None = None,
    now: datetime | None = None,
) -> EditorialBatchResult:
    """Run a bounded batch of editorial reviews and persist results."""
    now = now or datetime.now(timezone.utc)
    reviewer = reviewer or review_tool
    loader = loader or load_tools
    saver = saver or save_tools_with_retry
    tools_doc = loader()
    tools = tools_doc.setdefault("tools", [])
    requested_slugs = normalize_requested_slugs(slugs)
    available_slugs = {str(tool.get("slug") or "").strip().lower() for tool in tools if tool.get("slug")}

    result = EditorialBatchResult(dry_run=dry_run)
    result.missing_slugs = [slug for slug in requested_slugs if slug not in available_slugs]

    selected = select_tools_for_editorial_review(
        tools,
        max_per_run=max_per_run,
        slugs=requested_slugs,
        stale_after_days=stale_after_days,
        force=force,
        now=now,
    )
    result.selected = len(selected)

    if result.missing_slugs:
        logger.warning("Requested slugs not found: %s", ", ".join(result.missing_slugs))
    if not selected:
        logger.info("No tools selected for editorial review")
        return result

    resolved_model = model
    action_counts: dict[str, int] = {}

    for candidate in selected:
        logger.info("Reviewing %s", candidate.slug)
        try:
            if resolved_model is None:
                resolved_model = resolve_editorial_review_model()
            review = reviewer(candidate.tool, model=resolved_model, use_web_search=use_web_search)
        except Exception:
            logger.exception("Editorial review failed for %s", candidate.slug)
            result.failed += 1
            result.failed_slugs.append(candidate.slug)
            continue

        updated_tool = apply_editorial_review(candidate.tool, review, reviewed_at=now.isoformat(), model=resolved_model)
        result.reviewed += 1
        result.reviewed_slugs.append(candidate.slug)
        result.updated += 1
        action_counts[review.action] = action_counts.get(review.action, 0) + 1
        tools[candidate.index] = updated_tool

    result.action_counts = action_counts

    if result.updated and not dry_run:
        saver(tools_doc)
        logger.info("Saved editorial reviews for %d tools", result.updated)
    elif result.updated:
        logger.info("Dry run: %d tools would have been updated", result.updated)

    return result


@click.command()
@click.option("--max-per-run", default=DEFAULT_MAX_PER_RUN, show_default=True, help="Max tools to review")
@click.option("--slug", "slugs", multiple=True, help="Specific slug to review; repeatable")
@click.option("--stale-after-days", default=DEFAULT_STALE_AFTER_DAYS, show_default=True, help="Re-review age threshold")
@click.option("--dry-run", is_flag=True, help="Review without persisting changes")
@click.option("--force", is_flag=True, help="Review selected candidates even if they are fresh")
@click.option("--use-web-search/--no-web-search", default=True, show_default=True, help="Allow web search")
def main(
    max_per_run: int,
    slugs: tuple[str, ...],
    stale_after_days: int,
    dry_run: bool,
    force: bool,
    use_web_search: bool,
) -> None:
    """Review a bounded batch of tool pages for v2 editorial decisions."""
    setup_logging()
    result = run_editorial_review_batch(
        max_per_run=max_per_run,
        slugs=slugs,
        stale_after_days=stale_after_days,
        dry_run=dry_run,
        force=force,
        use_web_search=use_web_search,
    )

    click.echo(
        " ".join(
            [
                f"selected={result.selected}",
                f"reviewed={result.reviewed}",
                f"updated={result.updated}",
                f"failed={result.failed}",
                f"dry_run={str(result.dry_run).lower()}",
            ]
        )
    )
    if result.missing_slugs:
        click.echo(f"missing={','.join(result.missing_slugs)}")
    if result.action_counts:
        action_summary = ",".join(f"{action}:{count}" for action, count in sorted(result.action_counts.items()))
        click.echo(f"actions={action_summary}")


if __name__ == "__main__":
    main()
