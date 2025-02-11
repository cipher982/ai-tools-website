import json
import logging
from functools import lru_cache
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
        secure: bool = True,
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

    @lru_cache(maxsize=1)
    def get_tools(self) -> Dict:
        """Get tools data from Minio with caching."""
        try:
            data = self.client.get_object(
                self.bucket_name,
                "tools.json",
            )
            return json.loads(data.read())
        except S3Error as e:
            logger.error(f"Failed to get tools.json: {e}")
            raise

    def update_tools(self, tools_data: Dict) -> None:
        """Update tools.json in Minio storage."""
        try:
            json_data = json.dumps(tools_data).encode("utf-8")
            self.client.put_object(
                self.bucket_name,
                "tools.json",
                data=json_data,
                length=len(json_data),
                content_type="application/json",
            )
            # Clear the cache after update
            self.get_tools.cache_clear()
            logger.info("Successfully updated tools.json in Minio")
        except S3Error as e:
            logger.error(f"Failed to update tools.json: {e}")
            raise
