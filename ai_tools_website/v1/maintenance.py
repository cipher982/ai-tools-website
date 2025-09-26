"""Maintenance tasks for the AI tools database."""

import asyncio
import logging
from typing import List

from pydantic import BaseModel
from pydantic import Field

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging
from .models import MAINTENANCE_MODEL
from .search import build_category_context
from .search import client
from .search import smart_deduplicate_tools


class CategoryChange(BaseModel):
    """Represents a category name change."""

    from_category: str = Field(alias="from", description="Original category name")
    to_category: str = Field(alias="to", description="New category name")
    reason: str = Field(description="Explanation for the change")


class ToolMove(BaseModel):
    """Represents moving a tool to a different category."""

    tool: str = Field(description="Name of the tool to move")
    from_category: str = Field(alias="from", description="Original category")
    to_category: str = Field(alias="to", description="New category")
    reason: str = Field(description="Explanation for the move")


class RecategorizationChanges(BaseModel):
    """Complete set of categorization changes."""

    category_changes: List[CategoryChange] = Field(default_factory=list)
    tool_moves: List[ToolMove] = Field(default_factory=list)


logger = logging.getLogger(__name__)


async def recategorize_database(auto_accept: bool = False) -> None:
    """Do a complete review and reorganization of tool categories."""
    logger.info("Starting tool recategorization...")
    current = load_tools()
    total = len(current["tools"])
    logger.info(f"Processing {total} tools")

    # Get AI to analyze current categorization and suggest improvements
    categories_text = build_category_context(current)

    completion = client.beta.chat.completions.parse(
        model=MAINTENANCE_MODEL,
        reasoning_effort="low",
        messages=[
            {
                "role": "system",
                "content": """You are an expert at organizing AI tools into meaningful categories.
Your task is to analyze the current categorization and suggest improvements.
Consider:
1. Categories that could be merged (e.g., 'LLMs' and 'Language Models')
2. Categories that should be split (e.g., if 'Other' contains distinct groups)
3. Tools that might fit better in different categories
4. Category names that could be more clear or consistent

Since this task will run often, be careful to not keep creating more specific categories.
Focus on broad categories that a user will be seeing on a webpage and can quickly scroll through.
Also we can differentiate and mix 'models' and 'tools'. So they can have their own categories.

IMPORTANT RULES FOR CATEGORY NAMES:
1. Must be a simple, concise noun or noun phrase (e.g. "Language Models", "Developer Tools")
2. Never use explanatory phrases or parentheticals as category names
3. Never include words like "redistributed" or "moved to" in category names
4. Keep names short and clear - ideally 1-3 words
5. Use title case consistently


""",
            },
            {
                "role": "user",
                "content": f"""Here is our current database of tools organized by category:

{categories_text}

Analyze this categorization and suggest a revised category structure.""",
            },
        ],
        response_format=RecategorizationChanges,
    )

    changes = completion.choices[0].message.parsed
    logger.info("\nProposed reorganization changes:")

    if not changes.category_changes and not changes.tool_moves:
        logger.info("No changes suggested, categories look good!")
        return

    if changes.category_changes:
        logger.info("\nCategory renames:")
        for change in changes.category_changes:
            logger.info(f"  • {change.from_category} -> {change.to_category}")
            logger.info(f"    Reason: {change.reason}")

    if changes.tool_moves:
        logger.info("\nTool moves:")
        for move in changes.tool_moves:
            logger.info(f"  • {move.tool}: {move.from_category} -> {move.to_category}")
            logger.info(f"    Reason: {move.reason}")

    # Get user confirmation if not auto-accepting
    if not auto_accept:
        response = input("\nApply these changes? (y/n): ").lower().strip()
        if response != "y":
            logger.info("Changes cancelled.")
            return
    else:
        logger.info("Auto-accepting changes...")

    logger.info("Applying changes...")
    updated_tools = []

    # Create mapping of old -> new categories
    category_map = {c.from_category: c.to_category for c in changes.category_changes}

    # Create mapping of tool -> new category
    tool_map = {m.tool: m.to_category for m in changes.tool_moves}

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
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-accept changes without prompting")

    args = parser.parse_args()
    setup_logging()

    if args.task == "deduplicate":
        asyncio.run(deduplicate_database())
    elif args.task == "recategorize":
        asyncio.run(recategorize_database(auto_accept=args.yes))
