from datetime import datetime
from typing import List
from typing import Tuple

from openai import OpenAI
from pydantic import BaseModel

from ai_tools.agent import AITool

client = OpenAI()


class SearchResult(BaseModel):
    """Model for search result item"""

    title: str
    href: str
    body: str = ""


class ScrapedContent(BaseModel):
    """Model for scraped URL content"""

    title: str
    content: str
    url: str


class WebSearchResponse(BaseModel):
    """Model for complete web search response"""

    response: str
    results: List[ScrapedContent]


async def openai_search(query: str) -> Tuple[str, List[SearchResult]]:
    """Search for results using OpenAI's web search API."""

    response = client.responses.create(
        model="gpt-4o",
        tools=[
            {
                "type": "web_search_preview",
                "search_context_size": "high",
            }
        ],
        input=query,
        tool_choice={"type": "web_search_preview"},
    )

    results = []
    seen_urls = set()

    # Extract citations from the response
    for item in response.output:
        if hasattr(item, "content") and item.type == "message":
            print(f"Found {len(item.content)} content items")
            for content_item in item.content:
                if hasattr(content_item, "annotations"):
                    print(f"Found {len(content_item.annotations)} annotations")
                    for annotation in content_item.annotations:
                        if annotation.type == "url_citation":
                            if annotation.url not in seen_urls:
                                results.append(SearchResult(title=annotation.title, href=annotation.url, body=""))
                                seen_urls.add(annotation.url)
                            else:
                                print(f"Skipping duplicate URL: {annotation.url}")
                        else:
                            print(f"Found {content_item.type} annotation")

    print(f"Found {len(results)} results")
    return response.output_text, results


async def scrape_url(url: str) -> ScrapedContent:
    """Simple scraper that gets title and content from a URL.

    Args:
        url: URL to scrape

    Returns:
        ScrapedContent with title and content
    """
    import re

    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                return ScrapedContent(title="", content="", url=url)

            soup = BeautifulSoup(response.text, "html.parser")

            # Get title
            title = ""
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.text.strip()

            # Get content (with better whitespace handling)
            for tag in soup(["script", "style", "header", "footer", "nav"]):
                tag.decompose()

            # Extract text and clean it up
            text = soup.get_text(" ", strip=True)

            # Replace multiple spaces with a single space
            text = re.sub(r"\s+", " ", text)

            # Clean up any remaining oddities
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            content = " ".join(lines)

            return ScrapedContent(
                title=title,
                content=content[:5000],  # Limit size
                url=url,
            )

    except Exception as e:
        return ScrapedContent(title="", content=f"Error: {str(e)}", url=url)


async def web_search(query: str) -> WebSearchResponse:
    """Search the web for information."""
    response_text, search_results = await openai_search(query)
    url_content_list = []
    print(f"Found {len(search_results)} results to scrape")
    for result in search_results:
        url_content = await scrape_url(result.href)
        url_content_list.append(url_content)

    print(f"Returning {len(url_content_list)} scraped results")
    return WebSearchResponse(
        response=response_text,
        results=url_content_list,
    )


def extract_ai_tools(search_response: WebSearchResponse) -> List[AITool]:
    """Extract AI tools from search results and convert to AITool format"""
    current_time = datetime.now().isoformat()
    tools = []

    for result in search_response.results:
        # This is a simple extraction - in a real implementation,
        # you might want to use AI to better extract tool details
        tool = AITool(
            url=result.url,
            name=result.title,
            categories=[],  # This would need better extraction logic
            summary=result.content[:200] if result.content else "",
            discovered_at=current_time,
            last_updated=current_time,
        )
        tools.append(tool)

    return tools


async def main():
    # 1. Get search results
    print("\n===== SEARCHING FOR AI TOOLS =====\n")
    results = await web_search("AI coding assistants")

    print(f"Found {len(results.results)} results:")
    for i, result in enumerate(results.results, 1):
        print(f"{i}. {result.title}")
        print(f"   URL: {result.url}")
        print()

    # 2. Extract AITools
    tools = extract_ai_tools(results)
    for tool in tools:
        print(f"AITool: {tool.name}")
        print(f"URL: {tool.url}")
        print(f"Summary: {tool.summary[:100]}...")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
