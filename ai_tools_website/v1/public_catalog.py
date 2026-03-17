"""Public record normalization for the slim directory reset."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from ai_tools_website.v1.editorial import TOOL_STATUS_CANDIDATE
from ai_tools_website.v1.editorial import TOOL_STATUS_REJECTED
from ai_tools_website.v1.editorial import get_policy_flags
from ai_tools_website.v1.editorial import get_tool_status
from ai_tools_website.v1.seo_utils import generate_category_slug
from ai_tools_website.v1.seo_utils import generate_tool_slug

FIXED_CATEGORIES = (
    "Code Assistants",
    "Agent Tools",
    "Developer Tools",
    "AI Apps",
    "Workflow Automation",
    "Language Models",
    "Image Models",
    "Video Models",
    "Audio Models",
    "Vision Models",
    "Model Platforms",
    "RAG and Search",
    "Evaluation and Monitoring",
    "Training Tools",
    "Creative Tools",
    "Data and Research",
    "Robotics",
    "Other AI Tools",
)

CATEGORY_ORDER = {category: index for index, category in enumerate(FIXED_CATEGORIES)}

LEGACY_CATEGORY_MAP = {
    "Agent Apps": "Agent Tools",
    "Agent Connectors": "Agent Tools",
    "Agent Frameworks": "Agent Tools",
    "Audio Models": "Audio Models",
    "Audio Tools": "Creative Tools",
    "Chat Apps": "AI Apps",
    "Code Assistants": "Code Assistants",
    "Data Tools": "Data and Research",
    "Developer Tools": "Developer Tools",
    "Directories": "Data and Research",
    "Embedding Models": "Language Models",
    "Evaluation and Monitoring": "Evaluation and Monitoring",
    "Gaming Tools": "Other AI Tools",
    "Image Models": "Image Models",
    "Image Tools": "Creative Tools",
    "Inference Runtimes": "Developer Tools",
    "Language Models": "Language Models",
    "Local Apps": "AI Apps",
    "Model Platforms": "Model Platforms",
    "Productivity Tools": "Workflow Automation",
    "RAG and Search": "RAG and Search",
    "Research Tools": "Data and Research",
    "Robotics Tools": "Robotics",
    "SDKs & Libraries": "Developer Tools",
    "Security Tools": "Developer Tools",
    "Training Tools": "Training Tools",
    "Video Models": "Video Models",
    "Video Tools": "Creative Tools",
    "Vision Models": "Vision Models",
    "Workflow Builders": "Workflow Automation",
}


def canonicalize_url(value: Any) -> str:
    """Normalize a URL for stable storage."""
    if value is None:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/")

    path = parsed.path.rstrip("/")
    if path == "/":
        path = ""

    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def category_sort_key(category: str) -> tuple[int, str]:
    """Stable category ordering for public pages."""
    return (CATEGORY_ORDER.get(category, len(CATEGORY_ORDER)), category.lower())


def normalize_fixed_category(category: Any, *, name: str = "", summary: str = "", source_url: str = "") -> str:
    """Map legacy or noisy categories into the fixed public taxonomy."""
    raw = str(category or "").strip()
    if raw in LEGACY_CATEGORY_MAP:
        return LEGACY_CATEGORY_MAP[raw]
    if raw in FIXED_CATEGORIES:
        return raw

    haystack = " ".join([raw, name, summary, source_url]).lower()
    if any(token in haystack for token in {"code assistant", "copilot", "coding agent"}):
        return "Code Assistants"
    if "agent" in haystack:
        return "Agent Tools"
    if any(token in haystack for token in {"workflow", "automation", "productivity"}):
        return "Workflow Automation"
    if any(token in haystack for token in {"rag", "retrieval", "search"}):
        return "RAG and Search"
    if any(token in haystack for token in {"vision", "ocr"}):
        return "Vision Models"
    if any(token in haystack for token in {"audio", "speech", "voice"}):
        return "Audio Models"
    if "video" in haystack:
        return "Video Models"
    if any(token in haystack for token in {"image", "diffusion"}):
        return "Image Models"
    if any(token in haystack for token in {"language model", "llm", "embedding"}):
        return "Language Models"
    return "Other AI Tools"


def get_tool_summary(tool: Mapping[str, Any] | None) -> str:
    """Return the plain-language summary used on public pages."""
    if not isinstance(tool, Mapping):
        return ""

    candidates = [
        tool.get("summary"),
        tool.get("description"),
        (tool.get("editorial") or {}).get("page_angle") if isinstance(tool.get("editorial"), Mapping) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return " ".join(candidate.strip().split())
    return ""


def normalize_tags(tool: Mapping[str, Any] | None) -> list[str]:
    """Return a short, deduped list of public tags."""
    if not isinstance(tool, Mapping):
        return []

    enhanced = tool.get("enhanced_content_v2") if isinstance(tool.get("enhanced_content_v2"), Mapping) else {}
    tags: list[str] = []
    raw_tags = tool.get("tags")
    if isinstance(raw_tags, list):
        tags.extend(str(tag).strip() for tag in raw_tags if str(tag).strip())

    hf_stats = enhanced.get("huggingface_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(hf_stats, Mapping):
        pipeline_tag = hf_stats.get("pipeline_tag")
        if isinstance(pipeline_tag, str) and pipeline_tag.strip():
            tags.append(pipeline_tag.strip())

    gh_stats = enhanced.get("github_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(gh_stats, Mapping):
        language = gh_stats.get("language")
        if isinstance(language, str) and language.strip():
            tags.append(language.strip())

    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        cleaned = " ".join(tag.split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= 8:
            break
    return normalized


def extract_metrics(tool: Mapping[str, Any] | None) -> dict[str, int]:
    """Extract cheap structured metrics from legacy enhanced content."""
    if not isinstance(tool, Mapping):
        return {}

    enhanced = tool.get("enhanced_content_v2") if isinstance(tool.get("enhanced_content_v2"), Mapping) else {}
    metrics: dict[str, int] = {}

    gh_stats = enhanced.get("github_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(gh_stats, Mapping):
        stars = gh_stats.get("stars")
        if isinstance(stars, int) and stars > 0:
            metrics["github_stars"] = stars

    hf_stats = enhanced.get("huggingface_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(hf_stats, Mapping):
        downloads = hf_stats.get("downloads")
        if isinstance(downloads, int) and downloads > 0:
            metrics["hf_downloads"] = downloads

    pypi_stats = enhanced.get("pypi_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(pypi_stats, Mapping):
        downloads = pypi_stats.get("downloads")
        if isinstance(downloads, Mapping):
            last_month = downloads.get("last_month")
            if isinstance(last_month, int) and last_month > 0:
                metrics["pypi_downloads_30d"] = last_month

    npm_stats = enhanced.get("npm_stats") if isinstance(enhanced, Mapping) else {}
    if isinstance(npm_stats, Mapping):
        downloads = npm_stats.get("downloads")
        if isinstance(downloads, Mapping):
            last_month = downloads.get("last_month")
            if isinstance(last_month, int) and last_month > 0:
                metrics["npm_downloads_30d"] = last_month

    return metrics


def infer_source_metadata(tool: Mapping[str, Any] | None, canonical_url: str) -> tuple[str, str]:
    """Infer the best source type + source URL for a tool."""
    if not isinstance(tool, Mapping):
        return ("website", canonical_url)

    enhanced = tool.get("enhanced_content_v2") if isinstance(tool.get("enhanced_content_v2"), Mapping) else {}
    candidates = [
        ("github", ((enhanced.get("github_stats") or {}).get("url") if isinstance(enhanced, Mapping) else None)),
        (
            "huggingface",
            ((enhanced.get("huggingface_stats") or {}).get("url") if isinstance(enhanced, Mapping) else None),
        ),
        ("pypi", ((enhanced.get("pypi_stats") or {}).get("package_url") if isinstance(enhanced, Mapping) else None)),
        ("npm", ((enhanced.get("npm_stats") or {}).get("package_url") if isinstance(enhanced, Mapping) else None)),
    ]

    for source_type, value in candidates:
        source_url = canonicalize_url(value)
        if source_url:
            return (source_type, source_url)

    source_url = canonicalize_url(tool.get("source_url") or tool.get("canonical_url") or canonical_url)
    source_url = source_url or canonical_url
    domain = urlsplit(source_url).netloc.lower()
    if "github.com" in domain:
        return ("github", source_url)
    if "huggingface.co" in domain:
        return ("huggingface", source_url)
    if "pypi.org" in domain:
        return ("pypi", source_url)
    if "npmjs.com" in domain:
        return ("npm", source_url)
    return ("website", source_url)


def get_public_updated_at(tool: Mapping[str, Any] | None) -> str:
    """Choose the best available public-content timestamp."""
    if not isinstance(tool, Mapping):
        return datetime.now(timezone.utc).isoformat()

    for key in (
        "updated_at",
        "enhanced_at_v2",
        "last_enhanced_at",
        "enhanced_at",
        "discovered_at",
        "last_reviewed_at",
    ):
        value = tool.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return datetime.now(timezone.utc).isoformat()


def _compute_content_hash(record: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"content_hash", "updated_at", "discovered_at", "id", "status", "risk_flags"}
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def build_public_tool_record(tool: Mapping[str, Any] | None) -> dict[str, Any]:
    """Project a raw/legacy tool record into the slim public schema."""
    if not isinstance(tool, Mapping):
        return {}

    name = str(tool.get("name") or "").strip()
    slug = str(tool.get("slug") or "").strip() or generate_tool_slug(name)
    summary = get_tool_summary(tool)
    canonical_url = canonicalize_url(tool.get("canonical_url") or tool.get("url") or tool.get("source_url"))
    source_type, source_url = infer_source_metadata(tool, canonical_url)
    category = normalize_fixed_category(
        tool.get("category"),
        name=name,
        summary=summary,
        source_url=source_url or canonical_url,
    )
    status = get_tool_status(tool)
    risk_flags = get_policy_flags(tool)
    discovered_at = str(tool.get("discovered_at") or get_public_updated_at(tool))
    updated_at = str(get_public_updated_at(tool))

    if not canonical_url or not name or not slug:
        status = TOOL_STATUS_REJECTED
        if not canonical_url:
            risk_flags = sorted({*risk_flags, "missing-url"})
        if not name:
            risk_flags = sorted({*risk_flags, "missing-name"})
        if not slug:
            risk_flags = sorted({*risk_flags, "missing-slug"})

    record = {
        "id": str(tool.get("id") or slug),
        "slug": slug,
        "name": name,
        "summary": summary,
        "description": summary,
        "canonical_url": canonical_url,
        "url": canonical_url,
        "category": category,
        "tags": normalize_tags(tool),
        "source_type": source_type,
        "source_url": source_url,
        "metrics": extract_metrics(tool),
        "status": status,
        "risk_flags": risk_flags,
        "discovered_at": discovered_at,
        "updated_at": updated_at,
    }
    record["content_hash"] = _compute_content_hash(record)
    return record


def build_category_metadata(tools: list[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """Build category metadata for the slim public catalog."""
    metadata: dict[str, dict[str, str]] = {}
    for tool in tools:
        category = str(tool.get("category") or "").strip()
        if not category:
            continue
        slug = generate_category_slug(category)
        metadata[slug] = {"name": category, "slug": slug}
    return metadata


def project_tools_document(
    tools_document: Mapping[str, Any],
    *,
    drop_nonpublic: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project a tools document into slim public records."""
    counts = {
        "published": 0,
        "hidden": 0,
        "candidate": 0,
        "rejected": 0,
        "dropped": 0,
    }
    projected: list[dict[str, Any]] = []

    for raw_tool in tools_document.get("tools", []):
        record = build_public_tool_record(raw_tool)
        status = record.get("status")
        if status in counts:
            counts[status] += 1
        if drop_nonpublic and status in {TOOL_STATUS_CANDIDATE, TOOL_STATUS_REJECTED}:
            counts["dropped"] += 1
            continue
        projected.append(record)

    projected.sort(key=lambda tool: (category_sort_key(tool.get("category", "")), tool.get("name", "").lower()))
    return projected, counts
