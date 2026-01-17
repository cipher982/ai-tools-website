"""Shared utilities for OpenAI Responses API operations.

This module consolidates common patterns used across the pipeline:
- JSON response parsing with markdown fence stripping
- Response text extraction from Responses API payloads
- Citation extraction from API annotations
"""

import json
import logging
import re
from typing import Any
from typing import Optional

logger = logging.getLogger(__name__)


def strip_json_fences(value: str) -> str:
    """Remove Markdown code fences if present.

    Handles both ```json and plain ``` fences.

    Args:
        value: Raw string that may contain markdown code fences

    Returns:
        Cleaned string with fences removed
    """
    value = value.strip()
    if value.startswith("```"):
        first_newline = value.find("\n")
        if first_newline != -1:
            value = value[first_newline + 1 :]
        if value.endswith("```"):
            value = value[:-3]
    return value.strip()


def parse_json_response(raw: str, context: str = "response") -> Optional[dict[str, Any]]:
    """Safely parse JSON content from model output.

    Args:
        raw: Raw string from model output
        context: Description for logging (e.g., "comparison generation")

    Returns:
        Parsed dictionary or None if parsing fails
    """
    try:
        cleaned = strip_json_fences(raw)
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse %s JSON: %s", context, exc)
        return None


def extract_responses_api_text(response: Any) -> str:
    """Extract text content from OpenAI Responses API payload.

    The Responses API returns content in a different structure than
    chat completions. This handles both the convenience output_text
    attribute and the full output structure.

    Args:
        response: Response object from client.responses.create()

    Returns:
        Extracted text content, empty string if none found
    """
    # Try the convenience attribute first
    text = getattr(response, "output_text", "") or ""
    if text:
        return text

    # Fall back to parsing the full output structure
    output_items = getattr(response, "output", None) or []
    collected: list[str] = []
    for item in output_items:
        if getattr(item, "type", None) != "message":
            continue
        for content_item in getattr(item, "content", []) or []:
            content_type = getattr(content_item, "type", None)
            # Handle both "output_text" and "text" content types
            if content_type in ("output_text", "text"):
                piece = getattr(content_item, "text", "")
                if piece:
                    collected.append(piece)
    return "".join(collected)


def extract_responses_api_citations(response: Any) -> list[dict[str, Any]]:
    """Extract citation annotations from OpenAI Responses API payload.

    The Responses API with web_search tool includes annotations with
    citation information. This extracts them in a normalized format.

    Args:
        response: Response object from client.responses.create()

    Returns:
        List of citation dicts with 'title', 'url', 'start_index', 'end_index'
    """
    citations: list[dict[str, Any]] = []

    output_items = getattr(response, "output", None) or []
    for item in output_items:
        if getattr(item, "type", None) != "message":
            continue
        for content_item in getattr(item, "content", []) or []:
            content_type = getattr(content_item, "type", None)
            # Handle both "output_text" and "text" content types
            if content_type not in ("output_text", "text"):
                continue

            # Check for annotations on this content item
            annotations = getattr(content_item, "annotations", None) or []
            for annotation in annotations:
                ann_type = getattr(annotation, "type", None)
                if ann_type == "url_citation":
                    citations.append(
                        {
                            "title": getattr(annotation, "title", "") or "",
                            "url": getattr(annotation, "url", "") or "",
                            "start_index": getattr(annotation, "start_index", 0),
                            "end_index": getattr(annotation, "end_index", 0),
                        }
                    )

    return citations


def count_url_citations(text: str) -> int:
    """Count markdown-style URL citations in text.

    This is a fallback for counting citations when API annotations
    are not available. Counts markdown links like [text](https://...).

    Args:
        text: Text content to search for citations

    Returns:
        Number of markdown URL citations found
    """
    # Match markdown links: [text](url)
    pattern = r"\[([^\]]+)\]\(https?://[^\)]+\)"
    return len(re.findall(pattern, text))


def count_prose_citations(text: str) -> int:
    """Count prose-style citation patterns in text.

    Looks for natural language citation indicators like:
    - "according to..."
    - "pricing page..."
    - "documentation..."

    Args:
        text: Text content to search for citations

    Returns:
        Number of prose citation patterns found
    """
    citation_patterns = [
        "according to",
        "reports that",
        "states that",
        "pricing page",
        "documentation",
        "review on",
        "users report",
        "benchmark shows",
        "study found",
        "analysis by",
    ]

    text_lower = text.lower()
    return sum(1 for pattern in citation_patterns if pattern in text_lower)


def count_all_citations(text: str, api_citations: Optional[list[dict]] = None) -> int:
    """Count total citations from all sources.

    Combines API annotations with fallback text-based counting.
    Avoids double-counting by preferring API citations when available.

    Args:
        text: Text content to search
        api_citations: Pre-extracted API annotations (if available)

    Returns:
        Total citation count
    """
    if api_citations:
        return len(api_citations)

    # Fall back to text-based counting
    url_count = count_url_citations(text)
    prose_count = count_prose_citations(text)
    return url_count + prose_count
