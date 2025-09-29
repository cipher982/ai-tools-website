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

# Simple global cache
tools_cache: Dict = {}
logger = logging.getLogger(__name__)


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


def get_base_url() -> str:
    """Get base URL for the site"""
    return os.getenv("BASE_URL", "https://ai-tools.dev")


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
        {"href": f"/tools/{tool_slug}", "_class": "tool-card"},
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
    category_link = A(name, href=f"/category/{category_slug}")

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
    /* Retro Windows Pipeline Dashboard - Compact Above-The-Fold Design */
    .pipeline-page {
        background: var(--win98-face);
        padding: var(--spacing-md);
        border: var(--border-raised);
        border-color: var(--border-raised-color);
        box-shadow: 4px 4px 8px rgba(0, 0, 0, 0.3);
        margin: var(--spacing-lg) auto;
        max-width: 1100px;
    }

    .pipeline-grid {
        display: grid;
        gap: var(--spacing-md);
        grid-template-columns: repeat(3, 1fr);
        margin-top: var(--spacing-md);
    }

    /* Compact pipeline windows */
    .pipeline-card {
        background: var(--win98-face);
        border: var(--border-sunken);
        border-color: var(--border-sunken-color);
        padding: var(--spacing-md);
        position: relative;
        min-height: 200px;
    }

    /* Health status title bars */
    .modern-header {
        background: var(--win98-active-title);
        color: var(--win98-text-light);
        margin: calc(var(--spacing-md) * -1) calc(var(--spacing-md) * -1) var(--spacing-sm);
        padding: var(--spacing-sm) var(--spacing-md);
        font-size: 11px;
        font-weight: bold;
        border-bottom: 1px solid var(--win98-shadow);
    }

    .health-excellent .modern-header { background: #008000; }
    .health-healthy .modern-header { background: #008000; }
    .health-degraded .modern-header { background: #808000; }
    .health-critical .modern-header { background: #800000; }
    .health-unknown .modern-header { background: var(--win98-inactive-title); }

    .modern-header h2 { margin: 0; font-size: 11px; font-weight: bold; display: inline; }
    .health-row { float: right; }
    .health-indicator { font-size: 11px; }
    .progress-visual { font-family: monospace; font-size: 10px; margin-left: 4px; }

    /* Compact info sections */
    .summary-section {
        background: var(--win98-button-face);
        border: var(--border-sunken);
        border-color: var(--border-sunken-color);
        padding: var(--spacing-sm);
        margin-bottom: var(--spacing-sm);
        font-size: 10px;
    }

    .schedule-info { margin: 0; font-weight: bold; color: var(--win98-text); }
    .next-run-info { margin: 2px 0 0 0; color: var(--win98-accent); }
    .trend-info { margin: 2px 0 0 0; font-family: monospace; }
    .context-summary { margin: 2px 0 0 0; font-weight: bold; }

    /* Compact insights */
    .insight-normal, .insight-warning, .insight-critical {
        margin: var(--spacing-sm) 0;
        padding: var(--spacing-xs) var(--spacing-sm);
        font-size: 10px;
        border: 1px solid;
    }

    .insight-normal {
        background: #C8F7C5; border-color: #4ADE80; color: #166534;
    }
    .insight-warning {
        background: #FEF3C7; border-color: #FBBF24; color: #92400E;
    }
    .insight-critical {
        background: #FEE2E2; border-color: #F87171; color: #991B1B;
    }

    /* Compact metrics */
    .section-title {
        margin: var(--spacing-sm) 0 var(--spacing-xs) 0;
        font-size: 10px;
        font-weight: bold;
        color: var(--win98-text);
    }
    .metrics-list {
        margin: 0;
        padding: 0;
        list-style: none;
        font-size: 10px;
    }
    .metrics-list li {
        display: flex;
        justify-content: space-between;
        margin: 1px 0;
        padding: 1px 0;
    }
    .metric-value { font-weight: bold; color: var(--win98-accent); }

    /* Typography consistency */
    .back-link { color: var(--win98-text); text-decoration: underline; font-size: 11px; }
    .generated-at { font-size: 10px; color: var(--win98-text); margin-top: var(--spacing-sm); }

    /* Responsive - stack on mobile */
    @media (max-width: 768px) {
        .pipeline-grid { grid-template-columns: 1fr; }
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

            # Modern card header with health indicator
            header_components = [
                H2(f"{pipeline_name} Pipeline"),
                Div(
                    Span(f"{health_emoji} {health_status.title()}", _class="health-indicator"),
                    Span(pipeline.get("progress_bar", ""), _class="progress-visual"),
                    _class="health-row",
                ),
            ]

            # Performance summary with sparkline
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

            # Insights (actionable information)
            insights = pipeline.get("insights", [])
            insight_components = []
            for insight in insights[:2]:  # Limit to 2 most important
                if insight:
                    # Classify insight type by content
                    if insight.startswith(("✅", "⚡ Performance improving")):
                        css_class = "insight-normal"
                    elif insight.startswith(("⚠️", "⏱️")):
                        css_class = "insight-warning"
                    elif insight.startswith(("🚨", "🔥", "❌")):
                        css_class = "insight-critical"
                    else:
                        css_class = "insight-normal"  # Default to normal

                    insight_components.append(P(insight, _class=css_class))

            # Filtered metrics (outcomes only)
            metrics = pipeline.get("filtered_metrics", {})
            metric_components = []
            if metrics and len(metrics) > 0:
                metric_items = []
                for key, value in sorted(metrics.items()):
                    if str(value).isdigit() or isinstance(value, (int, float)):  # Only show numeric outcomes
                        # Format the metric display
                        metric_items.append(
                            Li(
                                Span(key),
                                Span(str(value), _class="metric-value"),
                            )
                        )
                if metric_items:
                    metric_components = [
                        H3("Key Metrics", _class="section-title"),
                        Ul(*metric_items, _class="metrics-list"),
                    ]

            # Combine all components
            card_content = [
                Div(*header_components, _class="modern-header"),
                Div(*summary_components, _class="summary-section"),
                *insight_components,
                *metric_components,
            ]

            cards.append(Div(*card_content, _class=" ".join(card_classes)))

    # Retro Windows dashboard layout
    content = Div(
        Div(
            A("← Back", href="/", _class="back-link"),
            H1("Pipeline Monitor", _class="window-title"),
            P("Automated job status with performance metrics and diagnostics."),
            Div(*cards, _class="pipeline-grid"),
            P(f"Last Updated: {_format_timestamp(now.isoformat())}", _class="generated-at"),
            _class="pipeline-page",
        ),
    )

    return Html(
        Head(
            Title("Pipeline Status"),
            Meta(name="robots", content="index,follow"),
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
                    A("Home", href="/"),
                    " › ",
                    A(category, href=f"/category/{generate_category_slug(category)}"),
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
                Div(A("Home", href="/"), " › ", Span(f"AI {category_name} Tools"), _class="breadcrumbs"),
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
