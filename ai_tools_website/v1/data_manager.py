"""Data management functionality for AI tools."""

import json
import logging
import os
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

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


def _attach_meta(payload: Dict[str, Any], *, etag: Optional[str] = None, last_modified: Optional[str] = None) -> None:
    """Attach metadata used for optimistic concurrency checks."""
    base_tools = json.loads(json.dumps(payload.get("tools", [])))
    payload["_meta"] = {
        "etag": etag,
        "last_modified": last_modified,
        "last_updated": payload.get("last_updated"),
        "base_tools": base_tools,
    }


def _tool_key(tool: Dict[str, Any]) -> Optional[str]:
    tool_id = tool.get("id")
    if tool_id:
        return f"id:{tool_id}"
    slug = tool.get("slug")
    if slug:
        return f"slug:{slug}"
    return None


def _map_tools(tools: list[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], list[str]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    order: list[str] = []
    for tool in tools:
        key = _tool_key(tool)
        if not key:
            continue
        if key not in mapping:
            order.append(key)
        mapping[key] = tool
    return mapping, order


def _merge_tool(base: Dict[str, Any], ours: Dict[str, Any], latest: Dict[str, Any]) -> Dict[str, Any]:
    """Three-way merge: apply our changes onto latest, preserving others."""
    merged = dict(latest)
    keys = set(base.keys()) | set(ours.keys()) | set(latest.keys())
    for key in keys:
        base_val = base.get(key)
        ours_val = ours.get(key)
        latest_val = latest.get(key)
        if ours_val != base_val:
            merged[key] = ours_val
        else:
            merged[key] = latest_val
    return merged


def _merge_tools_on_conflict(
    *,
    base_tools: list[Dict[str, Any]],
    ours_tools: list[Dict[str, Any]],
    latest_tools: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Merge tool lists with a three-way strategy on conflicts."""
    base_map, _ = _map_tools(base_tools)
    ours_map, _ = _map_tools(ours_tools)
    latest_map, latest_order = _map_tools(latest_tools)

    # Apply updates and additions
    for key, ours in ours_map.items():
        base = base_map.get(key)
        latest = latest_map.get(key)

        if latest is None:
            # New tool or tool deleted in latest: add ours
            latest_map[key] = ours
            latest_order.append(key)
            continue

        if base is None:
            # Tool added after base load; prefer our fields where provided
            merged = dict(latest)
            merged.update(ours)
            latest_map[key] = merged
            continue

        # Three-way merge
        latest_map[key] = _merge_tool(base, ours, latest)

    # Apply removals conservatively: only remove if latest unchanged from base
    for key, base in base_map.items():
        if key in ours_map:
            continue
        latest = latest_map.get(key)
        if latest is None:
            continue
        if latest == base:
            latest_map.pop(key, None)
            if key in latest_order:
                latest_order.remove(key)

    return [latest_map[key] for key in latest_order if key in latest_map]


def load_tools() -> Dict:
    """Load tools data from Minio storage."""
    if use_local_storage():
        path = local_tools_path()
        if not path.exists():
            empty_data = {"tools": [], "last_updated": ""}
            write_local_json(path, empty_data)
            _attach_meta(empty_data, last_modified=datetime.now(timezone.utc).isoformat())
            logger.info("No local tools.json found, initializing empty list")
            return empty_data
        data = read_local_json(path, {"tools": [], "last_updated": ""})
        last_modified = None
        try:
            stat = path.stat()
            last_modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        except Exception:
            last_modified = None
        _attach_meta(data, last_modified=last_modified)
        logger.info(f"Loaded {len(data.get('tools', [])):,} tools from local storage")
        return data

    client = get_minio_client()
    try:
        data = client.get_object(BUCKET_NAME, "tools.json")
        response = json.loads(data.read())
        etag = None
        last_modified = None
        try:
            stat = client.stat_object(BUCKET_NAME, "tools.json")
            etag = stat.etag
            if stat.last_modified:
                last_modified = stat.last_modified.isoformat()
        except Exception:
            pass
        _attach_meta(response, etag=etag, last_modified=last_modified)
        logger.info(f"Loaded {len(response['tools']):,} tools from Minio")
        return response
    except S3Error as e:
        if "NoSuchKey" in str(e):
            logger.info("No tools.json found, initializing empty list")
            empty_data = {"tools": [], "last_updated": ""}
            save_tools(empty_data)
            _attach_meta(empty_data)
            return empty_data
        logger.error(f"Failed to get tools.json: {e}")
        raise


def save_tools(tools_data: Dict) -> None:
    """Save tools data to Minio storage."""
    meta = tools_data.get("_meta")
    expected_etag = meta.get("etag") if isinstance(meta, dict) else None
    expected_last_modified = meta.get("last_modified") if isinstance(meta, dict) else None
    payload = dict(tools_data)
    payload.pop("_meta", None)

    if use_local_storage():
        path = local_tools_path()
        if expected_last_modified and path.exists():
            try:
                stat = path.stat()
                current_last_modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
                if current_last_modified != expected_last_modified:
                    # Try merge if we have a base snapshot
                    base_tools = meta.get("base_tools") if isinstance(meta, dict) else None
                    if base_tools is None:
                        raise RuntimeError("tools.json changed since load (local storage)")
                    latest = read_local_json(path, {"tools": [], "last_updated": ""})
                    merged_tools = _merge_tools_on_conflict(
                        base_tools=base_tools,
                        ours_tools=payload.get("tools", []),
                        latest_tools=latest.get("tools", []),
                    )
                    payload = dict(latest)
                    payload["tools"] = merged_tools
            except Exception as exc:
                raise RuntimeError(f"tools.json changed since load (local storage): {exc}") from exc
        payload.setdefault("tools", [])
        payload["last_updated"] = datetime.now(timezone.utc).isoformat()
        write_local_json(path, payload)
        logger.info(f"Successfully saved {len(payload['tools'])} tools to local storage")
        return

    client = get_minio_client()
    try:
        if expected_etag:
            try:
                stat = client.stat_object(BUCKET_NAME, "tools.json")
                current_etag = stat.etag
            except Exception as exc:
                raise RuntimeError(f"Failed to stat tools.json before save: {exc}") from exc
            if current_etag and current_etag != expected_etag:
                base_tools = meta.get("base_tools") if isinstance(meta, dict) else None
                if base_tools is None:
                    raise RuntimeError("tools.json changed since load (etag mismatch)")
                latest_resp = client.get_object(BUCKET_NAME, "tools.json")
                latest = json.loads(latest_resp.read())
                latest_resp.close()
                latest_resp.release_conn()
                merged_tools = _merge_tools_on_conflict(
                    base_tools=base_tools,
                    ours_tools=payload.get("tools", []),
                    latest_tools=latest.get("tools", []),
                )
                payload = dict(latest)
                payload["tools"] = merged_tools
        payload.setdefault("tools", [])
        payload["last_updated"] = datetime.now(timezone.utc).isoformat()
        data = BytesIO(json.dumps(payload, indent=2).encode())
        client.put_object(
            BUCKET_NAME,
            "tools.json",
            data,
            length=data.getbuffer().nbytes,
            content_type="application/json",
        )
        logger.info(f"Successfully saved {len(payload['tools'])} tools to Minio")
    except S3Error as e:
        logger.error(f"Failed to update tools: {e}")
        raise


def save_tools_with_retry(tools_data: Dict, *, max_attempts: int = 3, delay_seconds: float = 0.2) -> None:
    """Save tools with retry + merge on conflicts."""
    base_tools = None
    if isinstance(tools_data.get("_meta"), dict):
        base_tools = tools_data["_meta"].get("base_tools")
    ours_tools = tools_data.get("tools", [])

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            save_tools(tools_data)
            return
        except RuntimeError as exc:
            last_exc = exc
            msg = str(exc)
            if "changed since load" not in msg and "etag mismatch" not in msg:
                raise
            if attempt >= max_attempts - 1:
                break

            latest = load_tools()
            latest_tools = latest.get("tools", [])
            if base_tools:
                merged = _merge_tools_on_conflict(
                    base_tools=base_tools,
                    ours_tools=ours_tools,
                    latest_tools=latest_tools,
                )
                tools_data = dict(latest)
                tools_data["tools"] = merged
                base_tools = latest.get("_meta", {}).get("base_tools", latest_tools)
                ours_tools = merged
            else:
                tools_data = dict(latest)
                tools_data["tools"] = ours_tools
                base_tools = latest.get("_meta", {}).get("base_tools", latest_tools)

            if delay_seconds:
                import time

                time.sleep(delay_seconds)

    if last_exc:
        raise last_exc
