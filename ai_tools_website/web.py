import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fasthtml.common import H2
from fasthtml.common import H5
from fasthtml.common import A
from fasthtml.common import Container
from fasthtml.common import Div
from fasthtml.common import Input
from fasthtml.common import P
from fasthtml.common import Script
from fasthtml.common import Section
from fasthtml.common import Span
from fasthtml.common import StyleX
from fasthtml.common import Titled
from fasthtml.fastapp import fast_app
from starlette.staticfiles import StaticFiles

from ai_tools_website.data_manager import load_tools

load_dotenv()


# Data loading
@lru_cache()
def get_tools_by_category():
    """Load tools from Minio and organize by category"""
    data = load_tools()
    tools_by_category = {}
    for tool in data["tools"]:
        category = tool.get("category", "Missing")
        if category not in tools_by_category:
            tools_by_category[category] = []
        tools_by_category[category].append(tool)
    return tools_by_category


# Components
def tool_card(tool):
    return Div(
        H5(tool["name"]),
        P(tool["description"]),
        A({"href": tool["url"], "target": "_blank"}, "Visit Tool →"),
        _class="tool-card",
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
app, rt = fast_app()
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@rt("/")
def get():
    tools_by_category = get_tools_by_category()
    sections = [category_section(cat, tools) for cat, tools in tools_by_category.items()]

    return Titled(
        "AI Tools Collection",
        Container(
            StyleX(str(Path(__file__).parent / "static/styles.css")),
            P("A curated collection of AI tools, gathered by AI agents.", _class="intro"),
            Input({"type": "search", "id": "search", "placeholder": "Search tools..."}),
            *sections,
        ),
        Script(src="/static/search.js"),
    )


# For direct script execution
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Starting server on port {port}")
    uvicorn.run("ai_tools_website.web:app", host="0.0.0.0", port=port, reload=True)
