"""Autonomous editorial loop for selecting, reviewing, enriching, and publishing tools."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Iterable
from urllib.request import Request
from urllib.request import urlopen

import click

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.data_manager import save_tools_with_retry
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_DELETE
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_KEEP
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_NEEDS_REVIEW
from ai_tools_website.v1.editorial import EDITORIAL_ACTION_NOINDEX
from ai_tools_website.v1.editorial import get_editorial_action
from ai_tools_website.v1.editorial_agent import EditorialReview
from ai_tools_website.v1.editorial_agent import apply_editorial_review
from ai_tools_website.v1.editorial_agent import resolve_editorial_client_kwargs
from ai_tools_website.v1.editorial_agent import resolve_editorial_review_model
from ai_tools_website.v1.editorial_agent import review_tool
from ai_tools_website.v1.editorial_batch import get_tool_reviewed_at
from ai_tools_website.v1.editorial_batch import normalize_requested_slugs
from ai_tools_website.v1.logging_config import setup_logging

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = 12
DEFAULT_CONTENT_MAX_PER_RUN = 6
DEFAULT_STALE_AFTER_DAYS = 30
DEFAULT_PRUNE_CONFIDENCE = 0.9
DEFAULT_CONTENT_METADATA_SOURCE = "ai-tools:content-enhancer"
DEFAULT_CONTENT_REQUEST_TIMEOUT_SECONDS = 90.0
DEFAULT_CONTENT_MAX_RETRIES = 0

HIGH_RISK_KEYWORDS = (
    "aimbot",
    "cheat",
    "exploit",
    "bypass",
    "hack",
)

GAMBLING_CONTEXT_KEYWORDS = (
    "aviator",
    "betting",
    "casino",
    "slot",
    "gambling",
)

GAMBLING_SUPPORT_KEYWORDS = (
    "predictor",
    "prediction",
)

TIER_PRIORITY = {
    "tier1": 0,
    "tier2": 1,
    "tier3": 2,
    "noindex": 3,
}

Reviewer = Callable[..., EditorialReview]
ToolsLoader = Callable[[], dict[str, Any]]
ToolsSaver = Callable[[dict[str, Any]], None]
Tierer = Callable[[list[dict[str, Any]]], Any]
ContentNeededFn = Callable[[dict[str, Any], bool], bool]
Publisher = Callable[[str], None]
CacheRefresher = Callable[[str], None]
AsyncEnhancer = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass
class LoopCandidate:
    index: int
    slug: str
    tool: dict[str, Any]
    reasons: list[str]
    tier: str
    importance_score: float


@dataclass
class EditorialLoopItemResult:
    slug: str
    reasons: list[str]
    raw_action: str | None = None
    action: str | None = None
    confidence: float | None = None
    content_action: str | None = None
    error: str | None = None


@dataclass
class EditorialLoopResult:
    selected: int = 0
    reviewed: int = 0
    updated: int = 0
    failed: int = 0
    enriched: int = 0
    content_failed: int = 0
    dry_run: bool = False
    reviewed_slugs: list[str] = field(default_factory=list)
    failed_slugs: list[str] = field(default_factory=list)
    missing_slugs: list[str] = field(default_factory=list)
    enriched_slugs: list[str] = field(default_factory=list)
    action_counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)
    items: list[EditorialLoopItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "reviewed": self.reviewed,
            "updated": self.updated,
            "failed": self.failed,
            "enriched": self.enriched,
            "content_failed": self.content_failed,
            "dry_run": self.dry_run,
            "reviewed_slugs": self.reviewed_slugs,
            "failed_slugs": self.failed_slugs,
            "missing_slugs": self.missing_slugs,
            "enriched_slugs": self.enriched_slugs,
            "action_counts": self.action_counts,
            "reason_counts": self.reason_counts,
            "items": [asdict(item) for item in self.items],
        }


class _ResponsesAdapter:
    def __init__(self, wrapped: Any, *, metadata_source: str, timeout_seconds: float):
        self._wrapped = wrapped
        self._metadata_source = metadata_source
        self._timeout_seconds = timeout_seconds

    def create(self, **kwargs):
        metadata = dict(kwargs.get("metadata") or {})
        metadata.setdefault("source", self._metadata_source)
        kwargs["metadata"] = metadata
        kwargs.setdefault("timeout", self._timeout_seconds)
        return self._wrapped.create(**kwargs)


class _ClientAdapter:
    def __init__(self, wrapped: Any, *, metadata_source: str, timeout_seconds: float):
        self.responses = _ResponsesAdapter(
            wrapped.responses,
            metadata_source=metadata_source,
            timeout_seconds=timeout_seconds,
        )


def has_explicit_editorial_review(tool: dict[str, Any]) -> bool:
    """Return whether a tool has v2 editorial data, not just legacy timestamps."""
    editorial = tool.get("editorial")
    if not isinstance(editorial, dict):
        return False

    for key in (
        "action",
        "why",
        "ideal_user",
        "not_for",
        "decision_value",
        "page_angle",
        "comparison_candidates",
        "confidence",
        "reviewed_at",
    ):
        value = editorial.get(key)
        if value not in (None, "", [], {}):
            return True
    return False


def find_suspicious_keywords(tool: dict[str, Any]) -> list[str]:
    """Return matched suspicious keywords from normalized tokens, not substrings."""
    haystacks = [
        str(tool.get("name") or "").lower(),
        str(tool.get("description") or "").lower(),
        str(tool.get("url") or "").lower(),
        " ".join(str(tag).lower() for tag in tool.get("tags") or []),
    ]
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(haystacks)))

    matches = [keyword for keyword in HIGH_RISK_KEYWORDS if keyword in tokens]
    gambling_matches = [keyword for keyword in GAMBLING_CONTEXT_KEYWORDS if keyword in tokens]
    matches.extend(gambling_matches)
    if gambling_matches:
        matches.extend(keyword for keyword in GAMBLING_SUPPORT_KEYWORDS if keyword in tokens)
    return matches


def resolve_content_metadata_source() -> str:
    return os.getenv("CONTENT_ENHANCER_METADATA_SOURCE") or DEFAULT_CONTENT_METADATA_SOURCE


def resolve_content_request_timeout_seconds() -> float:
    raw = os.getenv("CONTENT_ENHANCER_REQUEST_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_CONTENT_REQUEST_TIMEOUT_SECONDS
    return float(raw)


def resolve_content_max_retries() -> int:
    raw = os.getenv("CONTENT_ENHANCER_OPENAI_MAX_RETRIES")
    if raw is None:
        return DEFAULT_CONTENT_MAX_RETRIES
    return int(raw)


def resolve_content_client_kwargs() -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {
        "api_key": (
            os.getenv("CONTENT_ENHANCER_OPENAI_API_KEY")
            or os.getenv("EDITORIAL_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ),
        "max_retries": resolve_content_max_retries(),
    }
    base_url = (
        os.getenv("CONTENT_ENHANCER_OPENAI_BASE_URL")
        or os.getenv("EDITORIAL_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    if base_url:
        client_kwargs["base_url"] = base_url
    return client_kwargs


def _resolve_base_url() -> str:
    service_url = os.getenv("SERVICE_URL_WEB")
    if service_url:
        return service_url.rstrip("/")
    base_path = os.getenv("BASE_PATH", "").rstrip("/")
    return f"https://drose.io{base_path}".rstrip("/")


def _default_tierer(tools: list[dict[str, Any]]) -> Any:
    from ai_tools_website.v1.quality_tiers import tier_all_tools

    return tier_all_tools(tools)


def _default_content_needed(tool: dict[str, Any], force: bool) -> bool:
    if force or not tool.get("enhanced_content_v2"):
        return True

    from ai_tools_website.v1.quality_tiers import should_refresh

    return should_refresh(tool, tool.get("_tier"))


def _default_publisher(base_url: str) -> None:
    from ai_tools_website.v1.sitemap_builder import publish_sitemaps

    publish_sitemaps(base_url)


def _default_cache_refresher(base_url: str) -> None:
    request = Request(
        f"{base_url.rstrip('/')}/",
        headers={"User-Agent": "ai-tools-editorial-loop/1.0"},
    )
    with urlopen(request, timeout=20) as response:
        response.read(0)


def _selection_bucket(reasons: list[str]) -> int:
    if "requested" in reasons:
        return 0
    if "suspicious" in reasons:
        return 1
    if "needs_review" in reasons:
        return 2
    if "missing_editorial" in reasons and ("missing_content" in reasons or "stale_content" in reasons):
        return 3
    if "missing_editorial" in reasons:
        return 4
    if "missing_content" in reasons:
        return 5
    if "stale_content" in reasons:
        return 6
    if "stale_editorial" in reasons:
        return 7
    if "force" in reasons:
        return 8
    return 9


def _selection_priority(candidate: LoopCandidate) -> tuple[int, int, float, str, str]:
    tier_rank = TIER_PRIORITY.get(candidate.tier, 9)
    return (
        _selection_bucket(candidate.reasons),
        tier_rank,
        -candidate.importance_score,
        str(candidate.tool.get("name") or "").lower(),
        candidate.slug,
    )


def get_candidate_reasons(
    tool: dict[str, Any],
    *,
    now: datetime,
    stale_after_days: int,
    force: bool,
    requested: bool,
) -> list[str]:
    if requested:
        return ["requested"]

    action = get_editorial_action(tool)
    if action == EDITORIAL_ACTION_DELETE and not force:
        return []

    reasons: list[str] = []
    if action == EDITORIAL_ACTION_NEEDS_REVIEW:
        reasons.append("needs_review")
    if not has_explicit_editorial_review(tool):
        reasons.append("missing_editorial")

    reviewed_at = get_tool_reviewed_at(tool)
    if reviewed_at is None or reviewed_at <= now - timedelta(days=stale_after_days):
        reasons.append("stale_editorial")

    if find_suspicious_keywords(tool):
        reasons.append("suspicious")

    if action == EDITORIAL_ACTION_KEEP and not tool.get("enhanced_content_v2"):
        reasons.append("missing_content")

    if force and not reasons:
        reasons.append("force")

    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped


def select_tools_for_editorial_loop(
    tools: list[dict[str, Any]],
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    slugs: Iterable[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    force: bool = False,
    tierer: Tierer | None = None,
    content_needed_fn: ContentNeededFn | None = None,
    now: datetime | None = None,
) -> list[LoopCandidate]:
    if max_per_run <= 0:
        return []

    now = now or datetime.now(timezone.utc)
    tierer = tierer or _default_tierer
    content_needed_fn = content_needed_fn or _default_content_needed
    tierer(tools)

    requested_slugs = normalize_requested_slugs(slugs)
    slug_map: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, tool in enumerate(tools):
        slug = str(tool.get("slug") or "").strip().lower()
        if not slug or slug in slug_map:
            continue
        slug_map[slug] = (index, tool)

    selected: list[LoopCandidate] = []
    seen_slugs: set[str] = set()
    for requested_slug in requested_slugs:
        located = slug_map.get(requested_slug)
        if located is None:
            continue
        index, tool = located
        candidate = LoopCandidate(
            index=index,
            slug=requested_slug,
            tool=tool,
            reasons=["requested"],
            tier=str(tool.get("_tier") or "tier3"),
            importance_score=float(tool.get("_importance_score") or 0.0),
        )
        selected.append(candidate)
        seen_slugs.add(requested_slug)
        if len(selected) >= max_per_run:
            return selected

    remaining: list[LoopCandidate] = []
    for slug, (index, tool) in slug_map.items():
        if slug in seen_slugs:
            continue

        reasons = get_candidate_reasons(
            tool,
            now=now,
            stale_after_days=stale_after_days,
            force=force,
            requested=False,
        )
        if not reasons:
            continue

        if get_editorial_action(tool) == EDITORIAL_ACTION_KEEP and content_needed_fn(tool, force):
            if "missing_content" not in reasons and not tool.get("enhanced_content_v2"):
                reasons.append("missing_content")
            elif "stale_content" not in reasons and tool.get("enhanced_content_v2"):
                reasons.append("stale_content")

        remaining.append(
            LoopCandidate(
                index=index,
                slug=slug,
                tool=tool,
                reasons=reasons,
                tier=str(tool.get("_tier") or "tier3"),
                importance_score=float(tool.get("_importance_score") or 0.0),
            )
        )

    remaining.sort(key=_selection_priority)
    for candidate in remaining:
        selected.append(candidate)
        if len(selected) >= max_per_run:
            break

    return selected


def _effective_review(
    tool: dict[str, Any],
    review: EditorialReview,
    *,
    reasons: list[str],
    prune_confidence: float,
) -> EditorialReview:
    current_action = get_editorial_action(tool)
    effective_action = review.action
    if review.action in {EDITORIAL_ACTION_DELETE, EDITORIAL_ACTION_NOINDEX}:
        is_confident_prune = review.confidence >= prune_confidence or "suspicious" in reasons or "requested" in reasons
        if not is_confident_prune:
            effective_action = current_action
    elif review.action == EDITORIAL_ACTION_NEEDS_REVIEW:
        effective_action = current_action

    if effective_action == review.action:
        return review
    return review.model_copy(update={"action": effective_action})


def _build_default_enhancer() -> AsyncEnhancer:
    from openai import OpenAI

    base_client = OpenAI(**resolve_content_client_kwargs())
    client = _ClientAdapter(
        base_client,
        metadata_source=resolve_content_metadata_source(),
        timeout_seconds=resolve_content_request_timeout_seconds(),
    )

    async def _enhance(tool: dict[str, Any]) -> dict[str, Any] | None:
        from ai_tools_website.v1.content_enhancer_v2 import enhance_tool_v2
        from ai_tools_website.v1.quality_tiers import get_tier_config

        tier = str(tool.get("_tier") or "tier3")
        tier_config = get_tier_config(tier)
        if tier_config.noindex:
            return None
        return await enhance_tool_v2(client, tool, tier_config, use_llm_classifier=False)

    return _enhance


def run_editorial_loop(
    *,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    content_max_per_run: int = DEFAULT_CONTENT_MAX_PER_RUN,
    slugs: Iterable[str] | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    dry_run: bool = False,
    force: bool = False,
    use_web_search: bool = True,
    prune_confidence: float = DEFAULT_PRUNE_CONFIDENCE,
    reviewer: Reviewer | None = None,
    enhancer: AsyncEnhancer | None = None,
    loader: ToolsLoader | None = None,
    saver: ToolsSaver | None = None,
    publisher: Publisher | None = None,
    cache_refresher: CacheRefresher | None = None,
    tierer: Tierer | None = None,
    content_needed_fn: ContentNeededFn | None = None,
    now: datetime | None = None,
) -> EditorialLoopResult:
    """Run the autonomous editorial loop over the next batch of candidates."""
    now = now or datetime.now(timezone.utc)
    loader = loader or load_tools
    saver = saver or save_tools_with_retry
    publisher = publisher or _default_publisher
    cache_refresher = cache_refresher or _default_cache_refresher
    tierer = tierer or _default_tierer
    content_needed_fn = content_needed_fn or _default_content_needed
    enhancer = enhancer or _build_default_enhancer()

    tools_doc = loader()
    tools = tools_doc.setdefault("tools", [])
    requested_slugs = normalize_requested_slugs(slugs)
    available_slugs = {str(tool.get("slug") or "").strip().lower() for tool in tools if tool.get("slug")}

    result = EditorialLoopResult(dry_run=dry_run)
    result.missing_slugs = [slug for slug in requested_slugs if slug not in available_slugs]

    selected = select_tools_for_editorial_loop(
        tools,
        max_per_run=max_per_run,
        slugs=requested_slugs,
        stale_after_days=stale_after_days,
        force=force,
        tierer=tierer,
        content_needed_fn=content_needed_fn,
        now=now,
    )
    result.selected = len(selected)

    if not selected:
        logger.info("No tools selected for editorial loop")
        return result

    editorial_client = None
    if reviewer is None:
        from openai import OpenAI

        editorial_client = OpenAI(**resolve_editorial_client_kwargs())
        reviewer = lambda tool, *, model, use_web_search: review_tool(  # noqa: E731
            tool,
            client=editorial_client,
            model=model,
            use_web_search=use_web_search,
        )

    for candidate in selected:
        for reason in candidate.reasons:
            result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1

    resolved_model = resolve_editorial_review_model()

    async def _process() -> None:
        enriched_count = 0

        for candidate in selected:
            logger.info("Reviewing %s", candidate.slug)
            try:
                raw_review = reviewer(candidate.tool, model=resolved_model, use_web_search=use_web_search)
            except Exception:
                logger.exception("Editorial loop review failed for %s", candidate.slug)
                result.failed += 1
                result.failed_slugs.append(candidate.slug)
                result.items.append(
                    EditorialLoopItemResult(
                        slug=candidate.slug,
                        reasons=candidate.reasons,
                        error="review_failed",
                    )
                )
                continue

            review = _effective_review(
                candidate.tool,
                raw_review,
                reasons=candidate.reasons,
                prune_confidence=prune_confidence,
            )
            updated_tool = apply_editorial_review(
                candidate.tool,
                review,
                reviewed_at=now.isoformat(),
                model=resolved_model,
            )

            content_action = "skipped_not_keep"
            if review.action == EDITORIAL_ACTION_KEEP:
                if enriched_count >= content_max_per_run:
                    content_action = "content_cap_reached"
                elif content_needed_fn(updated_tool, force):
                    try:
                        enhanced = await enhancer(updated_tool)
                    except Exception:
                        logger.exception("Editorial loop enhancement failed for %s", candidate.slug)
                        result.content_failed += 1
                        content_action = "enhancement_failed"
                    else:
                        if enhanced:
                            updated_tool["enhanced_content_v2"] = enhanced
                            updated_tool["enhanced_at_v2"] = now.isoformat()
                            result.enriched += 1
                            result.enriched_slugs.append(candidate.slug)
                            enriched_count += 1
                            content_action = "enhanced"
                        else:
                            content_action = "no_content_generated"
                else:
                    content_action = "content_fresh"

            result.reviewed += 1
            result.updated += 1
            result.reviewed_slugs.append(candidate.slug)
            result.action_counts[review.action] = result.action_counts.get(review.action, 0) + 1
            tools[candidate.index] = updated_tool
            result.items.append(
                EditorialLoopItemResult(
                    slug=candidate.slug,
                    reasons=candidate.reasons,
                    raw_action=raw_review.action,
                    action=review.action,
                    confidence=review.confidence,
                    content_action=content_action,
                )
            )

    asyncio.run(_process())

    if result.updated and not dry_run:
        saver(tools_doc)
        base_url = _resolve_base_url()
        try:
            publisher(base_url)
        except Exception:
            logger.exception("Failed to publish sitemaps after editorial loop")
        try:
            cache_refresher(base_url)
        except Exception:
            logger.exception("Failed to refresh public cache after editorial loop")
    elif result.updated:
        logger.info("Dry run: %d tools would have been updated", result.updated)

    return result


@click.command()
@click.option("--max-per-run", default=DEFAULT_MAX_PER_RUN, show_default=True, help="Max tools to review")
@click.option(
    "--content-max-per-run",
    default=DEFAULT_CONTENT_MAX_PER_RUN,
    show_default=True,
    help="Max kept tools to enrich in one run",
)
@click.option("--slug", "slugs", multiple=True, help="Specific slug to process; repeatable")
@click.option("--stale-after-days", default=DEFAULT_STALE_AFTER_DAYS, show_default=True, help="Stale threshold")
@click.option("--dry-run", is_flag=True, help="Run without persisting changes")
@click.option("--force", is_flag=True, help="Ignore freshness gates for selected tools")
@click.option("--use-web-search/--no-web-search", default=True, show_default=True, help="Allow web search")
@click.option("--json-output", is_flag=True, help="Print structured JSON output")
def main(
    max_per_run: int,
    content_max_per_run: int,
    slugs: tuple[str, ...],
    stale_after_days: int,
    dry_run: bool,
    force: bool,
    use_web_search: bool,
    json_output: bool,
) -> None:
    setup_logging()
    result = run_editorial_loop(
        max_per_run=max_per_run,
        content_max_per_run=content_max_per_run,
        slugs=slugs,
        stale_after_days=stale_after_days,
        dry_run=dry_run,
        force=force,
        use_web_search=use_web_search,
    )
    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    click.echo(
        " ".join(
            [
                f"selected={result.selected}",
                f"reviewed={result.reviewed}",
                f"updated={result.updated}",
                f"enriched={result.enriched}",
                f"failed={result.failed}",
                f"dry_run={str(result.dry_run).lower()}",
            ]
        )
    )
    if result.action_counts:
        action_summary = ",".join(f"{action}:{count}" for action, count in sorted(result.action_counts.items()))
        click.echo(f"actions={action_summary}")


if __name__ == "__main__":
    main()
