#!/usr/bin/env python3

import json
import logging
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import List

from jinja2 import Environment
from jinja2 import FileSystemLoader

from .logging_config import setup_logging
from .search import find_new_tools

logger = logging.getLogger(__name__)


def load_tools() -> Dict:
    """Load tools data from JSON file."""
    data_path = Path("data/tools.json")
    if not data_path.exists():
        logger.error(f"Data file not found at {data_path}")
        raise FileNotFoundError(f"Data file not found at {data_path}")

    with open(data_path, "r") as f:
        return json.load(f)


def save_tools(tools_data: Dict) -> None:
    """Save tools data to JSON file."""
    data_path = Path("data/tools.json")
    with open(data_path, "w") as f:
        json.dump(tools_data, f, indent=4)
    logger.info(f"Saved {len(tools_data['tools'])} tools to {data_path}")


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
    templates_path = Path("templates")
    if not templates_path.exists():
        logger.error(f"Templates directory not found at {templates_path}")
        raise FileNotFoundError(f"Templates directory not found at {templates_path}")

    env = Environment(loader=FileSystemLoader(templates_path))
    template = env.get_template("index.html")

    tools_by_category = group_tools_by_category(tools_data["tools"])
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = template.render(tools_by_category=tools_by_category, last_updated=last_updated)

    output_dir = Path("public")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "index.html"
    with open(output_file, "w") as f:
        f.write(html)
    logger.info(f"Generated HTML page at {output_file}")


def update_tools() -> Dict:
    """Update tools list with new findings."""
    logger.info("Starting tools update process")
    current_data = load_tools()
    logger.info(f"Loaded {len(current_data['tools'])} existing tools")

    new_tools = find_new_tools()
    logger.info(f"Found {len(new_tools)} potential new tools")

    # Create a set of existing URLs for deduplication
    existing_urls = {tool["url"] for tool in current_data["tools"]}
    added_count = 0

    # Add only new tools that aren't already in our list
    for tool in new_tools:
        if tool["url"] not in existing_urls:
            current_data["tools"].append(tool)
            existing_urls.add(tool["url"])
            added_count += 1

    logger.info(f"Added {added_count} new tools")

    # Update last_updated timestamp
    current_data["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Save updated data
    save_tools(current_data)

    return current_data


def main() -> None:
    """Main function to update the page."""
    setup_logging()
    logger.info("Starting AI tools website update")

    try:
        # Update tools list
        tools_data = update_tools()

        # Generate new page
        generate_page(tools_data)

        logger.info("Website update completed successfully")
    except Exception as e:
        logger.error(f"Error updating website: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
