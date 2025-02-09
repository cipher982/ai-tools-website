import json
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
from fasthtml.core import serve
from fasthtml.fastapp import fast_app
from starlette.staticfiles import StaticFiles

load_dotenv()


# Data loading
@lru_cache()
def load_tools():
    """Load tools from JSON and cache in memory"""
    tools_file = os.getenv("TOOLS_FILE")
    if not tools_file:
        raise ValueError("TOOLS_FILE environment variable is not set")
    if not Path(tools_file).exists():
        raise FileNotFoundError(f"Tools file not found at {tools_file}")

    data = json.loads(Path(tools_file).read_text())
    tools_by_category = {}
    for tool in data["tools"]:
        category = tool["category"]
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
    tools_by_category = load_tools()
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


if __name__ == "__main__":
    port = os.getenv("WEB_PORT")
    print(f"Starting server on port {port}")
    if not port:
        raise ValueError("WEB_PORT environment variable is not set")
    serve(port=int(port))
