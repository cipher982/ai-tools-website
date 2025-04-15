import os

import dotenv
from minio import Minio
from pydantic_ai import Agent
from pydantic_ai import RunContext

from ai_tools.constants import AITool
from ai_tools.tools.save_tool import list_tools
from ai_tools.tools.save_tool import save_tool
from ai_tools.tools.web_search import extract_ai_tools
from ai_tools.tools.web_search import web_search

dotenv.load_dotenv()

BUCKET = "ai-tools-db"


s3_client = Minio(
    endpoint=os.environ["MINIO_ENDPOINT"],
    access_key=os.environ["MINIO_ACCESS_KEY"],
    secret_key=os.environ["MINIO_SECRET_KEY"],
    secure=False,
)

websearch_agent = Agent(
    "openai:gpt-4o",
    system_prompt=(
        "Help compile lists of AI tools. "
        "Search the web for information about AI tools "
        "and save them to our database. "
        "Always extract the URL, category, and any relevant notes."
    ),
)


@websearch_agent.tool
async def web_search_tool(ctx: RunContext[str], query: str) -> str:
    """Search the web for information"""
    search_results = await web_search(query)
    tools = extract_ai_tools(search_results)

    # Format the results for display
    formatted_results = []
    for i, tool in enumerate(tools, 1):
        tool_info = f"{i}. {tool.name} - {tool.url}\n   Summary: {tool.summary[:100]}..."
        formatted_results.append(tool_info)

    return f"Found {len(tools)} AI tools:\n\n" + "\n\n".join(formatted_results)


@websearch_agent.tool
async def save_tool_to_db(ctx: RunContext[str], tool: AITool) -> str:
    """Save an AI tool to the collection"""
    return await save_tool(s3_client, tool)


@websearch_agent.tool
async def get_tools_from_db(ctx: RunContext[str], category: str = None) -> str:
    """List tools from the collection"""
    tools = await list_tools(s3_client, category)

    # Format the results for display
    formatted_results = []
    for i, tool in enumerate(tools, 1):
        categories_str = ", ".join(tool.categories) if tool.categories else "Uncategorized"
        tool_info = f"{i}. {tool.name} - {tool.url}\n   Categories: {categories_str}"
        formatted_results.append(tool_info)

    return f"Found {len(tools)} tools:\n\n" + "\n\n".join(formatted_results)


# Example run
async def find_and_save_tools():
    # Search for tools
    search_result = await websearch_agent.run("Find the top 3 AI image generation tools and save them to our database.")
    print(search_result.data)

    # List saved tools
    tools_result = await websearch_agent.run("List all image generation tools we've saved so far.")
    print(tools_result.data)


# For testing
if __name__ == "__main__":
    import asyncio

    asyncio.run(find_and_save_tools())
