"""Web search functionality for finding AI tools."""

import asyncio
import logging
import os
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from urllib.parse import urlparse

import click
import httpx
from bs4 import BeautifulSoup
from diskcache import Cache
from dotenv import load_dotenv
from langsmith.wrappers import wrap_openai
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

client = wrap_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))
tavily_client = TavilyClient(os.getenv("TAVILY_API_KEY"))

MODEL_NAME = "o3-mini"

# Cache settings
CACHE_TIMEOUT = 60 * 60 * 24  # 24 hours
CACHE_SIZE = int(1e9)  # 1GB size limit

cache = None

# Categories must match what we use in tools.json
# CategoryType = Literal[
#     "Language Models", "Image Generation", "Audio & Speech", "Video Generation", "Developer Tools", "Other"
# ]

UpdateActionType = Literal["add", "update", "skip", "error"]


class ToolUpdate(BaseModel):
    """Represents a tool update decision with complete verification status"""

    action: UpdateActionType = Field(
        description="""
        Action to take:
        - 'add' (new tool)
        - 'update' (modify existing)
        - 'skip' (duplicate/invalid)
        - 'error' (verification failed)
        """
    )
    name: str = Field(description="Clean name of the tool")
    description: str = Field(description="Clear, focused description of what it does")
    url: str = Field(description="Tool's URL")
    category: str = Field(
        description="""Category for this tool. Should be concise, descriptive, and group similar tools.
        Use existing categories when appropriate, suggest new ones if tool represents a distinct category."""
    )
    confidence: int = Field(description="Confidence in this decision (0-100)")
    reasoning: str = Field(description="Explanation of the decision and any notable changes/improvements")
    existing_index: Optional[int] = Field(None, description="Index in current tools list if this is an update")


class SearchAnalysis(BaseModel):
    """Analysis of search results against existing tools"""

    updates: List[ToolUpdate]
    suggestions: Optional[List[str]] = Field(
        None, description="Optional suggestions for improving tool categorization or data quality"
    )


class DuplicateStatus(BaseModel):
    """Result of duplicate analysis"""

    status: Literal["skip", "update", "new"] = Field(
        description="Whether to skip, update existing record, or process as new"
    )
    reasoning: str = Field(description="Explanation for the decision")
    confidence: int = Field(description="Confidence in decision (0-100)")


def build_category_context(current_tools: Dict) -> str:
    """Build a text representation of tools organized by category."""
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

    return "\n\n".join(categories_text)


async def normalize_category(suggested_category: str, current_tools: Dict) -> str:
    """Normalize a suggested category against existing ones using full tool context."""
    # First organize tools by category to understand category contents
    tools_by_category = {}
    for tool in current_tools["tools"]:
        cat = tool.get("category", "Other")
        if cat not in tools_by_category:
            tools_by_category[cat] = []
        tools_by_category[cat].append(tool)

    # If no categories yet or exact match, return as-is
    if not tools_by_category or suggested_category in tools_by_category:
        return suggested_category

    categories_text = build_category_context(current_tools)

    completion = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": """You are an expert at organizing AI tools into meaningful categories.
Your task is to either map a suggested category to an existing one if they contain similar types of tools,
or confirm it should be a new category if it represents a truly distinct type of tool.""",
            },
            {
                "role": "user",
                "content": f"""Here is our current database of tools organized by category:

{categories_text}

A new tool is being suggested for the category: {suggested_category}

Based on understanding what tools are in each category:
1. Should this be mapped to an existing category? (if tools are very similar)
2. Or kept as a new category? (if it represents a distinct type of tool)

Reply with just the category name to use.""",
            },
        ],
    )

    normalized = completion.choices[0].message.content.strip()
    logger.info(f"Normalized category: {suggested_category} -> {normalized}")
    return normalized


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
4. Choose or suggest a category based on these principles:
   - Use existing categories if they fit well
   - Suggest new categories if the tool represents a distinct type
   - Keep categories concise but descriptive
   - Group similar tools together
   - Consider merging very similar categories
   - Avoid overly broad or vague categories
5. Explain your category choice in the reasoning field""",
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
                # Normalize the suggested category
                normalized_category = await normalize_category(update.category, current_tools)
                return {
                    "name": update.name,
                    "description": update.description,
                    "url": url,
                    "category": normalized_category,
                }
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
        # Initialize cache for storing results regardless of cache_searches flag
        search_cache = Cache("search_cache", size_limit=CACHE_SIZE, timeout=CACHE_TIMEOUT)

        # Only use cached results if cache_searches is True and query exists in cache
        if cache is not None and query in search_cache:
            return search_cache[query]

        results = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=min(max_results, 20),
            include_domains=["github.com", "producthunt.com", "huggingface.co", "replicate.com"],
        )
        tavily_results = [{"title": r["title"], "href": r["url"], "body": r["content"]} for r in results["results"]]

        # Always cache new results
        search_cache[query] = tavily_results
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


async def verify_tool(candidate: ToolUpdate, current_tools: Dict) -> Optional[ToolUpdate]:
    """Verify and enrich a potential tool."""
    try:
        # First check if this is a duplicate
        dup_status = await check_duplicate_status(candidate, current_tools)
        if dup_status.status == "skip":
            logger.info(f"Skipping {candidate.name}: {dup_status.reasoning}")
            return ToolUpdate(
                action="skip",
                name=candidate.name,
                description=candidate.description,
                url=candidate.url,
                category=candidate.category,
                confidence=dup_status.confidence,
                reasoning=dup_status.reasoning,
            )
        elif dup_status.status == "update":
            # Find the index of the tool to update
            for i, tool in enumerate(current_tools["tools"]):
                if tool["url"].lower() == candidate.url.lower():
                    logger.info(f"Will update {candidate.name}: {dup_status.reasoning}")
                    return ToolUpdate(
                        action="update",
                        name=candidate.name,
                        description=candidate.description,
                        url=candidate.url,
                        category=candidate.category,
                        confidence=dup_status.confidence,
                        reasoning=dup_status.reasoning,
                        existing_index=i,
                    )
        else:
            logger.info(f"Processing new tool: {candidate.name}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as http_client:
            response = await http_client.get(candidate.url)
            final_url = str(response.url)

            # Skip listing pages
            parsed = urlparse(final_url)
            if any(x in parsed.path.lower() for x in ["/search", "/category", "/list", "/tools", "/browse"]):
                return ToolUpdate(
                    action="error",
                    name=candidate.name,
                    description=candidate.description,
                    url=final_url,
                    category=candidate.category,
                    confidence=0,
                    reasoning="Skipping listing/search page",
                )

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
                    return ToolUpdate(
                        action="add",
                        name=update.name,
                        description=update.description,
                        url=final_url,
                        category=update.category,
                        confidence=update.confidence,
                        reasoning="Verified as new tool",
                    )

            return ToolUpdate(
                action="error",
                name=candidate.name,
                description=candidate.description,
                url=final_url,
                category=candidate.category,
                confidence=0,
                reasoning="Failed verification checks",
            )

    except Exception as e:
        logger.error(f"Verification failed: {str(e)}")
        return ToolUpdate(
            action="error",
            name=candidate.name,
            description=candidate.description,
            url=candidate.url,
            category=candidate.category,
            confidence=0,
            reasoning=f"Error during verification: {str(e)}",
        )


def build_system_prompt(current_tools: Dict) -> str:
    """Build the system prompt with current tool context."""
    categories_text = build_category_context(current_tools)

    return f"""You are an expert AI tool analyst.
Your task is to verify if a webpage represents a real AI tool and categorize it appropriately.

Here is our current database of tools organized by category:

{categories_text}

When analyzing new tools:
1. Verify if this is a direct tool/product page (not a list or article)
2. Identify clear information about what the tool does
3. Verify it's a real, working product
4. Choose the most appropriate category based on our existing tools
5. If the tool represents a new important category, suggest it with strong reasoning"""


def deduplicate_tools(tools: List[Dict]) -> List[Dict]:
    """Remove duplicate tools based on exact URL matches (case insensitive).

    Args:
        tools: List of tool dictionaries

    Returns:
        List of tools with duplicates removed, keeping first occurrence
    """
    seen_urls = set()
    unique_tools = []

    for tool in tools:
        url = tool["url"].lower()
        if url not in seen_urls:
            seen_urls.add(url)
            unique_tools.append(tool)

    return unique_tools


async def find_new_tools(*, use_search_cache: bool = False, dry_run: bool = False) -> List[ToolUpdate]:
    """Find and verify new AI tools."""
    logger.info("Starting tool discovery")
    logger.indent()

    # Load data once at start
    current_tools = load_tools()
    logger.info(f"Loaded {len(current_tools['tools'])} existing tools")

    # Set up cache if search caching is enabled
    global cache
    cache = Cache("search_cache", size_limit=CACHE_SIZE, timeout=CACHE_TIMEOUT) if use_search_cache else None

    # Define queries based on mode
    queries = [
        "site:producthunt.com new AI tool launch",
        "site:github.com new AI tool release",
        "site:huggingface.co/spaces new",
        "site:replicate.com new model",
        "site:venturebeat.com new AI tool launch",
        "new AI tool beta access",
        "released new artificial intelligence tool",
        "open source AI tool release",
        "new AI model release",
        "Best AI tools 2025",
        "Top open-source AI models",
    ]

    # Parallel search phase
    logger.info(f"Running {len(queries)} parallel searches")
    search_results = await asyncio.gather(*[tavily_search(query) for query in queries])
    all_results = [r for results in search_results for r in results]  # Flatten
    logger.info(f"Found {len(all_results)} total results")

    # Parallel filter phase
    logger.info("Filtering candidates in parallel")
    candidates = await filter_results(all_results)
    logger.info(f"Identified {len(candidates)} potential tools")

    # Parallel verify phase
    logger.info("Verifying candidates in parallel")
    verified = await asyncio.gather(*[verify_tool(candidate, current_tools) for candidate in candidates])
    verified = [v for v in verified if v]  # Remove None results

    # Log verification results by status
    by_status = defaultdict(list)
    for result in verified:
        by_status[result.action].append(result)

    logger.info("Verification results:")
    logger.indent()
    for action, results in by_status.items():
        logger.info(f"{action.upper()}: {len(results)} tools")
        for result in results:
            logger.info(f"  • {result.name}: {result.reasoning}")
    logger.dedent()

    # Save verified tools
    if verified:
        if dry_run:
            logger.info("[DRY RUN] Would have made the following changes:")
            logger.indent()
            for tool in verified:
                if tool.action in ["add", "update"]:
                    logger.info(f"{tool.action.upper()}: {tool.name} - {tool.reasoning}")
            logger.dedent()
        else:
            # Handle updates first
            for tool in [t for t in verified if t.action == "update" and t.existing_index is not None]:
                current_tools["tools"][tool.existing_index] = {
                    "name": tool.name,
                    "description": tool.description,
                    "url": tool.url,
                    "category": tool.category,
                }
                logger.info(f"Updated tool: {tool.name}")

            # Handle additions
            new_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "url": tool.url,
                    "category": tool.category,
                }
                for tool in verified
                if tool.action == "add"
            ]
            if new_tools:
                current_tools["tools"].extend(new_tools)
                logger.info(f"Added {len(new_tools)} new tools")

            save_tools(current_tools)

    logger.dedent()
    logger.info("Tool discovery complete")
    return verified


async def check_duplicate_status(
    candidate: ToolUpdate,
    current_tools: Dict[str, List[Dict]],
) -> DuplicateStatus:
    """Check if a tool candidate is a duplicate and whether it should be updated.

    Returns decision on whether to skip, update, or process as new.
    """
    # First check for exact URL matches
    existing = None
    for tool in current_tools["tools"]:
        if tool["url"].lower() == candidate.url.lower():
            existing = tool
            break

    # If no URL match, check for name similarity
    if not existing:
        candidate_name = candidate.name.lower()
        for tool in current_tools["tools"]:
            if candidate_name == tool["name"].lower():
                existing = tool
                break

    if not existing:
        return DuplicateStatus(status="new", reasoning="No matching tool found in database", confidence=100)

    # If we found a potential match, use LLM to compare
    completion = client.beta.chat.completions.parse(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": """You are an expert at analyzing AI tools.
Your task is to compare a candidate tool entry against an existing database record
and decide whether to skip it or update the existing record.""",
            },
            {
                "role": "user",
                "content": f"""Please compare these two tool entries.

Decide if the candidate offers enough improvements to warrant updating the existing record.

EXISTING RECORD:
Name: {existing["name"]}
Description: {existing["description"]}
URL: {existing["url"]}
Category: {existing.get("category", "Other")}

CANDIDATE:
Name: {candidate.name}
Description: {candidate.description}
URL: {candidate.url}
Category: {candidate.category}

Decide whether to:
1. SKIP - No substantial differences
2. UPDATE - Candidate has better/newer information""",
            },
        ],
        response_format=DuplicateStatus,
    )

    return completion.choices[0].message.parsed


async def smart_deduplicate_tools(tools: List[Dict]) -> List[Dict]:
    """Smart deduplication of tools using LLM comparison.

    Args:
        tools: List of tool dictionaries to deduplicate

    Returns:
        Deduplicated list of tools, keeping best version of each
    """
    logger.info(f"Smart deduplicating {len(tools)} tools")

    # First pass: quick URL deduplication
    url_deduped = []
    seen_urls = set()
    for tool in tools:
        url = tool["url"].lower()
        if url not in seen_urls:
            seen_urls.add(url)
            url_deduped.append(tool)
        else:
            logger.info(f"URL duplicate found: {tool['url']}")

    logger.info(f"URL deduplication: {len(tools)} -> {len(url_deduped)} tools")

    # Second pass: LLM comparison
    cleaned_tools = []
    logger.info("Starting LLM comparison phase...")

    for i, tool in enumerate(url_deduped, 1):
        logger.info(f"Processing tool {i}/{len(url_deduped)}: {tool['name']}")

        # Compare against already cleaned tools
        candidate = ToolUpdate(
            action="add",
            name=tool["name"],
            description=tool["description"],
            url=tool["url"],
            category=tool.get("category", "Other"),
            confidence=100,
            reasoning="Existing tool",
        )

        if not cleaned_tools:  # First tool, no comparisons needed
            cleaned_tools.append(tool)
            logger.info("First tool, automatically keeping")
            continue

        temp_tools = {"tools": cleaned_tools}
        logger.info(f"Comparing against {len(cleaned_tools)} existing tools")
        status = await check_duplicate_status(candidate, temp_tools)

        if status.status == "new":
            cleaned_tools.append(tool)
            logger.info(f"Keeping new tool: {tool['name']}")
        else:
            logger.info(f"Found duplicate: {tool['name']} - {status.reasoning}")

    logger.info(f"LLM comparison complete: {len(url_deduped)} -> {len(cleaned_tools)} tools")
    return cleaned_tools


@click.command()
@click.option("--use-search-cache", is_flag=True, help="Use cached Tavily search results if available")
@click.option("--dry-run", is_flag=True, help="Run without saving any changes")
def main(use_search_cache: bool, dry_run: bool):
    """Run tool search with optional cached results and dry run flags."""
    setup_logging()
    logger.info("Running tool search...")
    if use_search_cache:
        logger.info("Using cached search results if available")
    if dry_run:
        logger.info("Dry run mode enabled - no changes will be saved")
    asyncio.run(find_new_tools(use_search_cache=use_search_cache, dry_run=dry_run))


if __name__ == "__main__":
    main()
