from typing import Any
from typing import Dict
from typing import List

from ..v1.models import WEB_SEARCH_MODEL


async def openai_search(query: str) -> List[Dict]:
    """Search for results using OpenAI's web search API.

    Args:
        query: The search query

    Returns:
        List of dictionaries with title, href, and body fields
    """
    from openai import OpenAI

    client = OpenAI()

    response = client.responses.create(
        model=WEB_SEARCH_MODEL,
        tools=[{"type": "web_search_preview"}],
        input=query,
        tool_choice={"type": "web_search_preview"},
    )

    results = []
    seen_urls = set()

    # Extract citations from the response
    for item in response.output:
        if hasattr(item, "content") and item.type == "message":
            for content_item in item.content:
                if hasattr(content_item, "annotations"):
                    for annotation in content_item.annotations:
                        if annotation.type == "url_citation":
                            if annotation.url not in seen_urls:
                                results.append({"title": annotation.title, "href": annotation.url, "body": ""})
                                seen_urls.add(annotation.url)

    return results


async def scrape_url(url: str) -> Dict[str, Any]:
    """Simple scraper that gets title and content from a URL.

    Args:
        url: URL to scrape

    Returns:
        Dictionary with title and content
    """
    import re

    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                return {"title": "", "content": "", "url": url}

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

            return {
                "title": title,
                "content": content[:5000],  # Limit size
                "url": url,
            }

    except Exception as e:
        return {"title": "", "content": f"Error: {str(e)}", "url": url}


async def web_search(query: str) -> List[Dict]:
    """Search the web for information."""
    search_results = await openai_search(query)
    url_content_list = []
    for result in search_results:
        url_content = await scrape_url(result["href"])
        url_content_list.append(url_content)
    return url_content_list


async def main():
    # 1. Get search results
    print("\n===== SEARCHING FOR AI TOOLS =====\n")
    results = await openai_search("AI coding assistants")

    print(f"Found {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"{i}. {result['title']}")
        print(f"   URL: {result['href']}")
        print()

    # 2. Scrape first result
    if results:
        first_url = results[0]["href"]
        print("\n===== SCRAPING FIRST RESULT =====\n")
        print(f"URL: {first_url}")

        content = await scrape_url(first_url)
        print(f"\nTitle: {content['title']}")
        print(f"\nContent preview: {content['content'][:200]}...")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
