"""SEO utilities for URL generation and content optimization."""

import re
import unicodedata
from typing import Dict
from typing import List
from urllib.parse import urlparse

DEFAULT_MAX_SLUG_LENGTH = 60
STOPWORDS = {
    "ai",
    "app",
    "apps",
    "and",
    "for",
    "the",
    "tool",
    "tools",
    "with",
}


def generate_slug(text: str, max_length: int = 50) -> str:
    """
    Generate SEO-friendly slug from text.

    Rules:
    - Lowercase, ASCII only
    - Hyphens instead of spaces/underscores
    - Remove punctuation except hyphens
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    """
    if not text:
        return ""

    # Normalize unicode to ASCII
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase
    text = text.lower()

    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)

    # Remove all characters except letters, numbers, and hyphens
    text = re.sub(r"[^a-z0-9\-]", "", text)

    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)

    # Strip leading/trailing hyphens
    text = text.strip("-")

    # Truncate to max length at word boundary
    if len(text) > max_length:
        text = text[:max_length]
        # Find last hyphen to avoid cutting mid-word
        last_hyphen = text.rfind("-")
        if last_hyphen > max_length * 0.7:  # Only if reasonably close to end
            text = text[:last_hyphen]

    return text


def _truncate_slug(parts: List[str], max_length: int) -> str:
    """Truncate slug parts to max length while preserving whole tokens where possible."""
    if not parts:
        return ""

    truncated: List[str] = []
    total_length = 0

    for part in parts:
        part_length = len(part)
        separator = 1 if truncated else 0
        if total_length + separator + part_length > max_length:
            break
        truncated.append(part)
        total_length += separator + part_length

    if truncated:
        return "-".join(truncated)

    # Fallback to hard trim if nothing fits
    raw = "-".join(parts)
    return raw[:max_length].strip("-")


def _sanitize_slug_parts(parts: List[str]) -> List[str]:
    """Remove repetitive stopwords while leaving at least one token."""
    if not parts:
        return []
    filtered = [token for token in parts if token not in STOPWORDS]
    return filtered or parts


def generate_tool_slug(tool_name: str, vendor_name: str = None, *, disambiguator: str | None = None) -> str:
    """
    Generate tool-specific slug with disambiguation logic.

    Examples:
    - "GPT-4" -> "gpt-4"
    - "Claude 3.5 Sonnet" -> "claude-3-5-sonnet"
    - "GitHub Copilot" -> "github-copilot" (keep vendor for disambiguation)
    """
    base_slug = generate_slug(tool_name, max_length=DEFAULT_MAX_SLUG_LENGTH)
    used_disambiguator_as_base = False

    if not base_slug and disambiguator:
        base_slug = generate_slug(disambiguator, max_length=DEFAULT_MAX_SLUG_LENGTH)
        if base_slug:
            used_disambiguator_as_base = True

    if not base_slug and vendor_name:
        base_slug = generate_slug(vendor_name, max_length=DEFAULT_MAX_SLUG_LENGTH)
    if not base_slug:
        return ""

    parts = _sanitize_slug_parts(base_slug.split("-"))
    slug = _truncate_slug(parts, DEFAULT_MAX_SLUG_LENGTH)

    if vendor_name:
        vendor_slug = generate_slug(vendor_name, max_length=20)
        if vendor_slug and not slug.startswith(f"{vendor_slug}-"):
            slug = _truncate_slug([vendor_slug] + slug.split("-"), DEFAULT_MAX_SLUG_LENGTH)

    if disambiguator and not used_disambiguator_as_base:
        disambiguator_slug = generate_slug(disambiguator, max_length=15)
        if disambiguator_slug:
            slug = _truncate_slug(slug.split("-") + [disambiguator_slug], DEFAULT_MAX_SLUG_LENGTH)

    return slug


def generate_category_slug(category_name: str) -> str:
    """Generate category slug with consistent formatting."""
    return generate_slug(category_name, max_length=DEFAULT_MAX_SLUG_LENGTH)


def generate_comparison_slug(
    tool1_name: str,
    tool2_name: str,
    *,
    tool1_slug: str | None = None,
    tool2_slug: str | None = None,
) -> str:
    """Generate comparison page slug."""
    slug1 = tool1_slug or generate_slug(tool1_name, max_length=25)
    slug2 = tool2_slug or generate_slug(tool2_name, max_length=25)
    return f"{slug1}-vs-{slug2}"


def extract_domain_from_url(url: str) -> str:
    """Extract clean domain name from URL for context."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def generate_meta_title(tool_name: str, category: str, max_length: int = 60) -> str:
    """Generate SEO-optimized meta title."""
    base_title = f"{tool_name} - AI {category} Tool Review & Guide"

    if len(base_title) <= max_length:
        return base_title

    # Shorter version if too long
    short_title = f"{tool_name} - AI {category} Tool"
    if len(short_title) <= max_length:
        return short_title

    # Minimal version
    return f"{tool_name} Review"


def generate_meta_description(tool_name: str, description: str, max_length: int = 160) -> str:
    """Generate SEO-optimized meta description."""
    if not description:
        return f"Complete guide to {tool_name}. Features, pricing, alternatives, and how to get started."

    # Clean and truncate description
    clean_desc = description.strip()
    if len(clean_desc) <= max_length:
        return clean_desc

    # Truncate at sentence boundary
    sentences = clean_desc.split(". ")
    result = sentences[0]

    # If first sentence is too long, hard truncate it
    if len(result) > max_length - 3:
        result = result[: max_length - 3] + "..."
        return result

    for sentence in sentences[1:]:
        if len(result + ". " + sentence) <= max_length - 3:
            result += ". " + sentence
        else:
            break

    if not result.endswith("."):
        result += "..."

    return result


def generate_breadcrumb_list(path_segments: List[Dict[str, str]], base_url: str) -> Dict:
    """
    Generate JSON-LD breadcrumb structured data.

    Args:
        path_segments: List of {"name": "Display Name", "url": "relative/path"}
        base_url: Base URL for the site
    """
    items = []

    for i, segment in enumerate(path_segments, 1):
        items.append(
            {
                "@type": "ListItem",
                "position": i,
                "name": segment["name"],
                "item": f"{base_url.rstrip('/')}/{segment['url'].lstrip('/')}",
            }
        )

    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def generate_product_schema(tool: Dict, base_url: str) -> Dict:
    """Generate Product/SoftwareApplication JSON-LD schema."""
    tool_slug = tool.get("slug") or generate_tool_slug(tool["name"])
    tool_url = f"{base_url}/tools/{tool_slug}"

    schema = {
        "@context": "https://schema.org",
        "@type": ["Product", "SoftwareApplication"],
        "name": tool["name"],
        "description": tool["description"],
        "url": tool_url,
        "applicationCategory": tool.get("category", "Software"),
        "operatingSystem": "Web Browser",
    }

    # Add pricing if available
    pricing = tool.get("pricing")
    if pricing:
        offers = {
            "@type": "Offer",
            "url": tool_url,
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        }

        if pricing.lower() == "free":
            offers["price"] = "0"
        elif pricing.lower() == "freemium":
            offers["price"] = "0"
            offers["description"] = "Free tier available with premium options"

        schema["offers"] = offers

    # Add aggregate rating if available
    if tool.get("rating"):
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": tool["rating"],
            "bestRating": "5",
            "worstRating": "1",
            "ratingCount": tool.get("review_count", 1),
        }

    # Add features if available
    if tool.get("features"):
        schema["featureList"] = tool["features"]

    return schema
