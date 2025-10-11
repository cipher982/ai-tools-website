#!/bin/sh
set -e

echo "[$(date -u)] Publishing sitemaps..."
uv run python -m ai_tools_website.v1.sitemap_builder
echo "[$(date -u)] Sitemap publish complete"
