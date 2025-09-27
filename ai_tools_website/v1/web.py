import asyncio
import json
import logging
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict

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
from fasthtml.common import StyleX
from fasthtml.common import Title
from fasthtml.common import Ul
from fasthtml.fastapp import fast_app

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.logging_config import setup_logging
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


PIPELINE_STATUS_PATH = Path(__file__).parent / "static" / "pipeline_status.json"


def _load_pipeline_status_snapshot() -> dict | None:
    if not PIPELINE_STATUS_PATH.exists():
        logger.info("Pipeline status snapshot missing at %s", PIPELINE_STATUS_PATH)
        return None
    try:
        with PIPELINE_STATUS_PATH.open() as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse pipeline status snapshot: %s", exc)
        return None


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


status_styles = StyleX(
    """
    .pipeline-page { max-width: 960px; margin: 0 auto; padding: 2rem 1rem; font-family: Inter, system-ui, sans-serif; }
    .pipeline-header { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap;
                       gap: 0.5rem; }
    .pipeline-grid { display: grid; gap: 1.5rem; margin-top: 1.5rem;
                     grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    .pipeline-card { border: 1px solid #d0d7de; border-radius: 12px; padding: 1.25rem; background: #fff;
                     box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08); display: flex; flex-direction: column; gap: 0.5rem; }
    .pipeline-card.status-success { border-color: #22c55e; }
    .pipeline-card.status-error { border-color: #ef4444; }
    .pipeline-card.status-missing, .pipeline-card.status-unknown { border-color: #9ca3af; }
    .pipeline-card.status-stale { box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.25); }
    .status-pill { display: inline-flex; align-items: center; padding: 0.15rem 0.6rem; border-radius: 999px;
                   font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
    .pipeline-card.status-success .status-pill { color: #166534; background: rgba(34, 197, 94, 0.16); }
    .pipeline-card.status-error .status-pill { color: #991b1b; background: rgba(239, 68, 68, 0.18); }
    .pipeline-card.status-missing .status-pill,
    .pipeline-card.status-unknown .status-pill { color: #374151; background: rgba(156, 163, 175, 0.24); }
    .status-note { font-size: 0.75rem; color: #b45309; font-weight: 600; }
    .meta-row { font-size: 0.85rem; color: #475569; }
    .metrics-list, .attributes-list { margin: 0; padding-left: 1.1rem; font-size: 0.9rem; color: #1f2937; }
    .section-title { margin-top: 0.5rem; font-size: 0.9rem; font-weight: 600; color: #111827; }
    .empty-state { font-size: 0.9rem; color: #6b7280; font-style: italic; }
    body { background: #f8fafc; }
    a.back-link { color: #2563eb; font-size: 0.9rem; }
    .generated-at { font-size: 0.85rem; color: #475569; }
    """
)


@rt("/pipeline-status")
async def pipeline_status():
    snapshot = _load_pipeline_status_snapshot()
    pipelines = snapshot.get("pipelines", []) if snapshot else []
    generated_at = _format_timestamp(snapshot.get("generated_at")) if snapshot else None

    cards = []
    if not pipelines:
        cards.append(Div(P("No pipeline runs recorded yet."), _class="pipeline-card status-missing"))
    else:
        for entry in pipelines:
            pipeline_key = entry.get("pipeline", "unknown")
            pipeline_label = pipeline_key.replace("_", " ").title()
            status_value = entry.get("status", "unknown")
            status_label = status_value.replace("_", " ").title()
            card_classes = ["pipeline-card", f"status-{status_value}"]
            if entry.get("stale"):
                card_classes.append("status-stale")

            components = [
                Div(
                    H2(pipeline_label),
                    Span(status_label, _class="status-pill"),
                    _class="pipeline-header",
                ),
                P(f"Started: {_format_timestamp(entry.get('started_at'))}", _class="meta-row"),
                P(f"Finished: {_format_timestamp(entry.get('finished_at'))}", _class="meta-row"),
                P(f"Duration: {entry.get('duration_seconds', '—')}s", _class="meta-row"),
            ]

            if entry.get("stale"):
                components.append(Span("Stale data – older than 6 hours", _class="status-note"))

            error_type = entry.get("error_type") or entry.get("error_note")
            if error_type:
                components.append(P(f"Last error: {error_type}", _class="status-note"))

            metrics = entry.get("metrics") or {}
            components.append(H3("Metrics", _class="section-title"))
            if metrics:
                metric_items = [
                    Li(f"{key.replace('_', ' ').title()}: {value}") for key, value in sorted(metrics.items())
                ]
                components.append(Ul(*metric_items, _class="metrics-list"))
            else:
                components.append(P("No metrics reported", _class="empty-state"))

            attributes = entry.get("attributes") or {}
            if attributes:
                components.append(H3("Attributes", _class="section-title"))
                attribute_items = [
                    Li(f"{key.replace('_', ' ').title()}: {value}") for key, value in sorted(attributes.items())
                ]
                components.append(Ul(*attribute_items, _class="attributes-list"))

            cards.append(Div(*components, _class=" ".join(card_classes)))

    content = Div(
        Div(
            A("← Back", href="/", _class="back-link"),
            H1("Pipeline Status"),
            P(
                "Snapshot of our automated jobs. Data refreshes whenever the pipelines emit new summaries.",
            ),
            P(f"Updated: {generated_at}" if generated_at else "Updated: —", _class="generated-at"),
            Div(*cards, _class="pipeline-grid"),
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
