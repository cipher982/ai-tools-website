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
from .logging_config import IndentLogger
from .logging_config import setup_logging

load_dotenv()

# Set up logger with indentation support
base_logger = logging.getLogger(__name__)
logger = IndentLogger(base_logger)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tavily_client = TavilyClient(os.getenv("TAVILY_API_KEY"))

# Development mode flag - set via environment variable
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
print(f"DEV_MODE: {DEV_MODE}")
MODEL_NAME = "gpt-4o-mini"

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
    category: str = Field(description="Category for this tool, either existing or new if strongly justified")
    confidence: int = Field(description="Confidence in this decision (0-100)")
    reasoning: str = Field(description="Explanation of the decision and any notable changes/improvements")


class SearchAnalysis(BaseModel):
    """Analysis of search results against existing tools"""

    updates: List[ToolUpdate]
    suggestions: Optional[List[str]] = Field(
        None, description="Optional suggestions for improving tool categorization or data quality"
    )


async def analyze_page_content(*, url: str, title: str, content: str, current_tools: Dict) -> Optional[Dict]:
    """Analyze actual page content to verify and enrich tool data."""
    try:
        logger.info("Analyzing content")
        # Organize current tools by category
        tools_by_category = {}
        for tool in current_tools["tools"]:
            cat = tool.get("category", "Other")
            if cat not in tools_by_category:
                tools_by_category[cat] = []
            tools_by_category[cat].append(tool)

        # Build rich context with full tool details
        categories_text = []
        for cat, tools in sorted(tools_by_category.items()):
            tool_details = [f"  - {t['name']}: {t['description']}" for t in tools]
            categories_text.append(f"{cat} ({len(tools)} tools):\n" + "\n".join(tool_details))

        categories_context = "\n\n".join(categories_text)

        completion = client.beta.chat.completions.parse(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": f"""You are an expert AI tool analyst.
Your task is to verify if a webpage represents a real AI tool and categorize it appropriately.

Here is our current database of tools organized by category:

{categories_context}

When analyzing new tools:
1. Verify if this is a direct tool/product page (not a list or article)
2. Identify clear information about what the tool does
3. Verify it's a real, working product
4. Choose the most appropriate category based on our existing tools
5. If the tool represents a new important category, suggest it with strong reasoning""",
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

        # Only return if we're very confident this is a real tool page
        for update in completion.choices[0].message.parsed.updates:
            if update.confidence >= 90 and update.action == "add":
                logger.info(f"Verified ({update.confidence}% confidence)")
                return {"name": update.name, "description": update.description, "url": url, "category": update.category}
            else:
                logger.info(f"Failed: {update.action}")

        return None

    except Exception as e:
        logger.error(f"Error analyzing content: {str(e)}")
        return None


async def verify_and_enrich_tool(url: str, current_tools: Dict) -> Optional[Dict]:
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

            # Analyze the actual page content with current tools context
            return await analyze_page_content(
                url=final_url,
                title=soup.title.text if soup.title else "",
                content=soup.get_text(),
                current_tools=current_tools,
            )

    except Exception as e:
        logger.error(f"Failed to verify tool URL {url}: {str(e)}")
        return None


async def analyze_search_results(search_results: List[Dict], current_tools: Dict) -> List[Dict]:
    """Analyze new search results in context of existing tools."""
    updates = []
    results_text = "\n\n".join(
        [f"Title: {r['title']}\nURL: {r['href']}\nDescription: {r['body']}" for r in search_results]
    )

    try:
        logger.info(f"Filtering {len(search_results)} results")
        completion = client.chat.completions.create(
            model=MODEL_NAME,
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
            response_format={"type": "json_object"},
        )

        analysis = SearchAnalysis.model_validate_json(completion.choices[0].message.content)
        potential_tools = [u for u in analysis.updates if u.confidence >= 80 and u.action == "add"]
        logger.info(f"Found {len(potential_tools)} candidates")

        if potential_tools:
            logger.info("Verifying tools")
            for update in potential_tools:
                verified = await verify_and_enrich_tool(update.url, current_tools)
                if verified:
                    updates.append(verified)
                    logger.info(f"✓ {verified['name']} ({verified['category']})")
                else:
                    logger.info(f"✗ {update.url}")
            logger.info(f"Added {len(updates)} tools")

        return updates

    except Exception as e:
        logger.error(f"Error in analysis: {str(e)}")
        return []


async def tavily_search(query: str, max_results: int = 15) -> List[Dict]:
    """Search for AI tools using Tavily."""
    try:
        if DEV_MODE and query in cache:
            return cache[query]

        results = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=min(max_results, 20),
            include_domains=["github.com", "producthunt.com", "huggingface.co", "replicate.com"],
        )
        tavily_results = [{"title": r["title"], "href": r["url"], "body": r["content"]} for r in results["results"]]

        if DEV_MODE:
            cache[query] = tavily_results
        return tavily_results
    except Exception as e:
        logger.error(f"Search failed: {str(e)}")
        return []


async def filter_results(search_results: List[Dict]) -> List[ToolUpdate]:
    """Filter search results to identify potential tools."""
    try:
        results_text = "\n\n".join(
            f"Title: {r['title']}\nURL: {r['href']}\nDescription: {r['body']}" for r in search_results
        )

        completion = client.beta.chat.completions.parse(
            model=MODEL_NAME,
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

        return [u for u in completion.choices[0].message.parsed.updates if u.confidence >= 80 and u.action == "add"]
    except Exception as e:
        logger.error(f"Filtering failed: {str(e)}")
        return []


async def verify_tool(candidate: ToolUpdate, current_tools: Dict) -> Optional[Dict]:
    """Verify and enrich a potential tool."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as http_client:
            response = await http_client.get(candidate.url)
            final_url = str(response.url)

            # Skip listing pages
            parsed = urlparse(final_url)
            if any(x in parsed.path.lower() for x in ["/search", "/category", "/list", "/tools", "/browse"]):
                return None

            # Extract content
            soup = BeautifulSoup(response.text, "html.parser")
            content = soup.get_text()
            title = soup.title.text if soup.title else ""

            # Analyze
            completion = client.beta.chat.completions.parse(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": build_system_prompt(current_tools),
                    },
                    {
                        "role": "user",
                        "content": f"""Please analyze this webpage content:
URL: {final_url}
Title: {title}
Content: {content[:8000]}""",
                    },
                ],
                response_format=SearchAnalysis,
            )

            for update in completion.choices[0].message.parsed.updates:
                if update.confidence >= 90 and update.action == "add":
                    return {
                        "name": update.name,
                        "description": update.description,
                        "url": final_url,
                        "category": update.category,
                    }
            return None
    except Exception as e:
        logger.error(f"Verification failed: {str(e)}")
        return None


def build_system_prompt(current_tools: Dict) -> str:
    """Build the system prompt with current tool context."""
    tools_by_category = {}
    for tool in current_tools["tools"]:
        cat = tool.get("category", "Other")
        if cat not in tools_by_category:
            tools_by_category[cat] = []
        tools_by_category[cat].append(tool)

    categories_text = []
    for cat, tools in sorted(tools_by_category.items()):
        tool_details = [f"  - {t['name']}: {t['description']}" for t in tools]
        categories_text.append(f"{cat} ({len(tools)} tools):\n" + "\n".join(tool_details))

    return f"""You are an expert AI tool analyst.
Your task is to verify if a webpage represents a real AI tool and categorize it appropriately.

Here is our current database of tools organized by category:

{"\n\n".join(categories_text)}

When analyzing new tools:
1. Verify if this is a direct tool/product page (not a list or article)
2. Identify clear information about what the tool does
3. Verify it's a real, working product
4. Choose the most appropriate category based on our existing tools
5. If the tool represents a new important category, suggest it with strong reasoning"""


def deduplicate_tools(tools: List[Dict]) -> List[Dict]:
    """Remove duplicate tools based on URL and name similarity."""
    seen_urls = set()
    seen_names = set()
    unique_tools = []

    for tool in tools:
        name_key = tool["name"].lower()
        if tool["url"] not in seen_urls and not any(
            existing_name in name_key or name_key in existing_name for existing_name in seen_names
        ):
            seen_urls.add(tool["url"])
            seen_names.add(name_key)
            unique_tools.append(tool)

    return unique_tools


async def find_new_tools() -> List[Dict]:
    """Find and verify new AI tools."""
    logger.info("Starting tool discovery")
    logger.indent()

    # Load data once at start
    current_tools = load_tools()
    logger.info(f"Loaded {len(current_tools['tools'])} existing tools")

    # Define queries based on mode
    queries = [
        "site:producthunt.com new AI tool launch",
        "site:github.com new AI tool release",
        "site:producthunt.com new AI tool launch",
        "site:github.com new AI tool release",
        "site:huggingface.co/spaces new",
        "site:replicate.com new model",
        "site:venturebeat.com new AI tool launch",
        "indie AI tool launch 2024",
        "AI startup launch announcement 2024",
        "new AI tool beta access",
        "launched new AI tool this week",
        "announced new AI platform today",
        "released new artificial intelligence tool",
        "open source AI tool release",
        "new AI model github release",
    ]

    # Process each query
    all_new_tools = []
    for query in queries:
        logger.info(f"Query: {query}")
        logger.indent()

        # Search phase
        results = await tavily_search(query)
        logger.info(f"Found {len(results)} search results")

        # Filter phase
        candidates = await filter_results(results)
        logger.info(f"Identified {len(candidates)} potential tools")

        # Verify phase
        verified = []
        if candidates:
            logger.info("Verifying candidates")
            logger.indent()
            for candidate in candidates:
                logger.info(f"Processing {candidate.url}")
                logger.indent()
                if result := await verify_tool(candidate, current_tools):
                    verified.append(result)
                    logger.info(f"✓ {result['name']} ({result['category']})")
                else:
                    logger.info("✗ Failed verification")
                logger.dedent()
            logger.dedent()

        all_new_tools.extend(verified)
        logger.info(f"Found {len(verified)} new tools")
        logger.dedent()

    # Deduplicate and save
    unique_tools = deduplicate_tools(all_new_tools)
    if unique_tools:
        current_tools["tools"].extend(unique_tools)
        save_tools(current_tools)
        logger.info(f"Added {len(unique_tools)} unique tools (now {len(current_tools['tools'])} total)")
    else:
        logger.info("No new tools found")

    logger.dedent()
    logger.info("Tool discovery complete")
    return unique_tools


async def recategorize_all_tools() -> None:
    """Recategorize all tools in the database with AI assistance."""
    logger.info("Starting tool recategorization...")
    current = load_tools()
    total = len(current["tools"])
    updated_tools = []

    # Process each tool with full context
    for i, tool in enumerate(current["tools"], 1):
        logger.info(f"Processing tool {i}/{total}: {tool['name']}")
        try:
            # Create minimal content from existing tool info
            content = f"""
Name: {tool['name']}
Description: {tool['description']}
URL: {tool['url']}
Current Category: {tool.get('category', 'None')}
            """

            updated = await analyze_page_content(
                url=tool["url"], title=tool["name"], content=content, current_tools=current
            )

            if updated:
                logger.info(f"Recategorized {tool['name']}: {tool.get('category', 'None')} -> {updated['category']}")
                updated_tools.append(updated)
            else:
                logger.warning(f"Failed to recategorize {tool['name']}, keeping original")
                updated_tools.append(tool)

        except Exception as e:
            logger.error(f"Error processing {tool['name']}: {str(e)}")
            updated_tools.append(tool)

    # Save back
    current["tools"] = updated_tools
    save_tools(current)
    logger.info("Recategorization complete!")


if __name__ == "__main__":
    import asyncio

    setup_logging()

    # Check if we should recategorize
    if os.getenv("RECATEGORIZE", "").lower() == "true":
        logger.info("Running recategorization...")
        asyncio.run(recategorize_all_tools())
    else:
        logger.info("Running normal tool search...")
        tools = asyncio.run(find_new_tools())
        if tools:
            current = load_tools()
            current["tools"].extend(tools)
            save_tools(current)
