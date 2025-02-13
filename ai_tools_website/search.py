"""Web search functionality for finding AI tools."""

import logging
import os
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from diskcache import Cache
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from pydantic import Field
from tavily import TavilyClient

from .data_manager import load_tools
from .data_manager import save_tools
from .logging_config import setup_logging

load_dotenv()

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tavily_client = TavilyClient(os.getenv("TAVILY_API_KEY"))

# Development mode flag - set via environment variable
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
print(f"DEV_MODE: {DEV_MODE}")

# Cache with 24 hour expiry and 1GB size limit
cache = Cache("dev_cache", size_limit=int(1e9), timeout=60 * 60 * 24) if DEV_MODE else None

# Categories must match what we use in tools.json
CategoryType = Literal[
    "Language Models", "Image Generation", "Audio & Speech", "Video Generation", "Developer Tools", "Other"
]

UpdateActionType = Literal["add", "update", "skip"]


class ToolUpdate(BaseModel):
    """Represents an update decision for a tool"""

    action: UpdateActionType = Field(
        description="Action to take: 'add' (new tool), 'update' (modify existing), 'skip' (duplicate/invalid)"
    )
    name: str = Field(description="Clean name of the tool")
    description: str = Field(description="Clear, focused description of what it does")
    url: str = Field(description="Tool's URL")
    category: CategoryType = Field(description="Best matching category based on existing categories")
    confidence: int = Field(description="Confidence in this decision (0-100)")
    reasoning: str = Field(description="Explanation of the decision and any notable changes/improvements")


class SearchAnalysis(BaseModel):
    """Analysis of search results against existing tools"""

    updates: List[ToolUpdate]
    suggestions: Optional[List[str]] = Field(
        None, description="Optional suggestions for improving tool categorization or data quality"
    )


async def analyze_page_content(*, url: str, title: str, content: str) -> Optional[Dict]:
    """Analyze actual page content to verify and enrich tool data."""
    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # DONT CHANGE THIS
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert AI tool analyst.
Your task is to verify if a webpage actually represents a real AI tool by analyzing its content.

Key verification points:
1. Is this a direct tool/product page (not a list, marketplace, or news article)?
2. Can you identify clear information about what the tool does?
3. Is there evidence this is a real, working product (not just an announcement or concept)?

If verified, extract key information in a clean, consistent format.""",
                },
                {
                    "role": "user",
                    "content": f"""Please analyze this webpage content:

URL: {url}
Title: {title}

Content:
{content[:8000]}  # First 8K chars

Verify if this is a real AI tool page and extract key information if it is.""",
                },
            ],
            response_format=SearchAnalysis,
        )

        analysis = completion.choices[0].message.parsed

        # Only return if we're very confident this is a real tool page
        for update in analysis.updates:
            if update.confidence >= 90 and update.action == "add":
                return {
                    "name": update.name,
                    "description": update.description,
                    "url": url,  # Use the final URL after redirects
                }

        return None

    except Exception as e:
        logger.error(f"Error analyzing page content: {str(e)}", exc_info=True)
        return None


async def verify_and_enrich_tool(url: str) -> Optional[Dict]:
    """Visit the URL and verify it's actually a tool's page."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            # Get the actual page
            response = await client.get(url)

            # Check if we got redirected to a different page
            final_url = str(response.url)

            # Skip if we landed on a listing/search page
            parsed = urlparse(final_url)
            if any(x in parsed.path.lower() for x in ["/search", "/category", "/list", "/tools", "/browse"]):
                logger.info(f"Skipping listing page: {final_url}")
                return None

            # Parse the page content
            soup = BeautifulSoup(response.text, "html.parser")

            # Let GPT analyze the actual page content
            return await analyze_page_content(
                url=final_url, title=soup.title.text if soup.title else "", content=soup.get_text()
            )

    except Exception as e:
        logger.error(f"Failed to verify tool URL {url}: {str(e)}")
        return None


async def analyze_search_results(search_results: List[Dict], current_tools: Dict) -> List[Dict]:
    """Analyze new search results in context of existing tools."""
    updates = []

    # First pass with current logic to filter obvious non-tools
    results_text = "\n\n".join(
        [f"Title: {r['title']}\nURL: {r['href']}\nDescription: {r['body']}" for r in search_results]
    )

    try:
        # Initial analysis to filter obvious non-tools
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # DONT CHANGE THIS
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert curator of AI tools.
                    Your task is to do an initial filter of search results to identify potential AI tools.""",
                },
                {
                    "role": "user",
                    "content": f"""Here are search results to analyze\n{results_text}\n
                    Please identify which results likely represent actual AI tools (not articles/lists).""",
                },
            ],
            response_format=SearchAnalysis,
        )

        initial_analysis = completion.choices[0].message.parsed

        # Verify promising candidates by visiting their pages
        for update in initial_analysis.updates:
            if update.confidence >= 80 and update.action == "add":
                verified = await verify_and_enrich_tool(update.url)
                if verified:
                    updates.append(verified)
                    logger.info(f"Verified and added tool: {verified['name']} ({update.url})")
                else:
                    logger.info(f"Failed to verify tool: {update.url}")
            else:
                logger.info(f"Skipping tool: {update.url} ({update.confidence}% confident)")
        return updates

    except Exception as e:
        logger.error(f"Error in search analysis: {str(e)}", exc_info=True)
        return []


async def search_ai_tools(query: str, max_results: int = 15) -> List[Dict]:
    """Search for AI tools using Tavily."""
    logger.info(f"Searching for AI tools with query: {query}")

    try:
        # Check cache first in dev mode for raw Tavily results
        if DEV_MODE and query in cache:
            logger.info(f"Using cached Tavily results for query: {query}")
            tavily_results = cache[query]
        else:
            # Use Tavily to search with better filtering
            results = tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=min(max_results, 20),  # Tavily max is 20
                include_domains=["github.com", "producthunt.com", "huggingface.co", "replicate.com"],
            )

            # Process raw results - standardize the keys
            tavily_results = [{"title": r["title"], "href": r["url"], "body": r["content"]} for r in results["results"]]

            # Cache raw Tavily results in dev mode
            if DEV_MODE:
                cache[query] = tavily_results
                logger.info(f"Cached Tavily results for query: {query}")

        # Always do fresh LLM analysis
        logger.info(f"Analyzing {len(tavily_results)} results with LLM")
        tools = await analyze_search_results(tavily_results, load_tools())
        logger.info(f"LLM analysis complete, found {len(tools)} valid tools")

        return tools

    except Exception as e:
        logger.error(f"Error searching with query '{query}': {str(e)}", exc_info=True)
        return []


async def find_new_tools() -> List[Dict]:
    """Find new AI tools using strategically categorized search queries."""
    # In dev mode, use a minimal set of queries
    if DEV_MODE:
        queries = [
            # Just two queries for faster development
            "site:producthunt.com new AI tool launch",
            "site:github.com new AI tool release",
        ]
        logger.info("Running in development mode with reduced query set")
    else:
        queries = [
            # High-value discovery sources
            "site:producthunt.com new AI tool launch",
            "site:github.com new AI tool release",
            "site:huggingface.co/spaces new",
            "site:replicate.com new model",
            # Startup and indie sources
            "indie AI tool launch 2024",
            "AI startup launch announcement 2024",
            "new AI tool beta access",
            # Time-based discovery
            "launched new AI tool this week",
            "announced new AI platform today",
            "released new artificial intelligence tool",
            # Open source focus
            "open source AI tool release",
            "new AI model github release",
        ]

    logger.info(f"Starting search with {len(queries)} queries")
    all_tools = []

    for query in queries:
        try:
            tools = await search_ai_tools(query, max_results=10)
            all_tools.extend(tools)
            logger.info(f"Found {len(tools)} tools for query: {query}")
        except Exception as e:
            logger.error(f"Error processing query '{query}': {str(e)}", exc_info=True)

    # Enhanced deduplication using both URL and name similarity
    seen_urls = set()
    seen_names = set()
    unique_tools = []

    for tool in all_tools:
        name_key = tool["name"].lower()
        if tool["url"] not in seen_urls and not any(
            existing_name in name_key or name_key in existing_name for existing_name in seen_names
        ):
            seen_urls.add(tool["url"])
            seen_names.add(name_key)
            unique_tools.append(tool)

    logger.info(f"Found {len(unique_tools)} unique tools after deduplication")
    return unique_tools


if __name__ == "__main__":
    import asyncio

    setup_logging()
    tools = asyncio.run(find_new_tools())
    if tools:
        current = load_tools()
        current["tools"].extend(tools)
        save_tools(current)
