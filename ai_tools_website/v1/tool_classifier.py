"""Classify tools into types that determine page structure and content generation.

Tool types determine:
1. Which data aggregators to use
2. Which sections to render
3. What content prompts to use
"""

import re
from typing import Any
from typing import Optional


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
