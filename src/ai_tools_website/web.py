import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fasthtml.common import H2
from fasthtml.common import H5
from fasthtml.common import A
from fasthtml.common import Div
from fasthtml.common import Input
from fasthtml.common import P
from fasthtml.common import Script
from fasthtml.common import Section
from fasthtml.common import Span
from fasthtml.common import Style
from fasthtml.common import Titled
from fasthtml.core import serve
from fasthtml.fastapp import fast_app

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
    )


def category_section(name, tools):
    cards = []
    for t in tools:
        cards.append(tool_card(t))

    return Section(
        H2(name), Span(f"{len(tools)} tools", _class="count"), Div(*cards, _class="tools-grid"), _class="category"
    )


# Styles
styles = """
.tools-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1rem;
}
.tool-card {
    background: #fff;
    padding: 1rem;
    border-radius: 4px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.tool-card h5 {
    margin: 0 0 0.5rem 0;
    font-size: 1.1rem;
}
.tool-card p {
    margin: 0;
    font-size: 0.9rem;
    color: #666;
}
.tool-card a {
    display: inline-block;
    margin-top: 1rem;
    text-decoration: none;
    color: #0d6efd;
}
.category {
    margin-bottom: 2rem;
}
.category h2 {
    margin: 0;
    font-size: 1.2rem;
    border-bottom: 1px solid #eee;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}
.count {
    background: #6c757d;
    color: white;
    padding: 0.2rem 0.5rem;
    border-radius: 3px;
    font-size: 0.8rem;
}
"""

# Search script
search_script = """
const searchInput = document.getElementById('search');
const toolCards = document.querySelectorAll('.tool-card');
const categories = document.querySelectorAll('.category');

searchInput.addEventListener('input', (e) => {
    const searchTerm = e.target.value.toLowerCase();
    toolCards.forEach(card => {
        const searchText = card.dataset.search;
        const visible = searchText.includes(searchTerm);
        card.style.display = visible ? '' : 'none';
    });
    categories.forEach(category => {
        const visibleTools = category.querySelectorAll('.tool-card:not([style*="none"])').length;
        category.style.display = visibleTools > 0 ? '' : 'none';
    });
});
"""

# App setup
app, rt = fast_app()


@rt("/")
def get():
    tools_by_category = load_tools()

    sections = [category_section(cat, tools) for cat, tools in tools_by_category.items()]

    return Titled(
        "AI Tools Collection",
        Style(styles),
        P("A curated collection of AI tools, gathered by AI agents."),
        Input({"type": "search", "id": "search", "placeholder": "Search tools..."}),
        *sections,  # Unpack the list of sections
        Script(search_script),
    )


if __name__ == "__main__":
    port = os.getenv("WEB_PORT")
    print(f"Starting server on port {port}")
    if not port:
        raise ValueError("WEB_PORT environment variable is not set")
    serve(port=int(port))
