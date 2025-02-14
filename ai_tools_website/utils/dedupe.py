import asyncio
import logging

from ai_tools_website.data_manager import load_tools
from ai_tools_website.data_manager import save_tools
from ai_tools_website.logging_config import setup_logging
from ai_tools_website.search import smart_deduplicate_tools

# Set up logger
logger = logging.getLogger(__name__)


async def run_dedupe():
    """Run smart deduplication on tools database."""
    # Load current tools
    current = load_tools()
    logger.info(f"Starting deduplication of {len(current['tools'])} tools")

    # Run deduplication
    cleaned = await smart_deduplicate_tools(current["tools"])

    # Save results
    current["tools"] = cleaned
    save_tools(current)
    logger.info(f"Deduplication complete. {len(current['tools'])} -> {len(cleaned)} tools")


if __name__ == "__main__":
    setup_logging()
    asyncio.run(run_dedupe())
