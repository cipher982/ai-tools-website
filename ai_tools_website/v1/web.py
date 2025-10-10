import asyncio
import json
import logging
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import List

from dotenv import load_dotenv
from fasthtml.common import H1
from fasthtml.common import H2
from fasthtml.common import H3
from fasthtml.common import H5
from fasthtml.common import A
from fasthtml.common import Body
from fasthtml.common import Div
from fasthtml.common import Head
from fasthtml.common import Html
from fasthtml.common import Img
from fasthtml.common import Input
from fasthtml.common import Li
from fasthtml.common import Meta
from fasthtml.common import P
from fasthtml.common import Script
from fasthtml.common import Section
from fasthtml.common import Span
from fasthtml.common import Style
from fasthtml.common import StyleX
from fasthtml.common import Title
from fasthtml.common import Ul
from fasthtml.fastapp import fast_app

from ai_tools_website.v1.cron_utils import calculate_next_run
from ai_tools_website.v1.cron_utils import get_cron_schedules
from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.logging_config import setup_logging
from ai_tools_website.v1.pipeline_analytics import calculate_health_score
from ai_tools_website.v1.pipeline_analytics import filter_outcome_metrics
from ai_tools_website.v1.pipeline_analytics import generate_insights
from ai_tools_website.v1.pipeline_analytics import get_contextual_summary
from ai_tools_website.v1.pipeline_analytics import render_progress_bar
from ai_tools_website.v1.pipeline_analytics import render_sparkline
from ai_tools_website.v1.pipeline_db import get_latest_pipeline_status
from ai_tools_website.v1.seo_utils import generate_breadcrumb_list
from ai_tools_website.v1.seo_utils import generate_category_slug
from ai_tools_website.v1.seo_utils import generate_meta_description
from ai_tools_website.v1.seo_utils import generate_meta_title
from ai_tools_website.v1.seo_utils import generate_product_schema
from ai_tools_website.v1.seo_utils import generate_tool_slug

load_dotenv()
setup_logging()

# Base path for subdirectory deployment
BASE_PATH = os.getenv("BASE_PATH", "").rstrip("/")

# Simple global cache
tools_cache: Dict = {}
logger = logging.getLogger(__name__)


def url(path: str) -> str:
    """Prefix path with BASE_PATH for subdirectory deployment"""
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{BASE_PATH}{path}"


def get_tools_by_category() -> Dict:
    """Get tools from cache, initialize if empty"""
    if not tools_cache:
        logger.info("Cache empty, loading tools from disk")
        tools = load_tools()
        by_category = {}
        for tool in tools["tools"]:
            category = tool.get("category", "Other")
            by_category.setdefault(category, []).append(tool)
        tools_cache.update(by_category)
        logger.info(f"Loaded {sum(len(tools) for tools in by_category.values())} tools into cache")
    return tools_cache


async def refresh_tools_background():
    """Background task to refresh tools cache"""
    logger.info("Starting background cache refresh")
    tools = load_tools()
    by_category = {}
    for tool in tools["tools"]:
        category = tool.get("category", "Other")
        by_category.setdefault(category, []).append(tool)
    tools_cache.clear()
    tools_cache.update(by_category)
    logger.info(f"Background refresh complete, cached {sum(len(tools) for tools in by_category.values())} tools")


def get_all_tools() -> list:
    """Get flat list of all tools"""
    tools_by_category = get_tools_by_category()
    all_tools = []
    for tools in tools_by_category.values():
        all_tools.extend(tools)
    return all_tools


def find_tool_by_slug(slug: str) -> dict:
    """Find tool by its generated slug"""
    all_tools = get_all_tools()
    for tool in all_tools:
        if generate_tool_slug(tool["name"]) == slug:
            return tool
    return None


def get_tools_for_category(category_slug: str) -> list:
    """Get tools for a specific category by slug"""
    tools_by_category = get_tools_by_category()
    for category, tools in tools_by_category.items():
        if generate_category_slug(category) == category_slug:
            return tools, category
    return [], None


def find_comparison_by_slug(slug: str) -> tuple[dict, str, str]:
    """Find comparison by its generated slug (tool1-vs-tool2)"""
    all_tools = get_all_tools()

    # Parse slug to extract tool names
    if "-vs-" not in slug:
        return None, None, None

    parts = slug.split("-vs-")
    if len(parts) != 2:
        return None, None, None

    tool1_slug, tool2_slug = parts

    # Convert slugs to the format used in DB keys (replace hyphens with underscores)
    tool1_key = tool1_slug.replace("-", "_")
    tool2_key = tool2_slug.replace("-", "_")

    # Search for comparisons in all tools
    for tool in all_tools:
        comparisons = tool.get("comparisons", {})
        for comp_key, comparison in comparisons.items():
            # Check if this comparison matches the slug (both directions)
            if comp_key == f"{tool1_key}_vs_{tool2_key}" or comp_key == f"{tool2_key}_vs_{tool1_key}":
                # Extract tool names from the comparison (fallback to parsing from key if opportunity is empty)
                opportunity = comparison.get("opportunity", {})
                tool1_name = opportunity.get("tool1", "")
                tool2_name = opportunity.get("tool2", "")

                # If opportunity is empty, try to extract from comparison title or generate from key
                if not tool1_name or not tool2_name:
                    title = comparison.get("title", "")
                    if " vs " in title:
                        parts = title.split(" vs ")
                        if len(parts) >= 2:
                            tool1_name = parts[0]
                            tool2_name = parts[1].split(":")[0]  # Remove subtitle after colon

                # Final fallback: generate from slug
                if not tool1_name or not tool2_name:
                    tool1_name = tool1_slug.replace("-", " ").title()
                    tool2_name = tool2_slug.replace("-", " ").title()

                return comparison, tool1_name, tool2_name

    return None, None, None


def get_all_comparisons() -> list:
    """Get all available comparisons across all tools"""
    all_tools = get_all_tools()
    comparisons = []
    seen_keys = set()

    for tool in all_tools:
        tool_comparisons = tool.get("comparisons", {})
        for comp_key, comparison in tool_comparisons.items():
            if comp_key not in seen_keys:
                seen_keys.add(comp_key)

                # Extract metadata - try opportunity first, then fallback to title parsing
                opportunity = comparison.get("opportunity", {})
                tool1_name = opportunity.get("tool1", "")
                tool2_name = opportunity.get("tool2", "")

                # If opportunity is empty, try to extract from title
                if not tool1_name or not tool2_name:
                    title = comparison.get("title", "")
                    if " vs " in title:
                        parts = title.split(" vs ")
                        if len(parts) >= 2:
                            tool1_name = parts[0]
                            tool2_name = parts[1].split(":")[0]  # Remove subtitle after colon

                # Final fallback: extract from comparison key
                if not tool1_name or not tool2_name:
                    if "_vs_" in comp_key:
                        key_parts = comp_key.split("_vs_")
                        if len(key_parts) == 2:
                            tool1_name = key_parts[0].replace("_", " ").title()
                            tool2_name = key_parts[1].replace("_", " ").title()

                if tool1_name and tool2_name:
                    # Generate slug for the comparison
                    comp_slug = f"{generate_tool_slug(tool1_name)}-vs-{generate_tool_slug(tool2_name)}"

                    comparisons.append(
                        {
                            "slug": comp_slug,
                            "tool1_name": tool1_name,
                            "tool2_name": tool2_name,
                            "title": comparison.get("title", f"{tool1_name} vs {tool2_name}"),
                            "meta_description": comparison.get("meta_description", ""),
                            "last_updated": comparison.get("last_updated", ""),
                        }
                    )

    return comparisons


def get_base_url() -> str:
    """Get base URL for the site"""
    # For subdirectory deployment, construct from domain + base path
    return os.getenv("SERVICE_URL_WEB", f"https://drose.io{BASE_PATH}")


def render_tool_sections(tool: dict) -> list:
    """Create enhanced content blocks for a tool detail page."""
    enhanced = tool.get("enhanced_content") or {}
    blocks = []

    overview = enhanced.get("overview")
    if overview and overview.get("body"):
        blocks.append(H2(overview.get("heading", "Overview")))
        blocks.append(P(overview["body"]))
    else:
        blocks.append(H2("Overview"))
        blocks.append(P(tool.get("description", "")))

    features = enhanced.get("key_features") or {}
    feature_items = features.get("items") or []
    if feature_items:
        blocks.append(H3(features.get("heading", "Key Features")))
        blocks.append(Ul(*[Li(item) for item in feature_items]))

    use_cases = enhanced.get("use_cases") or {}
    use_case_items = use_cases.get("items") or []
    if use_case_items:
        blocks.append(H3(use_cases.get("heading", "Ideal Use Cases")))
        blocks.append(Ul(*[Li(item) for item in use_case_items]))

    getting_started = enhanced.get("getting_started") or {}
    steps = getting_started.get("steps") or []
    if steps:
        blocks.append(H3(getting_started.get("heading", "Getting Started")))
        blocks.append(Ul(*[Li(step) for step in steps]))

    pricing = enhanced.get("pricing") or {}
    if pricing.get("details"):
        blocks.append(H3(pricing.get("heading", "Pricing")))
        blocks.append(P(pricing["details"]))

    limitations = enhanced.get("limitations") or {}
    limitation_items = limitations.get("items") or []
    if limitation_items:
        blocks.append(H3(limitations.get("heading", "Limitations")))
        blocks.append(Ul(*[Li(item) for item in limitation_items]))

    return blocks


def render_comparison_sections(comparison: dict, tool1_name: str, tool2_name: str) -> list:
    """Create content blocks for a comparison page."""
    blocks = []

    # Overview section
    overview = comparison.get("overview", "")
    if overview:
        blocks.append(H2("Overview"))
        blocks.append(P(overview))

    # Detailed comparison sections
    detailed = comparison.get("detailed_comparison", {})

    # Pricing section
    pricing = detailed.get("pricing", "")
    if pricing:
        blocks.append(H2("Pricing Comparison"))
        blocks.append(P(pricing))

    # Features section
    features = detailed.get("features", "")
    if features:
        blocks.append(H2("Feature Comparison"))
        blocks.append(P(features))

    # Performance section
    performance = detailed.get("performance", "")
    if performance:
        blocks.append(H2("Performance & Reliability"))
        blocks.append(P(performance))

    # Ease of use section
    ease_of_use = detailed.get("ease_of_use", "")
    if ease_of_use:
        blocks.append(H2("Ease of Use"))
        blocks.append(P(ease_of_use))

    # Use cases section
    use_cases = detailed.get("use_cases", "")
    if use_cases:
        blocks.append(H2("Use Cases & Recommendations"))
        blocks.append(P(use_cases))

    # Pros and cons section
    pros_cons = comparison.get("pros_cons", {})
    if pros_cons:
        blocks.append(H2("Pros & Cons"))

        tool1_pros = pros_cons.get("tool1_pros", [])
        tool1_cons = pros_cons.get("tool1_cons", [])
        tool2_pros = pros_cons.get("tool2_pros", [])
        tool2_cons = pros_cons.get("tool2_cons", [])

        if tool1_pros or tool1_cons:
            blocks.append(H3(f"{tool1_name}"))
            if tool1_pros:
                blocks.append(H5("Pros:"))
                blocks.append(Ul(*[Li(pro) for pro in tool1_pros]))
            if tool1_cons:
                blocks.append(H5("Cons:"))
                blocks.append(Ul(*[Li(con) for con in tool1_cons]))

        if tool2_pros or tool2_cons:
            blocks.append(H3(f"{tool2_name}"))
            if tool2_pros:
                blocks.append(H5("Pros:"))
                blocks.append(Ul(*[Li(pro) for pro in tool2_pros]))
            if tool2_cons:
                blocks.append(H5("Cons:"))
                blocks.append(Ul(*[Li(con) for con in tool2_cons]))

    # Community section
    community = detailed.get("community", "")
    if community:
        blocks.append(H2("Community & Support"))
        blocks.append(P(community))

    # Verdict section
    verdict = comparison.get("verdict", "")
    if verdict:
        blocks.append(H2("Final Verdict"))
        blocks.append(P(verdict))

    return blocks


def _build_enhanced_pipeline_data() -> List[Dict]:
    """Build enhanced pipeline data with analytics and visual elements."""
    from datetime import datetime
    from datetime import timedelta
    from datetime import timezone

    # Get latest pipeline runs from database
    latest_runs = get_latest_pipeline_status()
    db_pipelines = {run["pipeline"]: run for run in latest_runs}

    # Get cron schedules for next run calculations
    cron_schedules = get_cron_schedules()
    now = datetime.now(timezone.utc)

    enhanced_pipelines = []

    for pipeline in ["discovery", "maintenance", "enhancement"]:
        run = db_pipelines.get(pipeline)

        # Calculate health metrics and insights
        health = calculate_health_score(pipeline, days=7)
        insights = generate_insights(pipeline, health)
        contextual_summary = get_contextual_summary(pipeline, days=1)

        # Handle maintenance special case
        if pipeline == "maintenance":
            discovery_run = db_pipelines.get("discovery")
            if discovery_run and discovery_run.get("status") == "success":
                # Show as successful with discovery timing
                enhanced_pipelines.append(
                    {
                        "pipeline": "maintenance",
                        "status": "success",
                        "started_at": discovery_run.get("started_at"),
                        "finished_at": discovery_run.get("finished_at"),
                        "duration_seconds": discovery_run.get("duration_seconds"),
                        "schedule_display": "Auto after discovery",
                        "next_run_display": "Follows discovery",
                        "health_score": health["score"],
                        "health_status": health["status"],
                        "contextual_summary": contextual_summary,
                        "insights": insights,
                        "sparkline": render_sparkline(health.get("durations", [])),
                        "progress_bar": render_progress_bar(health["score"]),
                        "filtered_metrics": {"Triggered automatically": "After discovery completes"},
                    }
                )
            else:
                enhanced_pipelines.append(
                    {
                        "pipeline": "maintenance",
                        "status": "pending",
                        "schedule_display": "Auto after discovery",
                        "next_run_display": "Follows discovery",
                        "health_score": health["score"],
                        "health_status": health["status"],
                        "contextual_summary": contextual_summary,
                        "insights": insights or ["Waiting for discovery"],
                        "filtered_metrics": {},
                    }
                )
            continue

        if run:
            # Pipeline has execution history
            # Check if stale (older than 6 hours)
            finished_at = run.get("finished_at")
            stale = False
            if finished_at:
                try:
                    finished_dt = datetime.fromisoformat(finished_at)
                    if now - finished_dt > timedelta(hours=6):
                        stale = True
                except ValueError:
                    pass

            # Calculate next run info
            cron_expr = cron_schedules.get(pipeline)
            next_run_info = calculate_next_run(cron_expr) if cron_expr else {}

            # Filter metrics to remove config pollution
            filtered_metrics = filter_outcome_metrics(pipeline, run.get("metrics", {}))

            enhanced_pipelines.append(
                {
                    "pipeline": run["pipeline"],
                    "status": run["status"],
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "duration_seconds": run.get("duration_seconds"),
                    "stale": stale,
                    "schedule_display": cron_expr or "Unknown",
                    "next_run_display": next_run_info.get("next_run_in", "—"),
                    "health_score": health["score"],
                    "health_status": health["status"],
                    "contextual_summary": contextual_summary,
                    "insights": insights,
                    "sparkline": render_sparkline(health.get("durations", [])),
                    "progress_bar": render_progress_bar(health["score"]),
                    "filtered_metrics": filtered_metrics,
                    "error_type": run.get("error_type"),
                    "error_note": run.get("error_note"),
                }
            )
        else:
            # Pipeline has never run
            cron_expr = cron_schedules.get(pipeline)
            next_run_info = calculate_next_run(cron_expr) if cron_expr else {}

            enhanced_pipelines.append(
                {
                    "pipeline": pipeline,
                    "status": "missing",
                    "schedule_display": cron_expr or "Unknown",
                    "next_run_display": next_run_info.get("next_run_in", "—"),
                    "health_score": 0,
                    "health_status": "unknown",
                    "contextual_summary": "Never executed",
                    "insights": ["No execution history"],
                    "filtered_metrics": {},
                }
            )

    return enhanced_pipelines


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# Components
def tool_card(tool):
    """Tool card component that links to internal tool page"""
    tool_slug = generate_tool_slug(tool["name"])
    return A(
        {"href": url(f"/tools/{tool_slug}"), "_class": "tool-card"},
        H5(tool["name"]),
        P(tool["description"]),
        **{"data-search": f"{tool['name'].lower()} {tool['description'].lower()}"},
    )


def tool_card_external(tool):
    """Tool card component that links to external URL (for homepage)"""
    return A(
        {"href": tool["url"], "target": "_blank", "_class": "tool-card"},
        H5(tool["name"]),
        P(tool["description"]),
        **{"data-search": f"{tool['name'].lower()} {tool['description'].lower()}"},
    )


def category_section(name, tools, use_internal_links=False):
    """Category section with configurable linking"""
    cards = []
    for t in tools:
        if use_internal_links:
            cards.append(tool_card(t))
        else:
            cards.append(tool_card_external(t))

    category_slug = generate_category_slug(name)
    category_link = A(name, href=url(f"/category/{category_slug}"))

    return Section(
        H2(category_link if use_internal_links else name),
        Span(f"{len(tools)} tools", _class="count"),
        Div(*cards, _class="tools-grid"),
        _class="category",
    )


# App setup
app, rt = fast_app(static_path=str(Path(__file__).parent / "static"))


status_styles = Style(
    """
    /* Pipeline Dashboard - Consistent with Main Page Styling */

    /* Pipeline grid layout */
    .pipeline-grid {
        display: grid;
        gap: var(--spacing-md);
        grid-template-columns: repeat(3, 1fr);
        margin-top: var(--spacing-lg);
    }

    /* Pipeline cards as Windows 98 dialog boxes */
    .pipeline-card {
        background: var(--win98-face);
        border: var(--border-raised);
        border-color: var(--border-raised-color);
        padding: 0;
        position: relative;
        min-height: 200px;
        box-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
    }

    /* Title bars with health status colors */
    .pipeline-title-bar {
        background: linear-gradient(90deg, var(--win98-active-title) 0%, var(--win98-accent) 100%);
        color: var(--win98-text-light);
        padding: var(--spacing-sm) var(--spacing-md);
        font-weight: bold;
        border: 1px solid var(--win98-border);
        margin: 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 11px;
    }

    /* Health status title bar colors */
    .health-excellent .pipeline-title-bar {
        background: linear-gradient(90deg, #006400 0%, #008000 100%);
    }
    .health-healthy .pipeline-title-bar {
        background: linear-gradient(90deg, #006400 0%, #008000 100%);
    }
    .health-degraded .pipeline-title-bar {
        background: linear-gradient(90deg, #B8860B 0%, #DAA520 100%);
    }
    .health-critical .pipeline-title-bar {
        background: linear-gradient(90deg, #8B0000 0%, #DC143C 100%);
    }
    .health-unknown .pipeline-title-bar {
        background: linear-gradient(90deg, var(--win98-inactive-title) 0%, var(--win98-shadow) 100%);
    }

    .pipeline-title-bar h2 {
        margin: 0;
        font-size: 11px;
        font-weight: bold;
    }

    .health-status-row {
        display: flex;
        align-items: center;
        gap: var(--spacing-xs);
    }

    .health-indicator {
        font-size: 11px;
    }

    .progress-visual {
        font-family: monospace;
        font-size: 10px;
    }

    /* Content area */
    .pipeline-content {
        padding: var(--spacing-md);
    }

    /* Info sections styled like Windows controls */
    .pipeline-info-panel {
        background: var(--win98-button-face);
        border: var(--border-sunken);
        border-color: var(--border-sunken-color);
        padding: var(--spacing-sm);
        margin-bottom: var(--spacing-sm);
        font-size: 11px;
    }

    .schedule-info {
        margin: 0;
        font-weight: bold;
        color: var(--win98-text);
    }

    .next-run-info {
        margin: var(--spacing-xs) 0 0 0;
        color: var(--win98-accent);
    }

    .trend-info {
        margin: var(--spacing-xs) 0 0 0;
        font-family: monospace;
    }

    .context-summary {
        margin: var(--spacing-xs) 0 0 0;
        font-weight: bold;
    }

    /* Status messages styled as Windows message boxes */
    .pipeline-insight {
        margin: var(--spacing-sm) 0;
        padding: var(--spacing-sm);
        font-size: 11px;
        border: var(--border-raised);
        border-color: var(--border-raised-color);
        background: var(--win98-face);
    }

    .insight-normal {
        color: var(--win98-text);
    }

    .insight-warning {
        background: var(--win98-button-face);
        color: var(--win98-text);
    }

    .insight-critical {
        background: var(--win98-button-face);
        color: var(--win98-text);
        border-color: var(--border-button-pressed);
    }

    /* Metrics in Windows list style */
    .metrics-section-title {
        margin: var(--spacing-sm) 0 var(--spacing-xs) 0;
        font-size: 11px;
        font-weight: bold;
        color: var(--win98-text);
    }

    .pipeline-metrics-list {
        margin: 0;
        padding: 0;
        list-style: none;
        font-size: 11px;
        background: var(--win98-text-light);
        border: var(--border-sunken);
        border-color: var(--border-sunken-color);
        padding: var(--spacing-xs);
    }

    .pipeline-metrics-list li {
        display: flex;
        justify-content: space-between;
        margin: 1px 0;
        padding: 1px var(--spacing-xs);
    }

    .pipeline-metric-value {
        font-weight: bold;
        color: var(--win98-accent);
    }

    /* Navigation */
    .pipeline-back-link {
        color: var(--win98-accent);
        text-decoration: none;
        font-size: 11px;
        margin-bottom: var(--spacing-md);
        display: inline-block;
    }

    .pipeline-back-link:hover {
        text-decoration: underline;
    }

    .pipeline-timestamp {
        font-size: 11px;
        color: var(--win98-shadow);
        margin-top: var(--spacing-lg);
        text-align: center;
        padding: var(--spacing-sm);
        background: var(--win98-button-face);
        border: var(--border-sunken);
        border-color: var(--border-sunken-color);
    }

    /* Responsive - stack on mobile */
    @media (max-width: 768px) {
        .pipeline-grid {
            grid-template-columns: 1fr;
        }
    }
    """
)


@rt("/pipeline-status")
async def pipeline_status():
    """Modern pipeline dashboard with operational intelligence."""

    # Get enhanced pipeline data with analytics
    enhanced_pipelines = _build_enhanced_pipeline_data()
    now = datetime.now(timezone.utc)

    cards = []
    if not enhanced_pipelines:
        cards.append(Div(P("No pipeline data available."), _class="pipeline-card status-missing"))
    else:
        for pipeline in enhanced_pipelines:
            pipeline_name = pipeline["pipeline"].replace("_", " ").title()
            status = pipeline["status"]
            health_status = pipeline.get("health_status", "unknown")

            # Health status emoji
            health_emoji = {"excellent": "✅", "healthy": "✅", "degraded": "⚠️", "critical": "❌", "unknown": "❓"}.get(
                health_status, "❓"
            )

            # Build card classes
            card_classes = ["pipeline-card", f"status-{status}", f"health-{health_status}"]
            if pipeline.get("stale"):
                card_classes.append("status-stale")

            # Title bar with health indicator (Windows 98 style)
            title_bar = Div(
                H2(f"{pipeline_name} Pipeline"),
                Div(
                    Span(f"{health_emoji} {health_status.title()}", _class="health-indicator"),
                    Span(pipeline.get("progress_bar", ""), _class="progress-visual"),
                    _class="health-status-row",
                ),
                _class="pipeline-title-bar",
            )

            # Performance summary with sparkline (Windows control style)
            sparkline = pipeline.get("sparkline", "")
            summary_components = [
                P(f"{pipeline.get('schedule_display', 'Unknown schedule')}", _class="schedule-info"),
                P(f"Next: {pipeline.get('next_run_display', '—')}", _class="next-run-info"),
            ]

            if sparkline and sparkline != "─" * 12:
                summary_components.append(P(f"Trend: {sparkline} (last 10 runs)", _class="trend-info"))

            # Contextual summary
            context_summary = pipeline.get("contextual_summary", "")
            if context_summary and context_summary != "Never executed":
                summary_components.append(P(context_summary, _class="context-summary"))

            info_panel = Div(*summary_components, _class="pipeline-info-panel")

            # Insights as Windows message boxes
            insights = pipeline.get("insights", [])
            insight_components = []
            for insight in insights[:2]:  # Limit to 2 most important
                if insight:
                    # Classify insight type by content
                    if insight.startswith(("✅", "⚡ Performance improving")):
                        css_class = "pipeline-insight insight-normal"
                    elif insight.startswith(("⚠️", "⏱️")):
                        css_class = "pipeline-insight insight-warning"
                    elif insight.startswith(("🚨", "🔥", "❌")):
                        css_class = "pipeline-insight insight-critical"
                    else:
                        css_class = "pipeline-insight insight-normal"

                    insight_components.append(Div(insight, _class=css_class))

            # Filtered metrics as Windows list box
            metrics = pipeline.get("filtered_metrics", {})
            metric_components = []
            if metrics and len(metrics) > 0:
                metric_items = []
                for key, value in sorted(metrics.items()):
                    if str(value).isdigit() or isinstance(value, (int, float)):
                        metric_items.append(
                            Li(
                                Span(key),
                                Span(str(value), _class="pipeline-metric-value"),
                            )
                        )
                if metric_items:
                    metric_components = [
                        H3("Key Metrics", _class="metrics-section-title"),
                        Ul(*metric_items, _class="pipeline-metrics-list"),
                    ]

            # Combine content in proper Windows dialog structure
            card_content = [
                title_bar,
                Div(
                    info_panel,
                    *insight_components,
                    *metric_components,
                    _class="pipeline-content",
                ),
            ]

            cards.append(Div(*card_content, _class=" ".join(card_classes)))

    # Main window layout matching homepage structure
    content = Div(
        A("← Back", href=url("/"), _class="pipeline-back-link"),
        H1("Pipeline Monitor", _class="window-title"),
        P("Automated job status with performance metrics and diagnostics.", _class="intro"),
        Div(*cards, _class="pipeline-grid"),
        Div(f"Last Updated: {_format_timestamp(now.isoformat())}", _class="pipeline-timestamp"),
        _class="main-window",
    )

    return Html(
        Head(
            Title("Pipeline Status - AI Tools Collection"),
            Meta({"charset": "utf-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Meta(
                {
                    "name": "description",
                    "content": "Real-time pipeline monitoring dashboard with performance metrics.",
                }
            ),
            Meta(name="robots", content="index,follow"),
            StyleX(str(Path(__file__).parent / "static/styles.css")),
            status_styles,
        ),
        Body(content),
    )


@rt("/")
async def get():
    tools_by_category = get_tools_by_category()
    sections = [category_section(cat, tools, use_internal_links=True) for cat, tools in tools_by_category.items()]

    # Trigger background refresh
    asyncio.create_task(refresh_tools_background())

    return Html(
        Head(
            Title("AI Tools Collection - Best AI Software & Applications"),
            Meta({"charset": "utf-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Meta(
                {
                    "name": "description",
                    "content": (
                        "Discover the best AI tools for productivity, content creation, development, and more. "
                        "A curated collection of artificial intelligence tools gathered by AI agents."
                    ),
                }
            ),
            Meta(
                {
                    "name": "keywords",
                    "content": (
                        "AI tools, artificial intelligence, productivity tools, AI software, "
                        "machine learning tools, automation"
                    ),
                }
            ),
            Meta({"name": "robots", "content": "index, follow"}),
            Meta({"property": "og:title", "content": "AI Tools Collection - Best AI Software & Applications"}),
            Meta(
                {
                    "property": "og:description",
                    "content": (
                        "Discover the best AI tools for productivity, content creation, development, and more. "
                        "A curated collection of artificial intelligence tools."
                    ),
                }
            ),
            Meta({"property": "og:type", "content": "website"}),
            Meta({"name": "twitter:card", "content": "summary_large_image"}),
            Meta({"name": "twitter:title", "content": "AI Tools Collection - Best AI Software & Applications"}),
            Meta(
                {
                    "name": "twitter:description",
                    "content": "Discover the best AI tools for productivity, content creation, development, and more.",
                }
            ),
            StyleX(str(Path(__file__).parent / "static/styles.css")),
        ),
        Body(
            Div(
                Div(
                    A(
                        {
                            "href": "https://github.com/cipher982/ai-tools-website",
                            "target": "_blank",
                            "_class": "github-link",
                        },
                        Img({"src": "github-mark-white.svg", "alt": "GitHub", "width": "32", "height": "32"}),
                    ),
                    _class="github-corner",
                ),
                H1("AI Tools Collection", _class="window-title"),
                P("A curated collection of AI tools, gathered by AI agents.", _class="intro"),
                Input({"type": "search", "id": "search", "placeholder": "Search tools...", "_id": "search"}),
                *sections,
                _class="main-window",
            ),
            Script(src="search.js"),
        ),
    )


@rt("/tools/{slug}")
async def get_tool_page(slug: str):
    """Individual tool page with SEO optimization"""
    tool = find_tool_by_slug(slug)
    if not tool:
        return Html(
            Head(Title("Tool Not Found")), Body(H1("Tool Not Found"), P(f"No tool found with slug: {slug}"))
        ), 404

    base_url = get_base_url()
    meta_title = generate_meta_title(tool["name"], tool.get("category", "AI Tool"))
    meta_desc = generate_meta_description(tool["name"], tool["description"])

    # Generate breadcrumbs
    breadcrumbs = generate_breadcrumb_list(
        [
            {"name": "Home", "url": ""},
            {
                "name": tool.get("category", "Tools"),
                "url": f"category/{generate_category_slug(tool.get('category', 'Tools'))}",
            },
            {"name": tool["name"], "url": f"tools/{slug}"},
        ],
        base_url,
    )

    # Generate structured data
    product_schema = generate_product_schema(tool, base_url)

    # Find related tools (same category)
    category = tool.get("category", "Other")
    tools_by_category = get_tools_by_category()
    related_tools = [t for t in tools_by_category.get(category, []) if generate_tool_slug(t["name"]) != slug][:6]
    content_blocks = render_tool_sections(tool)

    return Html(
        Head(
            Title(meta_title),
            Meta({"charset": "utf-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Meta({"name": "description", "content": meta_desc}),
            Meta({"name": "robots", "content": "index, follow"}),
            Meta({"property": "og:title", "content": meta_title}),
            Meta({"property": "og:description", "content": meta_desc}),
            Meta({"property": "og:type", "content": "website"}),
            Meta({"property": "og:url", "content": f"{base_url}/tools/{slug}"}),
            Script(json.dumps(breadcrumbs), type="application/ld+json"),
            Script(json.dumps(product_schema), type="application/ld+json"),
            StyleX(str(Path(__file__).parent / "static/styles.css")),
        ),
        Body(
            Div(
                # Breadcrumb navigation
                Div(
                    A("Home", href=url("/")),
                    " › ",
                    A(category, href=url(f"/category/{generate_category_slug(category)}")),
                    " › ",
                    Span(tool["name"]),
                    _class="breadcrumbs",
                ),
                # Main content
                H1(f"{tool['name']} - AI {category} Tool", _class="tool-title"),
                Div(
                    Div(
                        *content_blocks,
                        H3("Key Information"),
                        Ul(
                            Li(f"Category: {category}"),
                            Li(f"Type: AI {category} Tool"),
                        ),
                        Div(
                            A("Visit Official Website", href=tool["url"], target="_blank", _class="cta-button"),
                            _class="cta-section",
                        ),
                        _class="tool-content",
                    ),
                    # Sidebar with related tools
                    Div(
                        H3("Related Tools"),
                        Div(*[tool_card(t) for t in related_tools], _class="related-tools"),
                        _class="sidebar",
                    )
                    if related_tools
                    else None,
                    _class="tool-layout",
                ),
                _class="main-window",
            )
        ),
    )


@rt("/compare/{slug}")
async def get_comparison_page(slug: str):
    """Comparison page with SEO optimization"""
    comparison, tool1_name, tool2_name = find_comparison_by_slug(slug)
    if not comparison or not tool1_name or not tool2_name:
        return Html(
            Head(Title("Comparison Not Found")), Body(H1("Comparison Not Found"), P(f"No comparison found for: {slug}"))
        ), 404

    base_url = get_base_url()
    title = comparison.get("title", f"{tool1_name} vs {tool2_name}: Complete Comparison Guide")
    meta_desc = comparison.get(
        "meta_description", f"Compare {tool1_name} and {tool2_name}. Features, pricing, pros/cons analysis."
    )

    # Generate breadcrumbs
    breadcrumbs = generate_breadcrumb_list(
        [
            {"name": "Home", "url": ""},
            {"name": "Comparisons", "url": "comparisons"},
            {"name": f"{tool1_name} vs {tool2_name}", "url": f"compare/{slug}"},
        ],
        base_url,
    )

    # Generate structured data for comparison
    comparison_schema = {
        "@context": "https://schema.org",
        "@type": "Review",
        "name": title,
        "description": meta_desc,
        "author": {"@type": "Organization", "name": "AI Tools Directory"},
        "datePublished": comparison.get("last_updated", datetime.now().isoformat()),
        "itemReviewed": [
            {"@type": "SoftwareApplication", "name": tool1_name},
            {"@type": "SoftwareApplication", "name": tool2_name},
        ],
    }

    # Render comparison content
    content_blocks = render_comparison_sections(comparison, tool1_name, tool2_name)

    # Last updated info
    last_updated = comparison.get("last_updated", "")
    if last_updated:
        try:
            updated_date = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            formatted_date = updated_date.strftime("%B %d, %Y")
        except ValueError:
            formatted_date = last_updated
    else:
        formatted_date = "Recently"

    return Html(
        Head(
            Title(title),
            Meta({"charset": "utf-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Meta({"name": "description", "content": meta_desc}),
            Meta({"name": "robots", "content": "index, follow"}),
            Meta({"property": "og:title", "content": title}),
            Meta({"property": "og:description", "content": meta_desc}),
            Meta({"property": "og:type", "content": "article"}),
            Meta({"property": "og:url", "content": f"{base_url}/compare/{slug}"}),
            Meta({"name": "article:author", "content": "AI Tools Directory"}),
            Script(json.dumps(breadcrumbs), type="application/ld+json"),
            Script(json.dumps(comparison_schema), type="application/ld+json"),
            StyleX(str(Path(__file__).parent / "static/styles.css")),
        ),
        Body(
            Div(
                Section(
                    H1(f"{tool1_name} vs {tool2_name}", _class="title"),
                    P(f"Last updated: {formatted_date}", _class="last-updated"),
                    *content_blocks,
                    # Related tools section
                    H2("Explore More Comparisons"),
                    P(
                        "Looking for other AI tool comparisons? Browse our complete directory to find "
                        "the right tools for your needs."
                    ),
                    A("View All Tools", href=url("/"), _class="cta-button"),
                ),
                _class="main-window",
            )
        ),
    )


@rt("/category/{category_slug}")
async def get_category_page(category_slug: str):
    """Category hub page with SEO optimization"""
    tools, category_name = get_tools_for_category(category_slug)
    if not tools:
        return Html(
            Head(Title("Category Not Found")), Body(H1("Category Not Found"), P(f"No category found: {category_slug}"))
        ), 404

    base_url = get_base_url()
    meta_title = f"Best AI {category_name} Tools - Complete Guide & Reviews"
    meta_desc = (
        f"Discover the top AI {category_name.lower()} tools. "
        "Compare features, pricing, and find the perfect solution for your needs."
    )

    # Generate breadcrumbs
    breadcrumbs = generate_breadcrumb_list(
        [{"name": "Home", "url": ""}, {"name": f"AI {category_name} Tools", "url": f"category/{category_slug}"}],
        base_url,
    )

    return Html(
        Head(
            Title(meta_title),
            Meta({"charset": "utf-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Meta({"name": "description", "content": meta_desc}),
            Meta({"name": "robots", "content": "index, follow"}),
            Meta({"property": "og:title", "content": meta_title}),
            Meta({"property": "og:description", "content": meta_desc}),
            Meta({"property": "og:type", "content": "website"}),
            Meta({"property": "og:url", "content": f"{base_url}/category/{category_slug}"}),
            Script(json.dumps(breadcrumbs), type="application/ld+json"),
            StyleX(str(Path(__file__).parent / "static/styles.css")),
        ),
        Body(
            Div(
                # Breadcrumb navigation
                Div(A("Home", href=url("/")), " › ", Span(f"AI {category_name} Tools"), _class="breadcrumbs"),
                # Main content
                H1(f"Best AI {category_name} Tools", _class="category-title"),
                P(
                    f"Explore {len(tools)} AI {category_name.lower()} tools to find the perfect solution.",
                    _class="category-intro",
                ),
                # Tools grid
                category_section(category_name, tools, use_internal_links=True),
                _class="main-window",
            )
        ),
    )


@rt("/sitemap.xml")
async def get_sitemap():
    """Generate XML sitemap with all pages"""
    base_url = get_base_url()
    tools_by_category = get_tools_by_category()
    all_tools = get_all_tools()

    # Use current date for lastmod
    current_date = datetime.now().strftime("%Y-%m-%d")

    # Build sitemap URLs
    urls = []

    # Homepage
    urls.append({"loc": base_url, "lastmod": current_date, "changefreq": "weekly", "priority": "1.0"})

    # Category pages
    for category in tools_by_category.keys():
        category_slug = generate_category_slug(category)
        urls.append(
            {
                "loc": f"{base_url}/category/{category_slug}",
                "lastmod": current_date,
                "changefreq": "weekly",
                "priority": "0.8",
            }
        )

    # Individual tool pages
    for tool in all_tools:
        tool_slug = generate_tool_slug(tool["name"])
        urls.append(
            {
                "loc": f"{base_url}/tools/{tool_slug}",
                "lastmod": current_date,  # TODO: Use actual tool last_updated when available
                "changefreq": "monthly",
                "priority": "0.7",
            }
        )

    # Comparison pages
    all_comparisons = get_all_comparisons()
    for comparison in all_comparisons:
        urls.append(
            {
                "loc": f"{base_url}/compare/{comparison['slug']}",
                "lastmod": current_date,  # TODO: Use actual comparison last_updated when available
                "changefreq": "monthly",
                "priority": "0.6",
            }
        )

    # Generate XML sitemap
    xml_content = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_content.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for url in urls:
        xml_content.append("  <url>")
        xml_content.append(f'    <loc>{url["loc"]}</loc>')
        xml_content.append(f'    <lastmod>{url["lastmod"]}</lastmod>')
        xml_content.append(f'    <changefreq>{url["changefreq"]}</changefreq>')
        xml_content.append(f'    <priority>{url["priority"]}</priority>')
        xml_content.append("  </url>")

    xml_content.append("</urlset>")

    return "\n".join(xml_content), {"Content-Type": "application/xml"}


@rt("/health")
def health():
    return {"status": "ok"}


# For direct script execution
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Starting server on port {port}")
    uvicorn.run("ai_tools_website.v1.web:app", host="0.0.0.0", port=port, reload=True)
