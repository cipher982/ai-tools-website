import json
import logging
from io import BytesIO
from typing import Dict

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinioClient:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = False,
    ) -> None:
        self.bucket_name = bucket_name
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Ensure the bucket exists, create if it doesn't."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Failed to ensure bucket exists: {e}")
            raise

    def get_tools(self) -> Dict:
        """Get tools data from Minio with caching."""
        try:
            data = self.client.get_object(
                self.bucket_name,
                "tools.json",
            )
            response = json.loads(data.read())
            logger.info(f"Loaded {len(response['tools']):,} tools from Minio")
            return response
        except S3Error as e:
            if "NoSuchKey" in str(e):
                logger.info("No tools.json found, initializing empty list")
                empty_data = {"tools": [], "last_updated": ""}
                self.update_tools(empty_data)
                return empty_data
            logger.error(f"Failed to get tools.json: {e}")
            raise

    def update_tools(self, tools_data: Dict) -> None:
        """Update tools data in Minio."""
        try:
            data = BytesIO(json.dumps(tools_data, indent=2).encode())
            self.client.put_object(
                self.bucket_name,
                "tools.json",
                data,
                length=data.getbuffer().nbytes,
                content_type="application/json",
            )
            logger.info("Successfully updated tools.json in Minio")
        except S3Error as e:
            logger.error(f"Failed to update tools: {e}")
            raise
