"""Web search functionality for finding AI tools."""

import logging
import os
from typing import Dict
from typing import List
from typing import Literal

from diskcache import Cache
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from pydantic import Field
from tavily import TavilyClient

load_dotenv()


logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tavily_client = TavilyClient(os.getenv("TAVILY_API_KEY"))

# Development mode flag - set via environment variable
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
print(f"DEV_MODE: {DEV_MODE}")

# Cache with 24 hour expiry and 1GB size limit
cache = Cache("dev_cache", size_limit=int(1e9), timeout=60 * 60 * 24) if DEV_MODE else None

CategoryType = Literal[
    "Language Models", "Image Generation", "Audio & Speech", "Video Generation", "Developer Tools", "Other"
]


class ToolInfo(BaseModel):
    name: str = Field(description="Clean, concise name of the AI tool")
    description: str = Field(description="Clear, focused description under 150 chars")
    category: CategoryType
    confidence: int = Field(description="Confidence score between 0 and 100")


class AnalysisResult(BaseModel):
    is_valid_tool: bool = Field(description="Whether this is an actual AI tool/product")
    reason: str = Field(description="Brief explanation of the decision")
    tool_info: ToolInfo | None = Field(None, description="Tool information if is_valid_tool is true")


class AnalysisResponse(BaseModel):
    results: List[AnalysisResult]


def classify_results(results: List[Dict]) -> List[Dict]:
    """Use OpenAI to classify search results as valid tools or not."""

    # Prepare the results for the prompt
    results_text = "\n\n".join([f"Title: {r['title']}\nURL: {r['href']}\nDescription: {r['body']}" for r in results])

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",  # DONT CHANGE THIS
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert curator of AI tools. 
Analyze the search results and identify which ones are actual AI tools/products (not articles or lists).
For valid tools, provide clean names, concise descriptions, and appropriate categorization.""",
                },
                {"role": "user", "content": f"Here are the results to analyze:\n\n{results_text}"},
            ],
            response_format=AnalysisResponse,
        )

        analysis = completion.choices[0].message.parsed
        logger.info(f"LLM Analysis: {analysis.model_dump_json(indent=2)}")

        # Process the results
        valid_tools = []
        for idx, (result, analysis_item) in enumerate(zip(results, analysis.results)):
            if analysis_item.is_valid_tool and analysis_item.tool_info and analysis_item.tool_info.confidence > 80:
                tool = {
                    "name": analysis_item.tool_info.name,
                    "description": analysis_item.tool_info.description,
                    "url": result["href"],
                    "category": analysis_item.tool_info.category,
                }
                valid_tools.append(tool)
                logger.info(f"Accepted tool: {tool['name']} ({analysis_item.tool_info.confidence}% confidence)")
            else:
                logger.info(f"Rejected result: {result['title']} - {analysis_item.reason}")

        return valid_tools
    except Exception as e:
        logger.error(f"Error in LLM classification: {str(e)}", exc_info=True)
        return []


def search_ai_tools(query: str, max_results: int = 15) -> List[Dict]:
    """Search for AI tools using Tavily."""
    tools = []
    logger.info(f"Searching for AI tools with query: {query}")

    # Check cache first in dev mode
    if DEV_MODE and query in cache:
        logger.info(f"Using cached results for query: {query}")
        return cache[query]

    try:
        # Use Tavily to search with better filtering
        results = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=min(max_results, 20),  # Tavily max is 20
            include_domains=["github.com", "producthunt.com", "huggingface.co", "replicate.com"],
        )

        # Process results in batches of 5
        tavily_results = [{"title": r["title"], "href": r["url"], "body": r["content"]} for r in results["results"]]

        for i in range(0, len(tavily_results), 5):
            batch = tavily_results[i : i + 5]
            valid_tools = classify_results(batch)
            tools.extend(valid_tools)

        # Cache results in dev mode
        if DEV_MODE:
            cache[query] = tools
            logger.info(f"Cached results for query: {query}")

    except Exception as e:
        logger.error(f"Error searching with query '{query}': {str(e)}", exc_info=True)

    return tools


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
