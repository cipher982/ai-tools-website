import json
import logging
import uuid
from io import BytesIO
from typing import List

from minio import Minio

from ai_tools.agent import BUCKET
from ai_tools.agent import AITool

logger = logging.getLogger(__name__)


async def check_tool_exists(minio_client: Minio, url: str) -> bool:
    """Check if a tool already exists in the collection by URL"""
    try:
        # List all objects in candidates directory
        objects = minio_client.list_objects(BUCKET, prefix="tools/", recursive=True)

        # Check each object to see if it contains our URL
        for obj in objects:
            try:
                data = minio_client.get_object(BUCKET, obj.object_name)
                tool_data = json.loads(data.read())
                if tool_data.get("url") == url:
                    return True
            except Exception as e:
                logger.error(f"Error checking object {obj.object_name}: {e}")
                continue

        return False
    except Exception as e:
        logger.error(f"Error checking if tool exists: {e}")
        return False


async def save_tool(minio_client: Minio, tool: AITool) -> str:
    """Save an AI tool to the collection"""
    # Check if tool already exists
    exists = await check_tool_exists(minio_client, tool.url)
    if exists:
        return f"Tool already exists: {tool.url}"

    # Create a category string from the list of categories
    category_str = "_".join(tool.categories) if tool.categories else "uncategorized"

    # Save immediately to S3
    key = f"tools/{category_str}/{uuid.uuid4()}.json"
    data = BytesIO(tool.model_dump_json(indent=2).encode())

    try:
        minio_client.put_object(
            BUCKET,
            key,
            data,
            length=data.getbuffer().nbytes,
            content_type="application/json",
        )
        logger.info(f"Tool saved: {tool.url} to {key}")
        return f"Tool saved: {tool.url}"
    except Exception as e:
        logger.error(f"Error saving tool: {e}")
        return f"Error saving tool: {str(e)}"


async def list_tools(minio_client: Minio, category: str = None) -> List[AITool]:
    """List tools from the collection, optionally filtered by category"""
    tools = []
    try:
        # Create the prefix for filtering by category
        prefix = f"tools/{category}/" if category else "tools/"

        # List objects with the prefix
        objects = minio_client.list_objects(BUCKET, prefix=prefix, recursive=True)

        # Get each object's data
        for obj in objects:
            try:
                data = minio_client.get_object(BUCKET, obj.object_name)
                tool_data = json.loads(data.read())
                # Create AITool from the JSON data
                tool = AITool(**tool_data)
                tools.append(tool)
            except Exception as e:
                logger.error(f"Error reading tool {obj.object_name}: {e}")
                continue

        return tools
    except Exception as e:
        logger.error(f"Error listing tools: {e}")
        return []
