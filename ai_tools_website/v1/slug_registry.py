"""Utilities for managing canonical slug registrations."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Dict
from typing import MutableMapping
from typing import Set

from minio.error import S3Error

from ai_tools_website.v1.data_manager import BUCKET_NAME
from ai_tools_website.v1.data_manager import get_minio_client

logger = logging.getLogger(__name__)

REGISTRY_KEY = "slug_registry.json"
DEFAULT_REGISTRY: Dict[str, Dict] = {
    "tools": {},
    "comparisons": {},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_slug_registry() -> Dict[str, Dict]:
    """Load slug registry stored in MinIO."""
    client = get_minio_client()
    try:
        response = client.get_object(BUCKET_NAME, REGISTRY_KEY)
        data = json.loads(response.read())
        if not isinstance(data, dict):
            raise ValueError("Slug registry payload is not a JSON object")
        return data
    except S3Error as exc:
        if "NoSuchKey" in str(exc):
            logger.info("No slug registry found, initializing new registry")
            return json.loads(json.dumps(DEFAULT_REGISTRY))
        logger.error("Failed to load slug registry: %s", exc)
        raise


def save_slug_registry(registry: Dict[str, Dict]) -> None:
    """Persist slug registry back to MinIO."""
    client = get_minio_client()
    payload = json.dumps(registry, indent=2).encode()
    client.put_object(
        BUCKET_NAME,
        REGISTRY_KEY,
        BytesIO(payload),
        length=len(payload),
        content_type="application/json",
    )
    logger.info("Saved slug registry with %d tool entries", len(registry.get("tools", {})))


def ensure_unique_slug(slug: str, existing: Set[str]) -> str:
    """Ensure slug uniqueness by appending numeric suffix if needed."""
    if slug not in existing:
        existing.add(slug)
        return slug

    base = slug
    counter = 2
    while True:
        candidate = f"{base}-{counter}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        counter += 1


def register_tool_slug(registry: MutableMapping[str, Dict], tool_id: str, slug: str) -> None:
    """Register canonical slug for a tool, tracking history when it changes."""
    tools_section = registry.setdefault("tools", {})
    entry = tools_section.get(tool_id)
    if not entry:
        tools_section[tool_id] = {"current": slug, "history": []}
        return

    current = entry.get("current")
    if current == slug:
        return

    history = entry.setdefault("history", [])
    if current:
        history.append({"slug": current, "replaced_at": _now_iso()})
    entry["current"] = slug


def register_comparison_slug(
    registry: MutableMapping[str, Dict],
    comparison_key: str,
    slug: str,
    *,
    participants: Dict[str, str],
) -> None:
    """Register canonical slug for a comparison pairing."""
    comparisons_section = registry.setdefault("comparisons", {})
    entry = comparisons_section.get(comparison_key)
    if not entry:
        comparisons_section[comparison_key] = {
            "current": slug,
            "participants": participants,
            "history": [],
        }
        return

    current = entry.get("current")
    if current == slug:
        return

    history = entry.setdefault("history", [])
    if current:
        history.append({"slug": current, "replaced_at": _now_iso()})
    entry["current"] = slug
    entry["participants"] = participants


def collect_existing_slugs(registry: Dict[str, Dict]) -> Set[str]:
    """Collect set of existing slugs across tools and comparisons."""
    slugs: Set[str] = set()
    for section in ("tools", "comparisons"):
        entries = registry.get(section, {})
        for entry in entries.values():
            current = entry.get("current")
            if current:
                slugs.add(current)
            for historic in entry.get("history", []):
                candidate = historic.get("slug")
                if candidate:
                    slugs.add(candidate)
    return slugs
