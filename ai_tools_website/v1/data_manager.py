"""Data management functionality for AI tools."""

import json
import logging
import os
from io import BytesIO
from typing import Dict

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

load_dotenv()

logger = logging.getLogger(__name__)

# Bucket name
BUCKET_NAME = os.environ["MINIO_BUCKET_NAME"]

# Lazy initialization of Minio client
_minio_client = None


def get_minio_client():
    """Get or create Minio client with lazy initialization."""
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            endpoint=os.environ["MINIO_ENDPOINT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            secure=True,
        )

        # Ensure bucket exists
        try:
            if not _minio_client.bucket_exists(BUCKET_NAME):
                _minio_client.make_bucket(BUCKET_NAME)
                logger.info(f"Created bucket: {BUCKET_NAME}")
        except S3Error as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            raise

    return _minio_client


def load_tools() -> Dict:
    """Load tools data from Minio storage."""
    client = get_minio_client()
    try:
        data = client.get_object(BUCKET_NAME, "tools.json")
        response = json.loads(data.read())
        logger.info(f"Loaded {len(response['tools']):,} tools from Minio")
        return response
    except S3Error as e:
        if "NoSuchKey" in str(e):
            logger.info("No tools.json found, initializing empty list")
            empty_data = {"tools": [], "last_updated": ""}
            save_tools(empty_data)
            return empty_data
        logger.error(f"Failed to get tools.json: {e}")
        raise


def save_tools(tools_data: Dict) -> None:
    """Save tools data to Minio storage."""
    client = get_minio_client()
    try:
        data = BytesIO(json.dumps(tools_data, indent=2).encode())
        client.put_object(
            BUCKET_NAME,
            "tools.json",
            data,
            length=data.getbuffer().nbytes,
            content_type="application/json",
        )
        logger.info(f"Successfully saved {len(tools_data['tools'])} tools to Minio")
    except S3Error as e:
        logger.error(f"Failed to update tools: {e}")
        raise
