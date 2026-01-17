"""Classify tools into types that determine page structure and content generation.

Tool types determine:
1. Which data aggregators to use
2. Which sections to render
3. What content prompts to use

This module provides two classification methods:
1. classify_tool() - Rule-based (regex/keyword matching), always available
2. classify_tool_llm() - LLM-based, more accurate but requires API call
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Literal
from typing import Optional

from openai import APIError
from openai import RateLimitError
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from .openai_utils import extract_responses_api_text

logger = logging.getLogger(__name__)


# Pydantic model for LLM classification output
class ToolClassification(BaseModel):
    """Structured output for LLM tool classification."""

    model_config = ConfigDict(extra="forbid")

    tool_type: Literal["open_source", "ml_model", "saas_commercial", "api_service", "developer_tool", "generic"] = (
        Field(description="The primary type of this tool")
    )
    confidence: float = Field(ge=0, le=1, description="Confidence score from 0-1")
    reasoning: str = Field(description="Brief explanation for the classification")


# Cache configuration
CACHE_MAX_SIZE = 10000
CACHE_TTL_HOURS = 24


@dataclass
class CacheEntry:
    """Entry in the classification cache with metadata."""

    result: dict[str, Any]
    created_at: datetime
    model: str


class ClassificationCache:
    """Bounded cache with TTL for LLM classifications."""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl_hours: int = CACHE_TTL_HOURS):
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._ttl = timedelta(hours=ttl_hours)

    def get(self, key: str, model: str) -> Optional[dict[str, Any]]:
        """Get cached result if valid (same model, not expired)."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.model != model:
            # Model changed, invalidate
            del self._cache[key]
            return None
        if datetime.now() - entry.created_at > self._ttl:
            # Expired
            del self._cache[key]
            return None
        return entry.result

    def set(self, key: str, result: dict[str, Any], model: str) -> None:
        """Store result in cache, evicting oldest entries if needed."""
        if len(self._cache) >= self._max_size:
            # Evict oldest 10% of entries
            evict_count = max(1, self._max_size // 10)
            oldest = sorted(self._cache.items(), key=lambda x: x[1].created_at)[:evict_count]
            for k, _ in oldest:
                del self._cache[k]
            logger.debug(f"Evicted {evict_count} oldest cache entries")
        self._cache[key] = CacheEntry(result, datetime.now(), model)

    def clear(self) -> None:
        """Clear all cache entries (useful for testing)."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


# Global cache instance
_classification_cache = ClassificationCache()


# LLM classification system prompt
CLASSIFICATION_SYSTEM_PROMPT = """\
You are an AI tool classifier. Analyze the given tool and classify it into exactly one category.

Categories:
- open_source: Tools hosted on GitHub/GitLab, self-hostable, with open licenses
- ml_model: ML models on HuggingFace, Replicate, etc. - things you run inference on
- saas_commercial: Cloud-based SaaS products with pricing/subscriptions
- api_service: Developer APIs and SDKs for building applications
- developer_tool: CLI tools, IDE extensions, frameworks, libraries
- generic: When none of the above clearly fit

Consider:
- URL patterns (github.com = open_source, huggingface.co = ml_model)
- Description keywords (subscription, pricing = saas_commercial)
- Primary use case and target audience

Be decisive - pick the single best category even if multiple could apply."""


class ToolType:
    """Enumeration of tool types with their characteristics."""

    OPEN_SOURCE = "open_source"
    ML_MODEL = "ml_model"
    SAAS_COMMERCIAL = "saas_commercial"
    API_SERVICE = "api_service"
    DEVELOPER_TOOL = "developer_tool"
    GENERIC = "generic"


# Classification rules: signals that indicate each tool type
CLASSIFICATION_RULES: dict[str, dict[str, Any]] = {
    ToolType.OPEN_SOURCE: {
        "url_patterns": [
            r"github\.com/",
            r"gitlab\.com/",
            r"bitbucket\.org/",
            r"codeberg\.org/",
            r"sourceforge\.net/",
        ],
        "description_signals": [
            "open source",
            "open-source",
            "opensource",
            "mit license",
            "apache license",
            "gpl",
            "bsd license",
            "self-host",
            "self host",
            "fork",
            "contribute",
            "community-driven",
        ],
        "tag_signals": ["open-source", "self-hosted", "foss", "libre"],
        "sections": [
            "overview",
            "github_stats",
            "installation",
            "key_features",
            "community",
            "recent_news",
        ],
        "aggregators": ["github", "pypi", "npm"],
    },
    ToolType.ML_MODEL: {
        "url_patterns": [
            r"huggingface\.co/",
            r"replicate\.com/",
            r"civitai\.com/",
            r"ollama\.com/",
        ],
        "description_signals": [
            "model",
            "transformer",
            "llm",
            "large language model",
            "neural network",
            "fine-tun",
            "pretrain",
            "inference",
            "embedding",
            "diffusion",
            "stable diffusion",
            "checkpoint",
            "weights",
            "parameters",
            "billion parameter",
            "7b",
            "13b",
            "70b",
            "foundation model",
        ],
        "tag_signals": [
            "model",
            "llm",
            "transformer",
            "machine-learning",
            "deep-learning",
            "neural-network",
            "nlp",
            "computer-vision",
        ],
        "category_signals": ["language models", "image generation", "audio", "video"],
        "sections": [
            "overview",
            "model_card",
            "benchmarks",
            "usage_examples",
            "key_features",
            "pricing",
            "recent_news",
        ],
        "aggregators": ["huggingface", "github"],
    },
    ToolType.SAAS_COMMERCIAL: {
        # NOTE: Do NOT match generic TLDs (".com", ".io", ".ai") — almost every tool URL would match.
        # Prefer pricing/app-path signals instead.
        "url_patterns": [
            r"/pricing",
            r"/plans",
            r"/subscribe",
            r"/signup",
            r"/sign-up",
            r"/login",
            r"/app",
            r"app\.",
            r"dashboard",
        ],
        "description_signals": [
            "subscription",
            "pricing",
            "enterprise",
            "pro plan",
            "business plan",
            "free tier",
            "pay per",
            "per month",
            "/month",
            "trial",
            "saas",
            "cloud-based",
            "hosted solution",
        ],
        "pricing_signals": ["free", "starter", "pro", "enterprise", "custom", "$"],
        "sections": [
            "overview",
            "pricing_tiers",
            "key_features",
            "use_cases",
            "alternatives",
            "recent_news",
        ],
        "aggregators": [],  # No external APIs typically
    },
    ToolType.API_SERVICE: {
        "url_patterns": [
            r"/api",
            r"/docs",
            r"developer\.",
            r"platform\.",
        ],
        "description_signals": [
            "api",
            "endpoint",
            "sdk",
            "rest",
            "graphql",
            "webhook",
            "integration",
            "developer",
            "programmatic",
            "authentication",
            "rate limit",
        ],
        "tag_signals": ["api", "sdk", "developer-tools", "integration"],
        "sections": [
            "overview",
            "api_overview",
            "code_examples",
            "key_features",
            "pricing",
            "recent_news",
        ],
        "aggregators": ["github", "pypi", "npm"],
    },
    ToolType.DEVELOPER_TOOL: {
        "url_patterns": [],
        "description_signals": [
            "cli",
            "command line",
            "terminal",
            "ide",
            "editor",
            "plugin",
            "extension",
            "framework",
            "library",
            "toolkit",
            "dev tool",
            "developer tool",
        ],
        "tag_signals": ["cli", "developer-tools", "productivity", "framework"],
        "sections": [
            "overview",
            "installation",
            "key_features",
            "use_cases",
            "github_stats",
            "recent_news",
        ],
        "aggregators": ["github", "pypi", "npm"],
    },
}


def _normalize_text(text: Optional[str]) -> str:
    """Normalize text for signal matching."""
    if not text:
        return ""
    return text.lower().strip()


def _check_url_patterns(url: str, patterns: list[str]) -> bool:
    """Check if URL matches any of the patterns."""
    url_lower = url.lower()
    for pattern in patterns:
        if re.search(pattern, url_lower):
            return True
    return False


def _check_text_signals(text: str, signals: list[str]) -> int:
    """Count how many signals match in the text. Returns count."""
    text_lower = _normalize_text(text)
    return sum(1 for signal in signals if signal in text_lower)


def _calculate_type_score(tool: dict[str, Any], tool_type: str, rules: dict[str, Any]) -> float:
    """Calculate confidence score for a tool being a specific type."""
    score = 0.0

    url = tool.get("url", "")
    description = tool.get("description", "")
    name = tool.get("name", "")
    tags = tool.get("tags", [])
    category = tool.get("category", "")
    pricing = tool.get("pricing", "")

    # URL pattern matching (high weight)
    if _check_url_patterns(url, rules.get("url_patterns", [])):
        score += 3.0

    # Description signal matching
    desc_matches = _check_text_signals(description, rules.get("description_signals", []))
    score += desc_matches * 1.0

    # Name signal matching
    name_matches = _check_text_signals(name, rules.get("description_signals", []))
    score += name_matches * 0.5

    # Tag signal matching
    tag_signals = rules.get("tag_signals", [])
    for tag in tags:
        if _normalize_text(tag) in [_normalize_text(s) for s in tag_signals]:
            score += 1.5

    # Category signal matching
    category_signals = rules.get("category_signals", [])
    if category_signals:
        if _normalize_text(category) in [_normalize_text(s) for s in category_signals]:
            score += 2.0

    # Pricing signal matching (for commercial detection)
    pricing_signals = rules.get("pricing_signals", [])
    if pricing_signals:
        pricing_matches = _check_text_signals(pricing, pricing_signals)
        score += pricing_matches * 1.0

    return score


def classify_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Classify a tool and return type information.

    Args:
        tool: Tool dictionary with at minimum 'url' and 'description'

    Returns:
        Dictionary with:
        - type: The classified tool type
        - confidence: Confidence score (0-1)
        - sections: Recommended sections for this type
        - aggregators: Data aggregators to use
        - scores: All type scores for debugging
    """
    scores: dict[str, float] = {}

    # Calculate score for each type
    for tool_type, rules in CLASSIFICATION_RULES.items():
        scores[tool_type] = _calculate_type_score(tool, tool_type, rules)

    # Find the best match
    if scores:
        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]
    else:
        best_type = ToolType.GENERIC
        best_score = 0.0

    # Calculate confidence (normalize by max possible score ~10)
    confidence = min(best_score / 10.0, 1.0)

    # Fall back to generic if confidence is too low
    if confidence < 0.1:
        best_type = ToolType.GENERIC

    # Get sections and aggregators for the type
    rules = CLASSIFICATION_RULES.get(best_type, {})
    sections = rules.get("sections", ["overview", "key_features", "pricing"])
    aggregators = rules.get("aggregators", [])

    return {
        "type": best_type,
        "confidence": round(confidence, 2),
        "sections": sections,
        "aggregators": aggregators,
        "scores": {k: round(v, 2) for k, v in scores.items()},
    }


def _get_cache_key(tool: dict[str, Any]) -> str:
    """Generate a cache key based on tool ID and description hash."""
    tool_id = tool.get("id") or tool.get("name", "")
    description = tool.get("description", "")
    content = f"{tool_id}:{description}"
    return hashlib.md5(content.encode()).hexdigest()


def classify_tool_llm(
    tool: dict[str, Any],
    client: Any,
    shadow_mode: bool = True,
) -> dict[str, Any]:
    """Classify a tool using LLM with structured outputs.

    This provides more accurate classification than rule-based matching,
    especially for ambiguous tools.

    Args:
        tool: Tool dictionary with name, url, description
        client: OpenAI client instance
        shadow_mode: If True, also run rule-based classification and log differences

    Returns:
        Dictionary with:
        - type: The classified tool type
        - confidence: Confidence score (0-1)
        - sections: Recommended sections for this type
        - aggregators: Data aggregators to use
        - classification_method: "llm" or "rules" (fallback)
    """

    model = os.getenv("MAINTENANCE_MODEL", "gpt-5.2")

    # Check cache first (includes model version and TTL)
    cache_key = _get_cache_key(tool)
    cached_result = _classification_cache.get(cache_key, model)
    if cached_result is not None:
        logger.debug(f"Cache hit for tool classification: {tool.get('name')}")
        return cached_result

    # Prepare tool context for LLM
    tool_context = json.dumps(
        {
            "name": tool.get("name"),
            "url": tool.get("url"),
            "description": tool.get("description", "")[:500],  # Limit length
            "category": tool.get("category"),
            "pricing": tool.get("pricing"),
        },
        indent=2,
    )

    try:
        response = client.responses.create(
            model=model,
            instructions=CLASSIFICATION_SYSTEM_PROMPT,
            input=[{"role": "user", "content": [{"type": "input_text", "text": tool_context}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "tool_classification",
                    "strict": True,
                    "schema": ToolClassification.model_json_schema(),
                }
            },
        )

        output_text = extract_responses_api_text(response)
        if not output_text:
            logger.warning(f"No output from LLM classifier for {tool.get('name')}, falling back to rules")
            return classify_tool(tool)

        # Parse the structured output
        try:
            classification = ToolClassification.model_validate_json(output_text)
        except Exception as parse_exc:
            logger.warning(f"Failed to parse LLM classification: {parse_exc}, falling back to rules")
            return classify_tool(tool)

        # Get sections and aggregators for the classified type
        rules = CLASSIFICATION_RULES.get(classification.tool_type, {})
        sections = rules.get("sections", ["overview", "key_features", "pricing"])
        aggregators = rules.get("aggregators", [])

        result = {
            "type": classification.tool_type,
            "confidence": classification.confidence,
            "sections": sections,
            "aggregators": aggregators,
            "reasoning": classification.reasoning,
            "classification_method": "llm",
        }

        # Shadow mode: compare with rule-based classification
        if shadow_mode:
            rule_result = classify_tool(tool)
            shadow_data = {
                "event": "classification_shadow_compare",
                "tool_name": tool.get("name"),
                "tool_url": tool.get("url"),
                "rule_type": rule_result["type"],
                "rule_confidence": rule_result["confidence"],
                "llm_type": classification.tool_type,
                "llm_confidence": classification.confidence,
                "llm_reasoning": classification.reasoning[:200],
                "match": rule_result["type"] == classification.tool_type,
            }
            if rule_result["type"] != classification.tool_type:
                logger.info("classification_diff %s", json.dumps(shadow_data))
            else:
                logger.debug("classification_match %s", json.dumps(shadow_data))

        # Cache the result (with model version for invalidation on model change)
        _classification_cache.set(cache_key, result, model)
        return result

    except RateLimitError as exc:
        logger.warning(f"Rate limit hit for LLM classifier: {exc}, falling back to rules")
        return classify_tool(tool)
    except APIError as exc:
        logger.warning(f"API error in LLM classifier: {exc}, falling back to rules")
        return classify_tool(tool)
    except Exception as exc:
        logger.error(f"Unexpected error in LLM classifier: {exc}, falling back to rules")
        return classify_tool(tool)


def get_sections_for_type(tool_type: str) -> list[str]:
    """Get the recommended sections for a tool type."""
    rules = CLASSIFICATION_RULES.get(tool_type, {})
    return rules.get("sections", ["overview", "key_features", "pricing"])


def get_aggregators_for_type(tool_type: str) -> list[str]:
    """Get the recommended data aggregators for a tool type."""
    rules = CLASSIFICATION_RULES.get(tool_type, {})
    return rules.get("aggregators", [])


# Quick classification helpers
def is_open_source(tool: dict[str, Any]) -> bool:
    """Check if tool appears to be open source."""
    result = classify_tool(tool)
    return result["type"] == ToolType.OPEN_SOURCE


def is_ml_model(tool: dict[str, Any]) -> bool:
    """Check if tool appears to be an ML model."""
    result = classify_tool(tool)
    return result["type"] == ToolType.ML_MODEL


def is_saas(tool: dict[str, Any]) -> bool:
    """Check if tool appears to be a SaaS product."""
    result = classify_tool(tool)
    return result["type"] == ToolType.SAAS_COMMERCIAL
