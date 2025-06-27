import asyncio
import logging
import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fasthtml.common import H2
from fasthtml.common import H5
from fasthtml.common import A
from fasthtml.common import Container
from fasthtml.common import Div
from fasthtml.common import Img
from fasthtml.common import Input
from fasthtml.common import P
from fasthtml.common import Script
from fasthtml.common import Section
from fasthtml.common import Span
from fasthtml.common import StyleX
from fasthtml.common import Titled
from fasthtml.fastapp import fast_app

from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.logging_config import setup_logging

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


# Components
def tool_card(tool):
    return A(
        {"href": tool["url"], "target": "_blank", "_class": "tool-card"},
        H5(tool["name"]),
        P(tool["description"]),
        **{"data-search": f"{tool['name'].lower()} {tool['description'].lower()}"},
    )


def category_section(name, tools):
    cards = []
    for t in tools:
        cards.append(tool_card(t))

    return Section(
        H2(name), Span(f"{len(tools)} tools", _class="count"), Div(*cards, _class="tools-grid"), _class="category"
    )


# App setup
app, rt = fast_app(static_path=str(Path(__file__).parent / "static"))


@rt("/")
async def get():
    tools_by_category = get_tools_by_category()
    sections = [category_section(cat, tools) for cat, tools in tools_by_category.items()]

    # Trigger background refresh
    asyncio.create_task(refresh_tools_background())

    return Titled(
        "AI Tools Collection",
        Container(
            StyleX(str(Path(__file__).parent / "static/styles.css")),
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
            P("A curated collection of AI tools, gathered by AI agents.", _class="intro"),
            Input({"type": "search", "id": "search", "placeholder": "Search tools...", "_id": "search"}),
            *sections,
            Script(src="search.js"),
        ),
    )


@rt("/health")
def health():
    return {"status": "ok"}


# For direct script execution
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Starting server on port {port}")
    uvicorn.run("ai_tools_website.web:app", host="0.0.0.0", port=port, reload=True)
