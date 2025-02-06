"""Web search functionality for finding AI tools."""

import logging
from typing import Dict, List
from duckduckgo_search import DDGS
import re

logger = logging.getLogger(__name__)

def clean_description(text: str) -> str:
    """Clean and truncate description text."""
    # Remove extra whitespace and newlines
    text = re.sub(r"\s+", " ", text).strip()
    # Truncate to reasonable length
    return text[:200] + "..." if len(text) > 200 else text

def search_ai_tools(query: str = "new AI tools 2024", max_results: int = 10) -> List[Dict]:
    """Search for AI tools using DuckDuckGo."""
    tools = []
    logger.info(f"Searching for AI tools with query: {query}")
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                query,
                region="wt-wt",  # Worldwide
                safesearch="off",
                max_results=max_results
            ))
            logger.info(f"Found {len(results)} results for query: {query}")
            
            # Log the first result to see its structure
            if results:
                logger.info(f"Sample result structure: {results[0]}")
            
            for r in results:
                # Log each result for debugging
                logger.info(f"Processing result: {r}")
                
                # Skip if title or link is missing
                if not r.get("title"):
                    logger.info("Skipping result: missing title")
                    continue
                if not r.get("href"):  # DuckDuckGo uses 'href' instead of 'link'
                    logger.info("Skipping result: missing href")
                    continue
                if not r.get("body"):  # DuckDuckGo uses 'body' instead of 'description'
                    logger.info("Skipping result: missing body")
                    continue
                    
                # Try to determine category from title/description
                category = "Uncategorized"
                title_lower = r["title"].lower()
                
                if any(term in title_lower for term in ["chat", "llm", "gpt", "language"]):
                    category = "Language Models"
                elif any(term in title_lower for term in ["image", "art", "draw", "stable diffusion"]):
                    category = "Image Generation"
                elif any(term in title_lower for term in ["voice", "speech", "audio"]):
                    category = "Audio & Speech"
                elif any(term in title_lower for term in ["video", "animation"]):
                    category = "Video Generation"
                elif any(term in title_lower for term in ["code", "programming", "developer"]):
                    category = "Developer Tools"
                
                tool = {
                    "name": r["title"][:100],  # Truncate very long titles
                    "description": clean_description(r["body"]),
                    "url": r["href"],  # Use 'href' instead of 'link'
                    "category": category
                }
                
                logger.info(f"Found tool: {tool['name']} in category: {category}")
                tools.append(tool)
    
    except Exception as e:
        logger.error(f"Error searching with query '{query}': {str(e)}", exc_info=True)
    
    logger.info(f"Processed {len(tools)} valid tools from search results")
    return tools

def find_new_tools() -> List[Dict]:
    """Find new AI tools using multiple search queries."""
    queries = [
        "new AI tools 2024",
        "best artificial intelligence tools",
        "AI productivity tools",
        "AI developer tools",
        "AI image generation tools",
        "AI language models tools",
    ]
    
    logger.info(f"Starting search with {len(queries)} queries")
    all_tools = []
    
    for query in queries:
        try:
            tools = search_ai_tools(query, max_results=5)  # Fewer results per query to avoid duplicates
            all_tools.extend(tools)
            logger.info(f"Found {len(tools)} tools for query: {query}")
        except Exception as e:
            logger.error(f"Error processing query '{query}': {str(e)}", exc_info=True)
    
    # Remove duplicates based on URL
    seen_urls = set()
    unique_tools = []
    
    for tool in all_tools:
        if tool["url"] not in seen_urls:
            seen_urls.add(tool["url"])
            unique_tools.append(tool)
    
    logger.info(f"Found {len(unique_tools)} unique tools after deduplication")
    return unique_tools 