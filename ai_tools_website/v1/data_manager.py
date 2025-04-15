"""Data management functionality for AI tools."""

import logging
import os
from typing import Dict

from dotenv import load_dotenv

from .storage import MinioClient

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize Minio client once
minio_client = MinioClient(
    endpoint=os.environ["MINIO_ENDPOINT"],
    access_key=os.environ["MINIO_ACCESS_KEY"],
    secret_key=os.environ["MINIO_SECRET_KEY"],
    bucket_name=os.environ["MINIO_BUCKET_NAME"],
    secure=True,
)


def load_tools() -> Dict:
    """Load tools data from Minio storage."""
    return minio_client.get_tools()


def save_tools(tools_data: Dict) -> None:
    """Save tools data to Minio storage."""
    minio_client.update_tools(tools_data)
    logger.info(f"Saved {len(tools_data['tools'])} tools to Minio")
