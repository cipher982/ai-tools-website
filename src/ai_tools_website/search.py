"""Web search functionality for finding AI tools."""

import logging
import os
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional

from diskcache import Cache
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from pydantic import Field
from tavily import TavilyClient

from .data_manager import load_tools

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


def analyze_search_results(search_results: List[Dict], current_tools: Dict) -> List[Dict]:
    """Analyze new search results in context of existing tools."""

    # Prepare the results for the prompt
    results_text = "\n\n".join(
        [f"Title: {r['title']}\nURL: {r['href']}\nDescription: {r['body']}" for r in search_results]
    )

    try:
        completion = client.chat.completions.parse(
            model="gpt-4o-mini",  # DONT CHANGE THIS
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert curator of AI tools with deep knowledge of the field.
Your task is to analyze new search results and decide how to update our tools database.

For each result:
1. Check if it represents a real AI tool (not an article/list/news)
2. Compare against our existing tools to avoid duplicates
3. Look for opportunities to improve existing entries with better descriptions or categorization
4. Ensure consistent categorization with our existing categories
5. Maintain high quality standards for names and descriptions

Key principles:
- Prefer official sources over third-party listings
- Descriptions should be clear, specific, and under 150 characters
- Categories should match our existing ones
- Confidence should reflect certainty about the tool and data quality
- For updates, only suggest if the new information is clearly better""",
                },
                {
                    "role": "user",
                    "content": f"""Here is our current tools database:
{current_tools}

And here are new search results to analyze:
{results_text}

Please analyze these results and provide structured decisions about how to update our database.
Focus on quality and consistency with our existing data.""",
                },
            ],
            response_format=SearchAnalysis,
        )

        analysis = completion.choices[0].message.parsed
        logger.info(f"LLM Analysis: {analysis.model_dump_json(indent=2)}")

        # Process the analysis and update tools
        updates = []
        for update in analysis.updates:
            if update.confidence >= 80:  # We could make this threshold configurable
                tool_data = {
                    "name": update.name,
                    "description": update.description,
                    "url": update.url,
                    "category": update.category,
                }

                if update.action in ["add", "update"]:
                    updates.append(tool_data)
                    action_type = "new" if update.action == "add" else "updated"
                    logger.info(
                        f"Processed {action_type} tool: {update.name} ({update.confidence}% confidence)\n"
                        f"Reason: {update.reasoning}"
                    )
                else:
                    logger.info(f"Skipped tool: {update.name}\nReason: {update.reasoning}")

        return updates

    except Exception as e:
        logger.error(f"Error in LLM analysis: {str(e)}", exc_info=True)
        return []


def search_ai_tools(query: str, max_results: int = 15) -> List[Dict]:
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

            # Process raw results
            tavily_results = [{"title": r["title"], "href": r["url"], "body": r["content"]} for r in results["results"]]

            # Cache raw Tavily results in dev mode
            if DEV_MODE:
                cache[query] = tavily_results
                logger.info(f"Cached Tavily results for query: {query}")

        # Always do fresh LLM analysis
        logger.info(f"Analyzing {len(tavily_results)} results with LLM")
        tools = analyze_search_results(tavily_results, load_tools())
        logger.info(f"LLM analysis complete, found {len(tools)} valid tools")

        return tools

    except Exception as e:
        logger.error(f"Error searching with query '{query}': {str(e)}", exc_info=True)
        return []


def find_new_tools() -> List[Dict]:
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
            tools = search_ai_tools(query, max_results=10)
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
