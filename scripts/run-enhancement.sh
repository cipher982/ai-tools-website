#!/bin/sh
set -e

MAX_PER_RUN=${CONTENT_ENHANCER_MAX_PER_RUN:-50}
STALE_DAYS=${CONTENT_ENHANCER_STALE_DAYS:-7}

echo "[$(date -u)] Starting content enhancement..."
uv run python -m ai_tools_website.v1.content_enhancer --max-per-run "$MAX_PER_RUN" --stale-days "$STALE_DAYS"
echo "[$(date -u)] Content enhancement finished"
