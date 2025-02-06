#!/usr/bin/env python3

from datetime import datetime, timezone
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from typing import Dict, List

def load_tools() -> Dict:
    """Load tools data from JSON file."""
    with open("data/tools.json", "r") as f:
        return json.load(f)

def group_tools_by_category(tools: List[Dict]) -> Dict[str, List[Dict]]:
    """Group tools by their category."""
    categories: Dict[str, List[Dict]] = {}
    for tool in tools:
        category = tool["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(tool)
    return categories

def generate_page(tools_data: Dict) -> None:
    """Generate HTML page using template."""
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("index.html")
    
    tools_by_category = group_tools_by_category(tools_data["tools"])
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    html = template.render(
        tools_by_category=tools_by_category,
        last_updated=last_updated
    )
    
    with open("public/index.html", "w") as f:
        f.write(html)

def main() -> None:
    """Main function to update the page."""
    # Ensure directories exist
    Path("public").mkdir(exist_ok=True)
    
    # Load and process data
    tools_data = load_tools()
    generate_page(tools_data)

if __name__ == "__main__":
    main() 