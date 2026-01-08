"""Fetch HuggingFace model and space metrics.

Uses HuggingFace Hub API. Rate limit is ~300 requests/minute.
No authentication required for public models/spaces.

Set HF_TOKEN environment variable for private repos or higher rate limits.
"""

import logging
import os
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"
HF_TIMEOUT = 15.0  # seconds (model cards can be slow)


def _get_headers() -> dict[str, str]:
    """Build headers for HuggingFace API requests."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "ai-tools-website/1.0",
    }
    token = os.getenv("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_huggingface_id(url: str) -> Optional[tuple[str, str]]:
    """Extract model/space ID and type from a HuggingFace URL.

    Args:
        url: Any URL that might contain a HuggingFace reference

    Returns:
        Tuple of (entity_id, entity_type) where entity_type is "model" or "space",
        or None if not a valid HuggingFace URL

    Examples:
        >>> extract_huggingface_id("https://huggingface.co/meta-llama/Llama-2-7b")
        ("meta-llama/Llama-2-7b", "model")
        >>> extract_huggingface_id("https://huggingface.co/spaces/stabilityai/stable-diffusion")
        ("stabilityai/stable-diffusion", "space")
    """
    if not url:
        return None

    # Match space URLs first (more specific)
    space_match = re.search(r"huggingface\.co/spaces/([^/]+/[^/\?#]+)", url)
    if space_match:
        return (space_match.group(1).rstrip("/"), "space")

    # Match dataset URLs
    dataset_match = re.search(r"huggingface\.co/datasets/([^/]+/[^/\?#]+)", url)
    if dataset_match:
        return (dataset_match.group(1).rstrip("/"), "dataset")

    # Match model URLs (default pattern)
    model_match = re.search(r"huggingface\.co/([^/]+/[^/\?#]+)", url)
    if model_match:
        entity_id = model_match.group(1).rstrip("/")
        # Filter out non-model paths
        if entity_id.startswith(("docs/", "blog/", "papers/", "pricing")):
            return None
        return (entity_id, "model")

    return None


async def fetch_model_stats(model_id: str) -> Optional[dict[str, Any]]:
    """Fetch stats for a HuggingFace model.

    Args:
        model_id: Model identifier (e.g., "meta-llama/Llama-2-7b")

    Returns:
        Dictionary with model stats, or None if fetch failed
    """
    async with httpx.AsyncClient(timeout=HF_TIMEOUT) as client:
        headers = _get_headers()
        model_url = f"{HF_API_BASE}/models/{model_id}"

        try:
            response = await client.get(model_url, headers=headers)

            if response.status_code == 404:
                logger.warning(f"HuggingFace model not found: {model_id}")
                return None

            if response.status_code != 200:
                logger.warning(f"HuggingFace API error {response.status_code} for model {model_id}")
                return None

            data = response.json()

        except httpx.RequestError as exc:
            logger.error(f"HuggingFace request failed for model {model_id}: {exc}")
            return None

        # Build stats object
        stats: dict[str, Any] = {
            "id": model_id,
            "type": "model",
            "author": data.get("author"),
            "model_id": data.get("modelId") or data.get("id"),
            "sha": data.get("sha"),
            "pipeline_tag": data.get("pipeline_tag"),
            "tags": data.get("tags", []),
            "downloads": data.get("downloads", 0),
            "downloads_all_time": data.get("downloadsAllTime"),
            "likes": data.get("likes", 0),
            "library_name": data.get("library_name"),
            "created_at": data.get("createdAt"),
            "last_modified": data.get("lastModified"),
            "private": data.get("private", False),
            "gated": data.get("gated"),
            "disabled": data.get("disabled", False),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Extract model card info if available
        card_data = data.get("cardData") or {}
        if card_data:
            stats["model_card"] = {
                "license": card_data.get("license"),
                "language": card_data.get("language"),
                "datasets": card_data.get("datasets", []),
                "metrics": card_data.get("metrics", []),
                "base_model": card_data.get("base_model"),
                "model_type": card_data.get("model_type"),
            }

        # Extract safetensors info
        safetensors = data.get("safetensors")
        if safetensors:
            parameters = safetensors.get("total")
            if parameters:
                stats["parameters"] = parameters
                # Format as human-readable
                if parameters >= 1_000_000_000:
                    stats["parameters_human"] = f"{parameters / 1_000_000_000:.1f}B"
                elif parameters >= 1_000_000:
                    stats["parameters_human"] = f"{parameters / 1_000_000:.1f}M"
                else:
                    stats["parameters_human"] = f"{parameters:,}"

        # Check for trending/hot status
        if data.get("trending_score"):
            stats["trending_score"] = data.get("trending_score")

        return stats


async def fetch_space_stats(space_id: str) -> Optional[dict[str, Any]]:
    """Fetch stats for a HuggingFace Space.

    Args:
        space_id: Space identifier (e.g., "stabilityai/stable-diffusion")

    Returns:
        Dictionary with space stats, or None if fetch failed
    """
    async with httpx.AsyncClient(timeout=HF_TIMEOUT) as client:
        headers = _get_headers()
        space_url = f"{HF_API_BASE}/spaces/{space_id}"

        try:
            response = await client.get(space_url, headers=headers)

            if response.status_code == 404:
                logger.warning(f"HuggingFace space not found: {space_id}")
                return None

            if response.status_code != 200:
                logger.warning(f"HuggingFace API error {response.status_code} for space {space_id}")
                return None

            data = response.json()

        except httpx.RequestError as exc:
            logger.error(f"HuggingFace request failed for space {space_id}: {exc}")
            return None

        # Build stats object
        stats: dict[str, Any] = {
            "id": space_id,
            "type": "space",
            "author": data.get("author"),
            "likes": data.get("likes", 0),
            "sdk": data.get("sdk"),
            "sdk_version": data.get("sdkVersion"),
            "runtime": data.get("runtime"),
            "created_at": data.get("createdAt"),
            "last_modified": data.get("lastModified"),
            "private": data.get("private", False),
            "disabled": data.get("disabled", False),
            "stage": data.get("stage"),  # e.g., "RUNNING", "STOPPED"
            "tags": data.get("tags", []),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Hardware info
        hardware = data.get("hardware")
        if hardware:
            stats["hardware"] = hardware.get("current") or hardware.get("requested")

        return stats


async def fetch_huggingface_stats(url: str) -> Optional[dict[str, Any]]:
    """Convenience function to fetch stats from any HuggingFace URL.

    Automatically detects if URL points to a model, space, or dataset.

    Args:
        url: HuggingFace URL

    Returns:
        Stats dictionary or None if URL is not valid HuggingFace
    """
    extracted = extract_huggingface_id(url)
    if not extracted:
        return None

    entity_id, entity_type = extracted

    if entity_type == "model":
        return await fetch_model_stats(entity_id)
    elif entity_type == "space":
        return await fetch_space_stats(entity_id)
    elif entity_type == "dataset":
        # Datasets have limited API - return basic info
        return {
            "id": entity_id,
            "type": "dataset",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    return None
