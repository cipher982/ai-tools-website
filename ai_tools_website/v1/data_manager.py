"""Data management functionality for AI tools."""

import json
import logging
import os
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Dict

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

from ai_tools_website.v1.storage import local_tools_path
from ai_tools_website.v1.storage import read_local_json
from ai_tools_website.v1.storage import use_local_storage
from ai_tools_website.v1.storage import write_local_json

load_dotenv()

logger = logging.getLogger(__name__)

# Bucket name (minio only)
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "")

# Lazy initialization of Minio client
_minio_client = None


def get_minio_client():
    """Get or create Minio client with lazy initialization."""
    if use_local_storage():
        raise RuntimeError("Local storage enabled; MinIO client is not available")

    missing = [
        name
        for name in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET_NAME")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(f"Missing MinIO configuration: {', '.join(missing)}")

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
    if use_local_storage():
        path = local_tools_path()
        if not path.exists():
            empty_data = {"tools": [], "last_updated": ""}
            write_local_json(path, empty_data)
            logger.info("No local tools.json found, initializing empty list")
            return empty_data
        data = read_local_json(path, {"tools": [], "last_updated": ""})
        logger.info(f"Loaded {len(data.get('tools', [])):,} tools from local storage")
        return data

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
    if use_local_storage():
        path = local_tools_path()
        tools_data.setdefault("tools", [])
        tools_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        write_local_json(path, tools_data)
        logger.info(f"Successfully saved {len(tools_data['tools'])} tools to local storage")
        return

    client = get_minio_client()
    try:
        tools_data.setdefault("tools", [])
        tools_data["last_updated"] = datetime.now(timezone.utc).isoformat()
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
