"""Sitemap generation and publishing utilities."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from urllib.parse import quote
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import SubElement
from xml.etree.ElementTree import tostring

import click
from minio.error import S3Error

from ai_tools_website.v1.data_manager import BUCKET_NAME
from ai_tools_website.v1.data_manager import get_minio_client
from ai_tools_website.v1.data_manager import load_tools
from ai_tools_website.v1.seo_utils import generate_category_slug
from ai_tools_website.v1.seo_utils import generate_comparison_slug
from ai_tools_website.v1.seo_utils import generate_tool_slug

logger = logging.getLogger(__name__)

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITEMAP_PREFIX = "sitemaps/"
SITEMAP_FILES = {
    "sitemap-static.xml": "Static routes and landing pages",
    "sitemap-tools.xml": "Individual AI tool detail pages",
    "sitemap-categories.xml": "Category listing pages",
    "sitemap-comparisons.xml": "Tool comparison guides",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _choose_lastmod(*values: Optional[str]) -> str:
    best: Optional[datetime] = None
    for value in values:
        candidate = _parse_timestamp(value)
        if not candidate:
            continue
        if best is None or candidate > best:
            best = candidate
    if best is None:
        best = datetime.now(timezone.utc)
    return best.date().isoformat()


def _build_urlset(entries: Iterable[Dict[str, str]]) -> bytes:
    urlset = Element("urlset", xmlns=SITEMAP_NAMESPACE)
    for entry in entries:
        url_element = SubElement(urlset, "url")
        SubElement(url_element, "loc").text = entry["loc"]
        SubElement(url_element, "lastmod").text = entry["lastmod"]
        if "changefreq" in entry:
            SubElement(url_element, "changefreq").text = entry["changefreq"]
        if "priority" in entry:
            SubElement(url_element, "priority").text = entry["priority"]
    return tostring(urlset, encoding="utf-8", xml_declaration=True)


def _build_sitemapindex(entries: Iterable[Dict[str, str]]) -> bytes:
    sitemap_index = Element("sitemapindex", xmlns=SITEMAP_NAMESPACE)
    for entry in entries:
        sitemap_el = SubElement(sitemap_index, "sitemap")
        SubElement(sitemap_el, "loc").text = entry["loc"]
        SubElement(sitemap_el, "lastmod").text = entry["lastmod"]
    return tostring(sitemap_index, encoding="utf-8", xml_declaration=True)


def _latest_lastmod(entries: Iterable[Dict[str, str]]) -> str:
    best: Optional[datetime] = None
    for entry in entries:
        candidate = _parse_timestamp(entry.get("lastmod"))
        if not candidate:
            continue
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return _choose_lastmod(None)
    return best.date().isoformat()


def _build_static_entries(base_url: str) -> List[Dict[str, str]]:
    lastmod = _now_iso()[:10]
    return [
        {"loc": base_url, "lastmod": lastmod},
        {"loc": f"{base_url}/pipeline-status", "lastmod": lastmod},
    ]


def _build_tool_entries(tools: List[Dict[str, str]], base_url: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for tool in tools:
        slug = tool.get("slug") or generate_tool_slug(tool.get("name", ""))
        if not slug:
            continue
        lastmod = _choose_lastmod(
            tool.get("last_reviewed_at"),
            tool.get("last_enhanced_at"),
            tool.get("discovered_at"),
        )
        entries.append(
            {
                "loc": f"{base_url}/tools/{quote(slug)}",
                "lastmod": lastmod,
            }
        )
    return entries


def _build_category_entries(category_metadata: Dict[str, Dict], base_url: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for data in category_metadata.values():
        slug = data.get("slug") or generate_category_slug(data.get("name", ""))
        if not slug:
            continue
        lastmod = _choose_lastmod(data.get("last_rebuilt_at"))
        entries.append(
            {
                "loc": f"{base_url}/category/{quote(slug)}",
                "lastmod": lastmod,
            }
        )
    return entries


def _build_comparison_entries(tools: List[Dict[str, Dict]], base_url: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    seen_slugs = set()
    for tool in tools:
        comparisons = tool.get("comparisons", {})
        for comparison in comparisons.values():
            slug = comparison.get("slug")
            if not slug:
                opportunity = comparison.get("opportunity", {})
                slug = generate_comparison_slug(
                    opportunity.get("tool1", ""),
                    opportunity.get("tool2", ""),
                )
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            lastmod = _choose_lastmod(comparison.get("last_generated_at"))
            entries.append(
                {
                    "loc": f"{base_url}/compare/{quote(slug)}",
                    "lastmod": lastmod,
                }
            )
    return entries


def build_sitemaps(tools_data: Dict[str, Dict], base_url: str) -> Dict[str, bytes]:
    """Build sitemap XML blobs for all sections."""
    normalized_base = base_url.rstrip("/")
    tools = tools_data.get("tools", [])
    category_metadata = tools_data.get("category_metadata") or {}

    if not category_metadata:
        provisional: Dict[str, Dict] = {}
        for tool in tools:
            name = tool.get("category", "Other")
            slug = generate_category_slug(name)
            entry = provisional.setdefault(slug, {"name": name, "slug": slug, "last_rebuilt_at": None})
            entry["last_rebuilt_at"] = _choose_lastmod(entry.get("last_rebuilt_at"), tool.get("last_reviewed_at"))
        category_metadata = provisional

    static_entries = _build_static_entries(normalized_base)
    tool_entries = _build_tool_entries(tools, normalized_base)
    category_entries = _build_category_entries(category_metadata, normalized_base)
    comparison_entries = _build_comparison_entries(tools, normalized_base)

    sitemap_blobs = {
        "sitemap-static.xml": _build_urlset(static_entries),
        "sitemap-tools.xml": _build_urlset(tool_entries),
        "sitemap-categories.xml": _build_urlset(category_entries),
        "sitemap-comparisons.xml": _build_urlset(comparison_entries),
    }

    sitemap_base = f"{normalized_base}/sitemaps"
    index_entries = []
    entry_map = {
        "sitemap-static.xml": static_entries,
        "sitemap-tools.xml": tool_entries,
        "sitemap-categories.xml": category_entries,
        "sitemap-comparisons.xml": comparison_entries,
    }

    for filename, xml_blob in sitemap_blobs.items():
        if filename == "sitemap-index.xml":
            continue
        lastmod = _latest_lastmod(entry_map.get(filename, []))
        index_entries.append(
            {
                "loc": f"{sitemap_base}/{quote(filename)}",
                "lastmod": lastmod,
            }
        )
    sitemap_blobs["sitemap-index.xml"] = _build_sitemapindex(index_entries)
    return sitemap_blobs


def publish_sitemaps(base_url: str, *, dry_run: bool = False) -> Dict[str, bytes]:
    """Load tools data and publish sitemap files to MinIO."""
    tools_data = load_tools()
    sitemaps = build_sitemaps(tools_data, base_url)

    if dry_run:
        logger.info("Dry run enabled; sitemap XML not uploaded.")
        return sitemaps

    client = get_minio_client()
    for filename, content in sitemaps.items():
        key = f"{SITEMAP_PREFIX}{filename}"
        data = BytesIO(content)
        client.put_object(
            BUCKET_NAME,
            key,
            data,
            length=len(content),
            content_type="application/xml",
        )
        logger.info("Uploaded %s (%d bytes)", key, len(content))
    return sitemaps


def fetch_sitemap(filename: str) -> Optional[str]:
    """Fetch a sitemap file from MinIO."""
    client = get_minio_client()
    key = f"{SITEMAP_PREFIX}{filename}"
    try:
        response = client.get_object(BUCKET_NAME, key)
        return response.read().decode("utf-8")
    except S3Error as exc:
        if "NoSuchKey" not in str(exc):
            logger.warning("Failed to fetch sitemap %s: %s", filename, exc)
        return None


@click.command()
@click.option("--base-url", help="Absolute base URL for the site (e.g., https://drose.io/aitools).")
@click.option("--dry-run", is_flag=True, help="Render sitemaps without uploading to storage.")
def main(base_url: Optional[str], dry_run: bool) -> None:
    """CLI entry point for sitemap publishing."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    resolved_base = base_url or os.getenv("SERVICE_URL_WEB")
    if not resolved_base:
        base_path = os.getenv("BASE_PATH", "").rstrip("/")
        resolved_base = f"https://drose.io{base_path}"
    publish_sitemaps(resolved_base, dry_run=dry_run)


if __name__ == "__main__":
    main()
