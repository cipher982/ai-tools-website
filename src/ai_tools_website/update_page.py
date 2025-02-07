#!/usr/bin/env python3

import logging
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import List

from jinja2 import Environment
from jinja2 import FileSystemLoader

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .search import DEV_MODE
from .search import search_ai_tools

logger = logging.getLogger(__name__)


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


def find_new_tools() -> List[Dict]:
    """Find new AI tools using search queries."""
    queries = (
        [
            "site:producthunt.com new AI tool launch",
            "site:github.com new AI tool release",
            "site:huggingface.co/spaces new",
            "site:replicate.com new model",
        ]
        if not DEV_MODE
        else [
            "site:producthunt.com new AI tool launch",
            "site:github.com new AI tool release",
        ]
    )

    all_tools = []
    for query in queries:
        tools = search_ai_tools(query)
        all_tools.extend(tools)
        logger.info(f"Found {len(tools)} tools for query: {query}")

    return all_tools


def update_tools() -> Dict:
    """Update tools list with new findings."""
    logger.info("Starting tools update process")
    current_data = load_tools()
    logger.info(f"Loaded {len(current_data['tools'])} existing tools")

    new_tools = find_new_tools()
    logger.info(f"Found {len(new_tools)} potential updates")

    # Create a map of existing tools by URL for efficient lookup
    tools_by_url = {tool["url"]: tool for tool in current_data["tools"]}

    update_count = 0
    add_count = 0

    # Process updates and additions
    for tool in new_tools:
        if tool["url"] in tools_by_url:
            # Update existing tool
            existing_tool = tools_by_url[tool["url"]]
            if (
                tool["name"] != existing_tool["name"]
                or tool["description"] != existing_tool["description"]
                or tool["category"] != existing_tool["category"]
            ):
                existing_tool.update(tool)
                update_count += 1
                logger.info(f"Updated tool: {tool['name']}")
        else:
            # Add new tool
            current_data["tools"].append(tool)
            tools_by_url[tool["url"]] = tool
            add_count += 1
            logger.info(f"Added new tool: {tool['name']}")

    logger.info(f"Added {add_count} new tools, updated {update_count} existing tools")

    # Update last_updated timestamp
    current_data["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Save updated data
    save_tools(current_data)

    # Generate new page
    generate_page(current_data)

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
