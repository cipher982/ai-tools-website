import asyncio
import json
import logging
import os
from datetime import datetime
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
