"""Maintenance tasks for the AI tools database."""

import asyncio
import json
import logging

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .search import MODEL_NAME
from .search import build_category_context
from .search import client
from .search import smart_deduplicate_tools

logger = logging.getLogger(__name__)


async def recategorize_database() -> None:
    """Do a complete review and reorganization of tool categories."""
    logger.info("Starting tool recategorization...")
    current = load_tools()
    total = len(current["tools"])
    logger.info(f"Processing {total} tools")

    # Get AI to analyze current categorization and suggest improvements
    categories_text = build_category_context(current)

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": """You are an expert at organizing AI tools into meaningful categories.
Your task is to analyze the current categorization and suggest improvements.
Consider:
1. Categories that could be merged (e.g., 'LLMs' and 'Language Models')
2. Categories that should be split (e.g., if 'Other' contains distinct groups)
3. Tools that might fit better in different categories
4. Category names that could be more clear or consistent""",
            },
            {
                "role": "user",
                "content": f"""Here is our current database of tools organized by category:

{categories_text}

Analyze this categorization and suggest a revised category structure.
Reply in this JSON format:
{{
    "category_changes": [
        {{"from": "old_category", "to": "new_category", "reason": "explanation"}}
    ],
    "tool_moves": [
        {{"tool": "tool_name", "from": "old_category", "to": "new_category", "reason": "explanation"}}
    ]
}}""",
            },
        ],
    )

    changes = json.loads(completion.choices[0].message.content)
    logger.info("Got reorganization suggestions:")
    for change in changes["category_changes"]:
        logger.info(f"Category: {change['from']} -> {change['to']}: {change['reason']}")
    for move in changes["tool_moves"]:
        logger.info(f"Tool: {move['tool']} from {move['from']} to {move['to']}: {move['reason']}")

    # Apply the changes if they seem reasonable
    if changes["category_changes"] or changes["tool_moves"]:
        logger.info("Applying suggested changes...")
        updated_tools = []

        # Create mapping of old -> new categories
        category_map = {c["from"]: c["to"] for c in changes["category_changes"]}

        # Create mapping of tool -> new category
        tool_map = {m["tool"]: m["to"] for m in changes["tool_moves"]}

        for tool in current["tools"]:
            new_tool = tool.copy()
            current_cat = tool.get("category", "Other")

            # Check if tool should move
            if tool["name"] in tool_map:
                new_tool["category"] = tool_map[tool["name"]]
                logger.info(f"Moving {tool['name']} to {new_tool['category']}")
            # Check if category should change
            elif current_cat in category_map:
                new_tool["category"] = category_map[current_cat]
                logger.info(f"Updating category for {tool['name']}: {current_cat} -> {new_tool['category']}")

            updated_tools.append(new_tool)

        # Save changes
        current["tools"] = updated_tools
        save_tools(current)
        logger.info("Reorganization complete!")
    else:
        logger.info("No changes suggested, categories look good!")


async def deduplicate_database() -> None:
    """One-time cleanup to deduplicate the tools database."""
    logger.info("Starting database deduplication...")
    current = load_tools()
    total = len(current["tools"])
    logger.info(f"Processing {total} tools")

    cleaned_tools = await smart_deduplicate_tools(current["tools"])

    # Save cleaned database
    logger.info(f"Removed {total - len(cleaned_tools)} duplicates")
    current["tools"] = cleaned_tools
    save_tools(current)
    logger.info("Deduplication complete!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Tools Website Maintenance Tasks")
    parser.add_argument("task", choices=["deduplicate", "recategorize"], help="Maintenance task to perform")

    args = parser.parse_args()
    setup_logging()

    if args.task == "deduplicate":
        asyncio.run(deduplicate_database())
    elif args.task == "recategorize":
        asyncio.run(recategorize_database())
